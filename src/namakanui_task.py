#!/local/python3/bin/python3
'''
20181016 RMB

 86 GHz: Ala'ihi
230 GHz: U'u
345 GHz: Aweoweo

Supervisor for the three cartridge tasks.
Controls the cartridges via DRAMA commands,
but controls other hardware (load, cryostat) directly.

This is an engineering control task, and is expect to run most of the time.
The frontend (wrapper) tasks for ACSIS will remain separate.


'''

import jac_sw
import drama
import sys
import os
import time
import subprocess
from namakanui.includeparser import IncludeParser
import namakanui.cryo
import namakanui.load
# NOTE the reference signal generator interface should be more generic.
import namakanui.agilent

import argparse
parser = argparse.ArgumentParser()
parser.add_argument('taskname')
#parser.add_argument('inifile')
args = parser.parse_args()
taskname = args.taskname

import drama.log
drama.log.setup()  # no taskname, so no /jac_logs file output
import logging
log = logging.getLogger(args.taskname)

# always use sibling cartridge_task.py (vs one in $PATH)
binpath = os.path.dirname(os.path.realpath(sys.argv[0])) + '/'
datapath = os.path.realpath(binpath + '../../data') + '/'

initialised = False
inifile = None

agilent = None
cryo = None
load = None

# indexed by band number (int)
cartridge_tasknames = {}  
cold_mult = {}
warm_mult = {}



