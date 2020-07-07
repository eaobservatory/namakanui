#!/local/python3/bin/python3
'''
20200707 RMB

During jumping_tpd2.py tests there was an instance where sis_v was
apparently set to the wrong value.  Unfortunately I overwrote the data,
and I've been unable to reproduce the error.

This script sets mixer bias voltage to random values and checks feedback
from the FEMC.

'''

import jac_sw
import drama
import sys
import os
import time
import random
import argparse
import namakanui.cart
import namakanui.agilent
import namakanui.load
import namakanui.femc
import namakanui.util
import logging

taskname = 'SVT_%d'%(os.getpid())

logging.root.setLevel(logging.INFO)
logging.root.addHandler(logging.StreamHandler())

binpath, datapath = namakanui.util.get_paths()

# use explicit arguments to avoid confusion
parser = argparse.ArgumentParser(description='''
''',
  formatter_class=argparse.RawTextHelpFormatter)
parser.add_argument('band', type=int, choices=[6,7])
args = parser.parse_args()

band = args.band

# no need for lock; set agilent output to a safe level
agilent = namakanui.agilent.Agilent(datapath+'agilent.ini', time.sleep, namakanui.nop, simulate=0)
agilent.set_dbm(agilent.safe_dbm)

# init cartridge
cart = namakanui.cart.Cart(band, datapath+'band%d.ini'%(band), time.sleep, namakanui.nop, simulate=0)
cart.power(1)

# make sure LO pumping power is zero
cart._set_pa([0.0]*4)

# band-dependent mv range, +-
mv_range = 10.0
if band == 7:
    mv_range = 2.5

prev_mv = 0.0  # from cart init
random.seed()

try:
    count = 0
    errs = 0
    while True:
        count += 1
        sys.stderr.write('.')
        sys.stderr.flush()
        set_mv = random.uniform(-mv_range, mv_range)
        cart._ramp_sis_bias_voltages([set_mv]*4)
        for i in range(4):
            get_mv = cart.femc.get_sis_voltage(cart.ca, i//2, i%2)
            cmd_mv = cart.femc.get_sis_voltage_cmd(cart.ca, i//2, i%2)
            cmd_mv += cart.bias_error[i]
            # TODO tweak; unsure how much error to expect normally
            get_err = get_mv - set_mv
            set_err = cmd_mv - set_mv
            if abs(get_err) > mv_range*.001 or abs(set_err) > mv_range*.001:
                errs += 1
                sys.stderr.write('\n')
                sys.stderr.flush()
                print('err %d/%d (%g%%): mixer %d, set/get/cmd mv: %.3f, %.3f, %.3f'%(errs, count, 100.0*errs/count, i, set_mv, get_mv, cmd_mv))
finally:
    sys.stderr.write('\ndone, ramping bias voltages back to 0.')
    cart._ramp_sis_bias_voltages([0.0]*4)


