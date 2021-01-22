#!/local/python3/bin/python3
'''
tune.py    RMB 20210119

Tune the receiver.


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
parser.add_argument('lo_ghz', type=float)
parser.add_argument('lock_side', choices=['below','above'], nargs='?', default='above')
parser.add_argument('dbm', nargs='?', default='ini-0')
parser.add_argument('att', nargs='?', default='ini+0')
args = parser.parse_args()


dbm_use_ini = False
try:
    args.dbm = float(args.dbm)
except:
    if not args.dbm.startswith('ini'):
        logging.error('invalid dbm, must be a number or "ini"')
        sys.exit(1)
    dbm_use_ini = True
    args.dbm = float(args.dbm[3:] or '0')

att_use_ini = False
try:
    args.att = float(args.att)
except:
    if not args.att.startswith('ini'):
        logging.error('invalid att, must be a number or "ini"')
        sys.exit(1)
    att_use_ini = True
    args.att = float(args.att[3:] or '0')

# use the defaults for now
pll_range = [-.8, -2.5]
dbm_max = None
att_min = None

# perform basic setup and get handles
cart, agilent, photonics = namakanui.util.setup_script(args.band, args.lock_side)

# sanity check, avoid setting agilent for impossible freqs
lo_ghz = args.lo_ghz
lo_min = cart.yig_lo * cart.cold_mult * cart.warm_mult
lo_max = cart.yig_hi * cart.cold_mult * cart.warm_mult
if lo_ghz < lo_min or lo_ghz > lo_max:
    logging.error('lo_ghz %g outside range [%.3f, %.3f] for band %d', lo_ghz, lo_min, lo_max, args.band)
    sys.exit(1)


try:
    if namakanui.util.tune(cart, agilent, photonics, lo_ghz, pll_range=pll_range,
                            dbm_ini=dbm_use_ini, dbm_start=args.dbm, dbm_max=dbm_max,
                            att_ini=att_use_ini, att_start=args.att, att_min=att_min):
        logging.info('tuned band %d to %g ghz', cart.band, lo_ghz)
    else:
        raise RuntimeError('tune failed')
except:
    logging.error('tune failed, setting power to safe levels.')
    agilent.set_dbm(agilent.safe_dbm)
    photonics.set_attenuation(photonics.max_att) if photonics else None
    raise
finally:
    logging.info('done.')
    

