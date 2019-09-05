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

TODO: Add more control actions.
'''

import jac_sw
import drama
import sys
import os
import gc
import time
import subprocess
from namakanui.ini import IncludeParser
import namakanui.cryo
import namakanui.load
import namakanui.agilent
import namakanui.ifswitch

import argparse
parser = argparse.ArgumentParser()
parser.add_argument('taskname')
#parser.add_argument('inifile')
args = parser.parse_args()
taskname = args.taskname

import drama.log
drama.log.setup(taskname)  # save to file in /jac_logs
import logging
log = logging.getLogger(args.taskname)
#logging.getLogger('drama').setLevel(logging.DEBUG)

# always use sibling cartridge_task.py (vs one in $PATH)
binpath = os.path.dirname(os.path.realpath(sys.argv[0])) + '/'
# HACK, should crawl up
if 'install' in binpath:
    datapath = os.path.realpath(binpath + '../../data') + '/'
else:
    datapath = os.path.realpath(binpath + '../data') + '/'

initialised = False
inifile = None

agilent = None
cryo = None
load = None
ifswitch = None

# indexed by band number (int)
cartridge_tasknames = {}  
cold_mult = {}
warm_mult = {}



def INITIALISE(msg):
    '''
    Start the cartridge tasks and initialise them,
    then initialise the local control classes.  Arguments:
        INITIALISE: The ini file path
        SIMULATE: Bitmask. If given, overrides config file settings.
    '''
    global initialised, inifile, agilent, cryo, load, ifswitch
    global cartridge_tasknames, cold_mult, warm_mult
    
    log.debug('INITIALISE(%s)', msg.arg)
    
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
    # export these so the frontend task doesn't have to guess
    drama.set_param('TASKNAMES', {'B%d'%(k):v for k,v in cartridge_tasknames.items()})
    
    # start the cartridge tasks in the background.
    # will exit immediately if already running, which is fine.
    log.info('starting cartridge tasks')
    subprocess.Popen([binpath + 'cartridge_task.py', cartridge_tasknames[3]])
    subprocess.Popen([binpath + 'cartridge_task.py', cartridge_tasknames[6]])
    subprocess.Popen([binpath + 'cartridge_task.py', cartridge_tasknames[7]])
    
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
        if msg.status != 0:
            raise drama.BadStatus(msg.status, task + ' INITIALISE failed')
    
    # setting agilent frequency requires warm/cold multipliers for each band.
    # TODO: this assumes pubname=DYN_STATE -- could instead [include] config.
    #       also this is rather a large get() for just a couple values.
    for band in [3,6,7]:
        dyn_state = drama.get(cartridge_tasknames[band], "DYN_STATE").wait().arg["DYN_STATE"]
        cold_mult[band] = dyn_state['cold_mult']
        warm_mult[band] = dyn_state['warm_mult']
    
    # now reinstantiate the local stuff
    del agilent
    del cryo
    del load
    del ifswitch
    agilent = None
    cryo = None
    load = None
    ifswitch = None
    gc.collect()
    agilent = namakanui.agilent.Agilent(datapath+nconfig['agilent_ini'], drama.wait, drama.set_param, simulate)
    cryo = namakanui.cryo.Cryo(datapath+nconfig['cryo_ini'], drama.wait, drama.set_param, simulate)
    load = namakanui.load.Load(datapath+nconfig['load_ini'], drama.wait, drama.set_param, simulate)
    ifswitch = namakanui.ifswitch.IFSwitch(datapath+nconfig['ifswitch_ini'], drama.wait, drama.set_param, simulate)
    
    # publish the load.positions table for the GUI
    drama.set_param('LOAD_TABLE', load.positions)
    
    # rebuild the simulate bitmask from what was actually set
    simulate = agilent.simulate | cryo.simulate | load.simulate | ifswitch.simulate
    for band in [3,6,7]:
        task = cartridge_tasknames[band]
        simulate |= drama.get(task, 'SIMULATE').wait(5).arg['SIMULATE']
    drama.set_param('SIMULATE', simulate)
    
    # restart the update loop
    drama.blind_obey(taskname, "UPDATE")
    
    # TODO: power up the cartridges? tune? leave it for the FE wrapper?
    
    initialised = True
    log.info('initialised.')
    # INITIALISE
    

def UPDATE(msg):
    '''
    Update local class instances every 10s.
    This is half the frequency of the nominal cryo update rate,
    but we don't expect state to change quickly.
    
    Try updating everything in one call since it is simpler than staggering.
    
    TODO: wrap this in a try/catch block?
    
    TODO: small delay between updates to let DRAMA message loop run?
          or stagger individual updates?
    '''
    delay = 10
    if msg.reason == drama.REA_KICK:
        log.debug('UPDATE kicked.')
        return
    if msg.reason == drama.REA_OBEY:
        log.debug('UPDATE started.')
        if not initialised:
            raise drama.BadStatus(drama.APP_ERROR, 'task needs INITIALISE')
        # INITIALISE has just updated everything, so skip the first update.
        drama.reschedule(delay)
        return
    log.debug('UPDATE reschedule.')
    cryo.update()
    load.update()
    agilent.update()
    ifswitch.update()
    drama.reschedule(delay)
    # UPDATE


# TODO: my naming scheme isn't very consistent

def set_sg_dbm_args(DBM):
    return float(DBM)

def SET_SG_DBM(msg):
    '''Set Agilent output power in dBm.'''
    log.debug('SET_SG_DBM(%s)', msg.arg)
    if not initialised:
        raise drama.BadStatus(drama.APP_ERROR, 'task needs INITIALISE')
    args,kwargs = drama.parse_argument(msg.arg)
    dbm = set_sg_dbm_args(*args,**kwargs)
    if dbm < -130.0 or dbm > 0.0:
        raise drama.BadStatus(drama.INVARG, 'DBM %g outside [-130, 0] range' % (dbm))
    log.info('setting agilent dbm to %g', dbm)
    agilent.set_dbm(dbm)
    agilent.update(publish_only=True)

def set_sg_hz_args(HZ):
    return float(HZ)

def SET_SG_HZ(msg):
    '''Set Agilent output frequency in Hz.'''
    log.debug('SET_SG_HZ(%s)', msg.arg)
    if not initialised:
        raise drama.BadStatus(drama.APP_ERROR, 'task needs INITIALISE')
    args,kwargs = drama.parse_argument(msg.arg)
    hz = set_sg_hz_args(*args,**kwargs)
    if hz < 9e3 or hz > 32e9:
        raise drama.BadStatus(drama.INVARG, 'HZ %g outside [9 KHz, 32 GHz] range' % (hz))
    log.info('setting agilent hz to %g', hz)
    agilent.set_hz(hz)
    agilent.update(publish_only=True)

def set_sg_out_args(OUT):
    return int(bool(OUT))

def SET_SG_OUT(msg):
    '''Set Agilent output on (1) or off (0).'''
    log.debug('SET_SG_OUT(%s)', msg.arg)
    if not initialised:
        raise drama.BadStatus(drama.APP_ERROR, 'task needs INITIALISE')
    args,kwargs = drama.parse_argument(msg.arg)
    out = set_sg_out_args(*args,**kwargs)
    log.info('setting agilent output to %d', out)
    agilent.set_output(out)
    agilent.update(publish_only=True)


def set_band_args(BAND):
    return int(BAND)

def SET_BAND(msg):
    '''Set IFSwitch band to BAND.  If this would change the selection,
       first sets Agilent to -30 dBm to avoid high power to mixer.'''
    log.debug('SET_BAND(%s)', msg.arg)
    if not initialised:
        raise drama.BadStatus(drama.APP_ERROR, 'task needs INITIALISE')
    args,kwargs = drama.parse_argument(msg.arg)
    band = set_band_args(*args,**kwargs)
    if band not in [3,6,7]:
        raise drama.BadStatus(drama.INVARG, 'BAND %d not one of [3,6,7]' % (band))
    if ifswitch.get_band() != band:
        log.info('setting IF switch to band %d', band)
        agilent.set_dbm(-30.0)  # reduce reference signal power first
        ifswitch.set_band(band)
        agilent.update(publish_only=True)
    else:
        log.info('IF switch already at band %d', band)


def LOAD_HOME(msg):
    '''Home the load stage.  No arguments.
       
       NOTE: This can twist up any wires running to the load stage,
             e.g. for a tone source. Supervise as needed.
    '''
    log.debug('LOAD_HOME')
    if not initialised:
        raise drama.BadStatus(drama.APP_ERROR, 'task needs INITIALISE')
    if msg.reason == drama.REA_OBEY:
        log.info('homing load...')
        load.home()
        log.info('load homed.')
    else:
        log.error('LOAD_HOME stopping load due to unexpected msg %s', msg)
        load.stop()
    # LOAD_HOME


def load_move_args(POSITION):
    return POSITION

def LOAD_MOVE(msg):
    '''Move the load.  Arguments:
            POSITION:  Named position or absolute encoder counts.
    '''
    log.debug('LOAD_MOVE(%s)', msg.arg)
    if not initialised:
        raise drama.BadStatus(drama.APP_ERROR, 'task needs INITIALISE')
    if msg.reason == drama.REA_OBEY:
        args,kwargs = drama.parse_argument(msg.arg)
        pos = load_move_args(*args,**kwargs)
        log.info('moving load to %s...', pos)
        load.move(pos)
        log.info('load at %d, %s.', load.state['pos_counts'], load.state['pos_name'])
    else:
        log.error('LOAD_MOVE stopping load due to unexpected msg %s', msg)
        load.stop()
    # LOAD MOVE


def cart_power_args(BAND, ENABLE):
    BAND = int(BAND)
    if hasattr(ENABLE, 'lower'):
        ENABLE = ENABLE.lower().strip()
        ENABLE = {'0':0, 'off':0, 'false':0, '1':1, 'on':1, 'true':1}[ENABLE]
    else:
        ENABLE = int(bool(ENABLE))
    return BAND, ENABLE
    
def CART_POWER(msg):
    '''Power a cartridge on or off.  Arguments:
            BAND: One of 3,6,7
            ENABLE: Can be 1/0, on/off, true/false
    '''
    log.debug('CART_POWER(%s)', msg.arg)
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
       
       TODO: lock polarity (below or above reference) could be a parameter.
             for now we just read back from the cartridge task.
    '''
    log.debug('CART_TUNE(%s)', msg.arg)
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
    
    if ifswitch.get_band() != band:
        log.info('setting IF switch to band %d', band)
        agilent.set_dbm(-30.0)  # reduce reference signal power first
        ifswitch.set_band(band)
    
    cartname = cartridge_tasknames[band]
    
    # TODO don't assume pubname is DYN_STATE
    dyn_state = drama.get(cartname, "DYN_STATE").wait().arg["DYN_STATE"]
    lock_polarity = dyn_state['pll_sb_lock']  # 0=below_ref, 1=above_ref
    lock_polarity = -2.0 * lock_polarity + 1.0
    
    fyig = lo_ghz / (cold_mult[band] * warm_mult[band])
    fsig = (fyig*warm_mult[band] + agilent.floog*lock_polarity) / agilent.harmonic
    dbm = agilent.interp_dbm(band, lo_ghz)
    log.info('setting agilent to %g GHz, %g dBm', fsig, dbm)
    # these "set" calls modify agilent.state, but do not publish
    agilent.set_hz(fsig*1e9)
    agilent.set_dbm(dbm)
    agilent.set_output(1)
    agilent.update(publish_only=True)
    time.sleep(0.05)  # wait 50ms; for small changes PLL might hold lock
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
    log.info('%s starting drama.', taskname)
    drama.init(taskname,
               tidefile = datapath+'namakanui.tide',
               buffers = [64000, 8000, 8000, 2000],
               actions=[UPDATE, INITIALISE,
                        SET_SG_DBM, SET_SG_HZ, SET_SG_OUT,
                        SET_BAND,
                        LOAD_HOME, LOAD_MOVE,
                        CART_POWER, CART_TUNE])
    log.info('%s entering main loop.', taskname)
    drama.run()
finally:
    drama.stop()
    log.info('%s done.', taskname)

