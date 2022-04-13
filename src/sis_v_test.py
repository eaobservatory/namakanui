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

config = namakanui.util.get_config()
bands = namakanui.util.get_bands(config, simulated=False, has_sis_mixers=True)

parser = argparse.ArgumentParser(
    formatter_class=argparse.RawTextHelpFormatter,
    description=namakanui.util.get_description(__doc__)
    )
parser.add_argument('band', type=int, choices=bands)
args = parser.parse_args()

band = args.band

# no need for lock or load, and we don't care about zeroing other carts
sim_mask = SIM_LOAD | SIM_STSR | sim.other_bands(band)
instrument = namakanui.instrument.Instrument(config, simulate=sim_mask)
instrument.set_safe()
cart = instrument.carts[band]
cart.power(1)


# make sure LO pumping power is zero
cart._set_pa([0.0]*4)

# manually calculate bias error since we're not bothering to tune
cart._calc_sis_bias_error()

# band-dependent mv range, +-  TODO ask cart
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


