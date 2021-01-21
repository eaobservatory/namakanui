#!/local/python3/bin/python3
'''
dbm_table.py    RMB 20190805

Build a dBm table for a receiver by tuning in a range of frequencies and
adjusting the power output from the signal generator.  Ideally we want
the IF total power reading to be in the [-1,-2]V range, though being
in the [-.7,-3]V range is still acceptable.

This script instantiates a Cart instance directly, rather than
communicating with a running engineering task via DRAMA.  The two
probably shouldn't run at the same time.

The <dbm> parameter gives the starting dBm setting at each frequency;
I've used -12 dBm for the ASIAA IF switch and -16 dBm for Bill's IF switch.
You can also give "ini-X" for this parameter to start with the value
interpolated from the table in the agilent.ini file, minus X dBm.

It is no longer necessary to convert the output file to an ini table,
but if you prefer you can do that as follows:

grep -v '^#' <file> | sort -n | awk '{ printf "dbm%02d=%s, %6s\n", NR, $1, $2 }'

Usage:
dbm_table.py <band> <LO_GHz_start> <LO_GHz_end> <LO_GHz_step> <lock_polarity> <dbm>


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
import argparse
import namakanui.cart
import namakanui.agilent
import namakanui.photonics
import namakanui.ifswitch
import namakanui.util
import namakanui.ini
import logging

logging.root.setLevel(logging.DEBUG)
logging.root.addHandler(logging.StreamHandler())

binpath, datapath = namakanui.util.get_paths()

parser = argparse.ArgumentParser()
parser.add_argument('band', type=int, choices=[3,6,7])
parser.add_argument('LO_GHz_start', type=float)
parser.add_argument('LO_GHz_end', type=float)
parser.add_argument('LO_GHz_step', type=float)
parser.add_argument('lock_side', choices=['below','above'])
parser.add_argument('dbm')
args = parser.parse_args()
#print(args.band, args.LO_GHz_start, args.LO_GHz_end, args.LO_GHz_step)

if args.LO_GHz_step < 0.01:
    logging.error('invalid step, must be >= 0.01 GHz')
    sys.exit(1)
if args.LO_GHz_start > args.LO_GHz_end:
    logging.error('start/end out of order')
    sys.exit(1)

dbm_use_ini = False
try:
    args.dbm = float(args.dbm)
except:
    if not args.dbm.startswith('ini'):
        logging.error('invalid dbm, must be a number or "ini"')
        sys.exit(1)
    dbm_use_ini = True
    args.dbm = float(args.dbm[3:] or '0')


# if tune.sh, relax tuning constraints
pll_range = [-1.4,-1.6]
dbm_max = agilent.max_dbm
if args.LO_GHZ_start == args.LO_GHZ_end:
    pll_range = [-.8, -2.5]
    dbm_max = None


#sys.exit(0)

# perform basic setup and get handles
cart, agilent, photonics = namakanui.util.setup_script(args.band, args.lock_side)

floog = agilent.floog * {'below':1.0, 'above':-1.0}[args.lock_side]
lo_min = cart.yig_lo * cart.cold_mult * cart.warm_mult
lo_max = cart.yig_hi * cart.cold_mult * cart.warm_mult


def adjust_dbm(lo_ghz):
    # sanity check, avoid setting agilent for impossible freqs
    if lo_ghz < lo_min or lo_ghz > lo_max:
        logging.error('skipping lo_ghz %g, outside range [%.3f, %.3f] for band %d', lo_ghz, lo_min, lo_max, args.band)
        return
    if namakanui.util.tune(cart, agilent, photonics, lo_ghz, pll_range=pll_range,
                           dbm_ini=dbm_use_ini, dbm_start=args.dbm, dbm_max=dbm_max,
                           att_ini=True, att_start=0, att_min=0):
        sys.stdout.write('%.3f %6.2f %.3f %.3f %.3f\n' % (lo_ghz, agilent.state['dbm'], cart.state['pll_if_power'], cart.state['pa_drain_s'][0], cart.state['pa_drain_s'][1]))
        sys.stdout.flush()


def try_adjust_dbm(lo_ghz):
    try:
        adjust_dbm(lo_ghz)
    except Exception as e:
        agilent.set_dbm(agilent.safe_dbm)
        photonics.set_attenuation(photonics.max_att) if photonics else None
        logging.error('unhandled exception: %s', e)
        raise


sys.stdout.write('#lo_ghz dbm pll_if_power pa_0 pa_1\n')  # topcat ascii
lo_ghz = args.LO_GHz_start
while lo_ghz < args.LO_GHz_end:
    try_adjust_dbm(lo_ghz)
    lo_ghz += args.LO_GHz_step
lo_ghz = args.LO_GHz_end
try_adjust_dbm(lo_ghz)

# since this script is also used to tune the receiver, retune once we've
# found the optimal IF power to servo the PA.
cart.update_all()
if cart.state['lo_ghz'] == lo_ghz and not cart.state['pll_unlock']:
    logging.info('retuning at %g to adjust PA...', lo_ghz)
    try:
        cart.tune(lo_ghz, 0.0)
        time.sleep(0.1)
        cart.update_all()
        if cart.state['pll_unlock']:
            agilent.set_dbm(agilent.safe_dbm)
            photonics.set_attenuation(photonics.max_att) if photonics else None
            logging.error('lost lock at %g', lo_ghz)
        logging.info('band %d tuned to %g GHz, IF power: %g', args.band, lo_ghz, cart.state['pll_if_power'])
    except Exception as e:
        agilent.set_dbm(agilent.safe_dbm)
        photonics.set_attenuation(photonics.max_att) if photonics else None
        logging.error('final retune exception: %s', e)

# show the last dbm setting
agilent.update()
logging.info('final dbm: %.2f', agilent.state['dbm'])
logging.info('done.')