def INITIALISE(msg):
    '''
    '''
    global initialised, inifile, agilent, cryo, load
    global cartridge_tasknames, cold_mult, warm_mult
    
    args,kwargs = drama.parse_argument(msg.arg)
    
    initialised = False
    
    if 'INITIALISE' in kwargs:
        inifile = kwargs['INITIALISE']
    if not inifile:
        raise drama.BadStatus(drama.INVARG, 'missing argument INITIALISE, .ini file path')
    
    simulate = None
    if 'SIMULATE' in kwargs:
        simulate = int(kwargs['SIMULATE'])
    
    config = IncludeParser(inifile)
    nconfig = config['namakanui']
    cartridge_tasknames[3] = nconfig['b3_taskname']
    cartridge_tasknames[6] = nconfig['b6_taskname']
    cartridge_tasknames[7] = nconfig['b7_taskname']
    
    # start the cartridge tasks in the background.
    # will exit immediately if already running, which is fine.
    log.info('starting cartridge tasks')
    subprocess.popen([binpath + 'cartridge_task.py', cartridge_tasknames[3])
    subprocess.popen([binpath + 'cartridge_task.py', cartridge_tasknames[6])
    subprocess.popen([binpath + 'cartridge_task.py', cartridge_tasknames[7])
    
    # kill the UPDATE action while we fire things up
    try:
        drama.kick(taskname, "UPDATE").wait()
    except drama.DramaException:
        pass
    
    # kludge: sleep a short time to let cartridge tasks run up
    log.info('sleeping 3s for cartridge task startup')
    drama.wait(3)
    
    # TODO: do the ini file names really need to be configurable?
    #       probably a bit overkill.
    cart_kwargs = {}
    if simulate is not None:
        cart_kwargs["SIMULATE"] = simulate
    for band in [3,6,7]:
        task = cartridge_tasknames[band]
        ini = datapath + nconfig['b%d_ini'%(band)]
        log.info('initialising %s', task)
        msg = drama.obey(task, "INITIALISE", BAND=band, INITIALISE=ini, **cart_kwargs).wait()
        if msg.status != 0
            raise drama.BadStatus(msg.status, task + ' INITIALISE failed')
    
    # setting agilent frequency requires warm/cold multipliers for each band.
    # TODO: this assumes pubname=DYN_STATE -- could instead [include] config.
    #       also this is rather a large get() for just a couple values.
    for band in [3,6,7]:
        dyn_state = drama.get(cartridge_tasknames[band], "DYN_STATE").wait().arg
        cold_mult[band] = dyn_state['cold_mult']
        warm_mult[band] = dyn_state['warm_mult']
    
    # now reinstantiate the local stuff
    del agilent
    del cryo
    del load
    agilent = None
    cryo = None
    load = None
    gc.collect()
    agilent = namakanui.agilent.Agilent(datapath+nconfig['agilent_ini'], drama.wait, drama.set_param, simulate)
    cryo = namakanui.cryo.Cryo(datapath+nconfig['cryo_ini'], drama.wait, drama.set_param, simulate)
    load = namakanui.load.Load(datapath+nconfig['load_ini'], drama.wait, drama.set_param, simulate)
    
    # restart the update loop
    drama.blind_obey(taskname, "UPDATE")
    
    initialised = True
    # INITIALISE
    

def UPDATE(msg):
    '''
    Update local class instances every 10s.
    This is half the frequency of the nominal cryo update rate,
    but we don't expect state to change quickly.
    
    Try updating everything in one call since it is simpler than staggering.
    
    TODO: wrap this in a try/catch block?
    '''
    delay = 10
    if msg.reason == drama.REA_KICK:
        return
    if msg.reason == drama.REA_OBEY:
        if not initialised:
            raise drama.BadStatus(drama.APP_ERROR, 'task needs INITIALISE')
        # INITIALISE has just updated everything, so skip the first update.
        drama.reschedule(delay)
        return
    
    cryo.update()
    load.update()
    agilent.update()
    
    drama.reschedule(delay)
    # UPDATE


def LOAD_HOME(msg):
    '''Home the load stage.  No arguments.
       
       NOTE: This can twist up any wires running to the load stage.
             Supervise as needed.
       
       TODO: A kick will interrupt the wait/update loop,
             but we need to make sure the wheel stops.
    '''
    if not initialised:
        raise drama.BadStatus(drama.APP_ERROR, 'task needs INITIALISE')
    log.info('homing load...')
    load.home()
    log.info('load homed.')


def load_move_args(POSITION):
    return POSITION

def LOAD_MOVE(msg):
    '''Move the load.  Arguments:
            POSITION:  Named position or absolute encoder counts.
    '''
    if not initialised:
        raise drama.BadStatus(drama.APP_ERROR, 'task needs INITIALISE')
    args,kwargs = drama.parse_argument(msg.arg)
    pos = load_move_args(*args,**kwargs)
    log.info('moving load to %s...', pos)
    load.move(pos)
    log.info('load at %d, %s.', load.state['pos_counts'], load.state['pos_name'])


def cart_power_args(BAND, ENABLE):
    BAND = int(BAND)
    ENABLE = ENABLE.lower().strip()
    ENABLE = {'0':0, 'off':0, 'false':0, '1':1, 'on':1, 'true':1}[ENABLE]
    return BAND, ENABLE
    
def CART_POWER(msg):
    '''Power a cartridge on or off.  Arguments:
            BAND: One of 3,6,7
            ENABLE: Can be 1/0, on/off, true/false
    '''
    if not initialised:
        raise drama.BadStatus(drama.APP_ERROR, 'task needs INITIALISE')
    args,kwargs = drama.parse_argument(msg.arg)
    band,enable = cart_power_args(*args,**kwargs)
    if band not in [3,6,7]:
        raise drama.BadStatus(drama.INVARG, 'BAND %d not one of [3,6,7]' % (band))
    cartname = cartridge_tasknames[band]
    onoff = ['off','on'][enable]
    log.info('band %d powering %s...', band, onoff)
    msg = drama.obey(cartname, 'POWER', enable).wait()
    if msg.status != 0:
        raise drama.BadStatus(msg.status, '%s POWER %s failed' % (cartname, onoff))
    log.info('band %d powered %s.', band, ['off','on'][enable])


def cart_tune_args(BAND, LO_GHZ, VOLTAGE=None):
    BAND = int(BAND)
    LO_GHZ = float(LO_GHZ)
    if VOLTAGE is not None:
        VOLTAGE = float(VOLTAGE)
    return BAND, LO_GHZ, VOLTAGE
    
def CART_TUNE(msg):
    '''Tune a cartridge, after setting reference frequency.  Arguments:
            BAND: One of 3,6,7
            LO_GHZ: Local oscillator frequency in gigahertz
            VOLTAGE: Desired PLL control voltage, [-10,10].
                     If not given, voltage will not be adjusted
                     following the initial lock.
       
       TODO: Set IF switch.
    '''
    if not initialised:
        raise drama.BadStatus(drama.APP_ERROR, 'task needs INITIALISE')
    args,kwargs = drama.parse_argument(msg.arg)
    band,lo_ghz,voltage = cart_tune_args(*args,**kwargs)
    if band not in [3,6,7]:
        raise drama.BadStatus(drama.INVARG, 'BAND %d not one of [3,6,7]' % (band))
    if not 70<=lo_ghz<=400:  # TODO be more specific
        raise drama.BadStatus(drama.INVARG, 'LO_GHZ %g not in [70,400]' % (lo_ghz))
    if voltage and not -10<=voltage<=10:
        raise drama.BadStatus(drama.INVARG, 'VOLTAGE %g not in [-10,10]' % (voltage))
    
    fyig = lo_ghz / (cold_mult[band] * warm_mult[band])
    fsig = (fyig*warm_mult[band] + agilent.floog) / agilent.harmonic
    log.info('setting agilent to %g GHz, %g dBm')
    agilent.set_hz(fsig*1e9)
    agilent.set_dbm(agilent.dbm)
    agilent.set_output(1)
    agilent.update(publish_only=True)  # the "set_*" calls update state
    time.sleep(0.05)  # wait 50ms; for small changes PLL might hold lock
    cartname = cartridge_tasknames[band]
    vstr = ''
    band_kwargs = {"LO_GHZ":lo_ghz}
    if voltage is not None:
        vstr = ', %g V' % (voltage)
        band_kwargs["VOLTAGE"] = voltage
    log.info('band %d tuning to LO %g GHz%s...', band, lo_ghz, vstr)
    msg = drama.obey(cartname, 'TUNE', **band_kwargs).wait()
    if msg.status != 0:
        raise drama.BadStatus(msg.status, '%s TUNE failed' % (cartname))
    log.info('band %d tuned.', band)
    # CART_TUNE


try:
    drama.init(taskname, actions=[UPDATE, INITIALISE,
                                  LOAD_HOME, LOAD_MOVE,
                                  CART_POWER, CART_TUNE])
    drama.run()
finally:
    drama.stop()

