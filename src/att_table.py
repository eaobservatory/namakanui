#!/local/python3/bin/python3
'''
att_table.py    RMB 20191121

Build an attenuation table for a receiver by tuning a range of frequencies
and adjusting the attenuator to achieve sufficient PLL IF power
in the [-.7, -3]V range, ideally around -1.5V.

This script instantiates a Cart instance directly, rather than
communicating with a running engineering task via DRAMA.  The two
probably shouldn't run at the same time.

The <att> parameter gives the starting attenuator setting at each frequency.
You can also give "ini+X" for this parameter to start with the value
interpolated from the table in the photonics.ini file, plus X counts.

Usage:
att_table.py <band> <LO_GHz_start> <LO_GHz_end> <LO_GHz_step> <lock_polarity> <att>


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
import logging
import argparse
import namakanui.instrument
import namakanui.util
import namakanui.sim as sim
from namakanui_tune import tune


namakanui.util.setup_logging()
logging.root.setLevel(logging.DEBUG)

parser = argparse.ArgumentParser()
parser.add_argument('band', type=int, choices=[3,6,7])
parser.add_argument('LO_GHz_start', type=float)
parser.add_argument('LO_GHz_end', type=float)
parser.add_argument('LO_GHz_step', type=float)
parser.add_argument('lock_side', choices=['below','above'])
parser.add_argument('att')
parser.add_argument('--lock_only', action='store_true', help='skip mixer adjustment')
args = parser.parse_args()
#print(args.band, args.LO_GHz_start, args.LO_GHz_end, args.LO_GHz_step)

if args.LO_GHz_step < 0.01:
    logging.error('invalid step, must be >= 0.01 GHz')
    sys.exit(1)
if args.LO_GHz_start > args.LO_GHz_end:
    logging.error('start/end out of order')
    sys.exit(1)

use_ini = False
try:
    args.att = int(args.att)
except:
    if not args.att.startswith('ini'):
        logging.error('invalid att, must be a number or "ini"')
        sys.exit(1)
    use_ini = True
    args.att = int(args.att[3:] or '0')

#sys.exit(0)

# we don't need the load for this script
instrument = namakanui.instrument.Instrument(simulate=sim.SIM_LOAD)

# be a little less verbose
instrument.photonics.log.setLevel(logging.INFO)
instrument.reference.log.setLevel(logging.INFO)

instrument.set_safe()  # paranoia

cart = instrument.carts[args.band]
cart.power(1)
cart.set_lock_side(args.lock_side)
if args.lock_only:
    cart.zero()  # zero the mixers; we only care about PLL


photonics = instrument.photonics  # shorten name for adjust_att()

def adjust_att(lo_ghz):
    # sanity check, skip impossible freqs
    lo_min = cart.yig_lo * cart.cold_mult * cart.warm_mult
    lo_max = cart.yig_hi * cart.cold_mult * cart.warm_mult
    if lo_ghz < lo_min or lo_ghz > lo_max:
        logging.error('skipping lo_ghz %g, outside range [%.3f, %.3f] for band %d',
                      lo_ghz, lo_min, lo_max, args.band)
        return
    if tune(instrument, args.band, lo_ghz, pll_if=[-1.4,-1.6],
            att_ini=use_ini, att_start=args.att, att_min=-photonics.max_att,
            dbm_ini=True, dbm_start=0, dbm_max=0, lock_only=args.lock_only):
        sys.stdout.write('%.3f %d %.3f %.3f %.3f\n' % (lo_ghz, photonics.state['attenuation'], cart.state['pll_if_power'], cart.state['pa_drain_s'][0], cart.state['pa_drain_s'][1]))
        sys.stdout.flush()


def try_adjust_att(lo_ghz):
    try:
        adjust_att(lo_ghz)
    except Exception as e:
        instrument.set_safe()
        logging.error('unhandled exception: %s', e)
        raise


sys.stdout.write('#lo_ghz att pll_if_power pa_0 pa_1\n')  # topcat ascii
lo_ghz = args.LO_GHz_start
while lo_ghz < args.LO_GHz_end - 1e-9:
    try_adjust_att(lo_ghz)
    lo_ghz += args.LO_GHz_step
lo_ghz = args.LO_GHz_end
try_adjust_att(lo_ghz)

logging.info('done, setting safe power levels.')
instrument.set_safe()


