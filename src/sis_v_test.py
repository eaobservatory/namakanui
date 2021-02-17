#!/local/python3/bin/python3
'''
sis_v_test.py   20200707 RMB

During jumping_tpd2.py tests there was an instance where sis_v was
apparently set to the wrong value.  This script sets mixer bias voltage
to random values and checks feedback from the FEMC.


Copyright (C) 2020 East Asian Observatory

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
'''

import jac_sw
import drama
import sys
import os
import time
import random
import argparse
import namakanui.instrument
import namakanui.util
import namakanui.sim as sim
import logging

namakanui.util.setup_logging()

# use explicit arguments to avoid confusion
parser = argparse.ArgumentParser(description='''
''',
  formatter_class=argparse.RawTextHelpFormatter)
parser.add_argument('band', type=int, choices=[6,7])
args = parser.parse_args()

band = args.band

# no need for lock or load, and we don't care about zeroing other carts
# TODO: add a "band" argument to Instrument.__init__ to save trouble here
cart_sim = {3:sim.SIM_B3_FEMC, 6:sim.SIM_B6_FEMC, 7:sim.SIM_B7_FEMC}
del cart_sim[band]
cart_sim_bits = 0
for s in cart_sim.values():
    cart_sim_bits |= s
instrument = namakanui.instrument.Instrument(simulate=SIM_LOAD|SIM_IFSW|cart_sim_bits)
instrument.set_safe()
cart = instrument.carts[band]
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
        try:
            cart._ramp_sis_bias_voltages([set_mv]*4, retry=0)  # don't defeat the test
        except RuntimeError:
            pass
        # try to provoke errors
        #for i in range(10):
        #    cart.update_all()
        for i in range(4):
            avg = 0.0
            n = 10
            for j in range(n):
                avg += cart.femc.get_sis_voltage(cart.ca, i//2, i%2)
            get_mv = avg/n
            cmd_mv = cart.femc.get_sis_voltage_cmd(cart.ca, i//2, i%2)
            cmd_mv += cart.bias_error[i]
            # TODO tweak; unsure how much error to expect normally
            get_err = get_mv - set_mv
            set_err = cmd_mv - set_mv
            #if abs(get_err) > mv_range*.005 or abs(set_err) > mv_range*.005:
            if abs(set_err) > mv_range*.005:  # otherwise lots of get_err triggers for b7
                errs += 1
                sys.stderr.write('\n')
                sys.stderr.flush()
                sys.stdout.write('err %d/%d (%g%%): mixer %d, set/get/cmd mv: %.3f, %.3f, %.3f, err get/cmd: %.3f, %.3f, prev %.3f\n'%(errs, count, 100.0*errs/count, i, set_mv, get_mv, cmd_mv, get_err, set_err, prev_mv))
                sys.stdout.flush()
        prev_mv = set_mv
finally:
    sys.stderr.write('\nfinally, ramping bias voltages back to 0.\n')
    cart._ramp_sis_bias_voltages([0.0]*4)
    sys.stderr.write('done.\n')
    sys.stderr.flush()


