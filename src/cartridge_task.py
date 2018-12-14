#!/local/python3/bin/python3
'''
20181211 RMB

A DRAMA task to monitor and control a Namakanui warm/cold cartridge set.
'''
import jac_sw
import drama
import time
import namakanui.cart

import argparse
parser = argparse.ArgumentParser()
parser.add_argument('taskname')
parser.add_argument('band')
parser.add_argument('inifile')
args = parser.parse_args()

import drama.log
drama.log.setup()  # no taskname, so no /jac_logs file output

# create the Cart instance here so any failure kills the process.
# TODO: override starting simulate params?
# maybe carts should always start on full sim and fire up later.
# notably, connecting to a powered cartridge will invoke bias error measurement,
# which might take several seconds due to the ramping involved.
cart = namakanui.cart.Cart(args.band, args.inifile, drama.wait, drama.set_param)


def UPDATE(msg):
    '''
    Keep overall cart.state updated with a 5s period.
    There are 3 update functions, so call update_one at 0.6Hz, every 1.67s.
    '''
    cart.update_one()  # calls drama.set_param to publish state
    drama.reschedule(1.67)
    

def SIMULATE(msg):
    '''
    Change the set of simulated components (which re-initiliazes the cart).
    The set can be given as positional args or a single SIMULATE="..." param.
    '''
    args,kwargs = drama.parse_argument(msg.arg)
    sim = ' '.join(args + [kwargs.get('SIMULATE', '')])
    cart.simulate = sim  # assignment invokes initialise()


def POWER(msg):
    '''
    Enable or disable power to the cartridge.
    Single argument is ENABLE, which can be 0/1, on/off, true/false.
    Enabling power will trigger the demagnetization and defluxing sequence
    plus bias voltage error measurement, which could take considerable time.
    
    TODO: Invoking SIMULATE during this procedure (or interrupting it in
    some other way) could leave the cart powered but not setup properly.
    Can we do anything about that?  It would also be a problem if this task
    suddenly died, though, and there wouldn't be any indication.
    There will probably just need to be a procedure that an error during
    power up will require power-cycling the cartridge.
    '''
    args,kwargs = drama.parse_argument(msg.arg)
    enable = kwargs.get('ENABLE','') or args[0]
    enable = enable.lower().strip()
    enable = {'0':0, 'off':0, 'false':0, '1':1, 'on':1, 'true':1}[enable]
    cart.power(enable)


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
    args,kwargs = drama.parse_argument(msg.arg)
    lo_ghz,voltage = tune_args(**args,**kwargs)
    cart.tune(lo_ghz, voltage)



try:
    drama.init(args.taskname, actions=[UPDATE, SIMULATE, POWER, TUNE])
    drama.blind_obey(args.taskname, 'UPDATE')
    drama.run()
finally:
    drama.stop()



