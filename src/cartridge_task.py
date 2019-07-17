#!/local/python3/bin/python3
'''
20181211 RMB

A DRAMA task to monitor and control a Namakanui warm/cold cartridge set.
'''
import jac_sw
import drama
import time
import gc
import namakanui.cart

import argparse
parser = argparse.ArgumentParser()
parser.add_argument('taskname')
#parser.add_argument('band')
#parser.add_argument('inifile')
args = parser.parse_args()
taskname = args.taskname

import drama.log
drama.log.setup(taskname)  # save to file in /jac_logs
import logging
log = logging.getLogger(taskname)

# TODO: maybe carts should always start on full sim and fire up later.
# notably, connecting to a powered cartridge will invoke bias error measurement,
# which might take several seconds due to the ramping involved.
#cart = namakanui.cart.Cart(args.band, args.inifile, drama.wait, drama.set_param)
cart = None
inifile = None
band = None

def UPDATE(msg):
    '''
    Keep overall cart.state updated with a 5s period.
    There are 3 update functions, so call update_one at 0.6Hz, every 1.67s.
    
    TODO: wrap this in a try block so it keeps going?
          what exceptions do we need to catch?
    '''
    delay = 1.67
    if msg.reason == drama.REA_KICK:
        log.debug('UPDATE kicked.')
        return
    if msg.reason == drama.REA_OBEY:
        log.debug('UPDATE started.')
        # INITIALISE has just done an update_all, so skip the first update.
        drama.reschedule(delay)
        return
    log.debug('UPDATE reschedule.')
    cart.update_one()  # calls drama.set_param to publish state
    drama.reschedule(delay)
    

def INITIALISE(msg):
    '''
    Reinitialise (reinstantiate) the cartridge.
    '''
    global cart, inifile, band
    
    log.debug('INITIALISE(%s)', msg.arg)
    
    args,kwargs = drama.parse_argument(msg.arg)
    
    if 'INITIALISE' in kwargs:
        inifile = kwargs['INITIALISE']
    if not inifile:
        raise drama.BadStatus(drama.INVARG, 'missing argument INITIALISE, .ini file path')
    
    simulate = None
    if 'SIMULATE' in kwargs:
        simulate = int(kwargs['SIMULATE'])  # bitmask
    
    if 'BAND' in kwargs:
        band = int(kwargs['BAND'])
    if not band:
        raise drama.BadStatus(drama.INVARG, 'missing argument BAND, receiver band number')
    
    # kick the update loop, if running, just to make sure it can't interfere
    # with cart's initialise().
    try:
        drama.kick(taskname, "UPDATE").wait()
    except drama.DramaException:
        pass
    
    # we recreate the cart instance to force it to reread its ini file.
    # note that Cart.__init__() calls Cart.initialise().
    log.info('initialising band %d...', band)
    del cart
    cart = None
    gc.collect()
    cart = namakanui.cart.Cart(band, inifile, drama.wait, drama.set_param, simulate)
    
    # set the SIMULATE bitmask used by the cart
    drama.set_param('SIMULATE', cart.simulate)
    
    # restart the update loop
    drama.blind_obey(taskname, "UPDATE")
    log.info('initialised.')
    # INITIALISE


def POWER(msg):
    '''
    Enable or disable power to the cartridge.
    Single argument is ENABLE, which can be 1/0, on/off, true/false.
    Enabling power will trigger the demagnetization and defluxing sequence
    plus bias voltage error measurement, which could take considerable time.
    
    TODO: Invoking SIMULATE during this procedure (or interrupting it in
    some other way) could leave the cart powered but not setup properly.
    That is, not demagnetized or defluxed.
    Can we do anything about that?  It would also be a problem if this task
    suddenly died, though, and there wouldn't be any indication.
    There will probably just need to be a procedure that an error during
    power up will require power-cycling the cartridge.
    '''
    log.debug('POWER(%s)', msg.arg)
    args,kwargs = drama.parse_argument(msg.arg)
    enable = kwargs.get('ENABLE','') or args[0]
    enable = enable.lower().strip()
    enable = {'0':0, 'off':0, 'false':0, '1':1, 'on':1, 'true':1}[enable]
    onoff = ['off','on'][enable]
    log.info('powering %s...', onoff)
    cart.power(enable)
    log.info('powered %s.', onoff)


def tune_args(LO_GHZ, VOLTAGE=None):
    LO_GHZ = float(LO_GHZ)
    if VOLTAGE is not None:
        VOLTAGE = float(VOLTAGE)
    return LO_GHZ, VOLTAGE

def TUNE(msg):
    '''
    Takes two arguments, LO_GHZ and VOLTAGE.
    If VOLTAGE is not given, PLL control voltage will not be adjusted
    following the initial lock.
    The reference signal and IF switch must already be set externally.
    '''
    log.debug('TUNE(%s)', msg.arg)
    args,kwargs = drama.parse_argument(msg.arg)
    lo_ghz,voltage = tune_args(*args,**kwargs)
    vstr = ''
    if voltage is not None:
        vstr = ', %g V' % (voltage)
    log.info('tuning to LO %g GHz%s...', lo_ghz, vstr)
    cart.tune(lo_ghz, voltage)
    log.info('tuned.')



try:
    log.info('%s starting drama.', taskname)
    drama.init(taskname, actions=[UPDATE, INITIALISE, POWER, TUNE])
    log.info('%s entering main loop.', taskname)
    drama.run()
finally:
    drama.stop()
    log.info('%s done.', taskname)



