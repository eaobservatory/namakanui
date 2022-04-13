#!/local/python3/bin/python3
'''
retune_pmeter.py  20220324 RMB

Test RFSMA power meter readings against small-scale retunings,
as might occur during a typical doppler-tracking observation.

Adapted from original JCMT retune_tpd2.py script.


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
import logging
import argparse
import namakanui.instrument
import namakanui.util
from namakanui_tune import tune


taskname = 'RTPD_%d'%(os.getpid())

namakanui.util.setup_logging()

config = namakanui.util.get_config()
bands = namakanui.util.get_bands(config, simulated=False)#, has_sis_mixers=True)

parser = argparse.ArgumentParser(
    formatter_class=argparse.RawTextHelpFormatter,
    description=namakanui.util.get_description(__doc__)
    )
parser.add_argument('band', type=int, choices=bands)
parser.add_argument('lo_ghz', type=float)
parser.add_argument('lock_side', nargs='?', choices=['below','above'], default='above')
parser.add_argument('--off_ghz', nargs='?', type=float, default=0.01)
parser.add_argument('--iters', nargs='?', type=int, default=200)
parser.add_argument('--level_only', action='store_true')
args = parser.parse_args()

args.off_ghz = abs(args.off_ghz)

band = args.band
lo_ghz = args.lo_ghz
lo_range = namakanui.util.get_band_lo_range(band, config)
lo_range = namakanui.util.interval(lo_range.min + args.off_ghz, lo_range.max - args.off_ghz)
if not lo_ghz not in lo_range:
    logging.error('lo_ghz %g outside %s range for band %d', lo_ghz, lo_range, band)
    sys.exit(1)

instrument = namakanui.instrument.Instrument(config)
instrument.set_safe()
instrument.set_band(args.band)
instrument.load.move('b%d_hot'%(args.band))
cart = instrument.carts[band]
cart.power(1)
cart.set_lock_side(args.lock_side)

if not tune(instrument, band, lo_ghz):
    logging.error('failed to tune to %.3f ghz', lo_ghz)
    sys.exit(1)

pmeters = namakanui.util.init_rfsma_pmeters_49()

# write out a header for our output file
sys.stdout.write(time.strftime('# %Y%m%d %H:%M:%S HST\n', time.localtime()))
sys.stdout.write('# %s\n'%(sys.argv))
sys.stdout.write('#\n')
sys.stdout.write('#lo_ghz lock_only ')

# debug, this should exist
#sys.stderr.write('sis_v_s: %s'%(repr(cart.state['sis_v_s'])))
#sys.stderr.flush()

state_keys = sorted(cart.state)
for key in sorted(cart.state):
    if isinstance(cart.state[key], (list,tuple)):
        state_keys.remove(key)
        state_keys += ['%s_%d'%(key,i) for i in range(len(cart.state[key]))]
    elif not str(cart.state[key]).strip():
        state_keys.remove(key)
    elif len(str(cart.state[key]).split()) > 1:
        state_keys.remove(key)
state_keys.sort()
state_keys.remove('lo_ghz')
sys.stdout.write(' '.join(state_keys))

pheader = []
pheader += ['B%d_U0'%(band)]
pheader += ['B%d_U1'%(band)]
pheader += ['B%d_L0'%(band)]
pheader += ['B%d_L1'%(band)]

sys.stdout.write(' ' + ' '.join('hot_dbm_'+p for p in pheader))
sys.stdout.write('\n')
sys.stdout.flush()



def main_loop():
    random.seed()
    lock_only = 1
    sys.stderr.write('starting %d iters\n'%(args.iters))
    sys.stderr.flush()
    for i in range(args.iters):
        sys.stderr.write('%d '%(i))
        sys.stderr.flush()
        if i == args.iters//2:
            lock_only = 0
            sys.stderr.write('\nhalfway\n')
            sys.stderr.flush()
        lo_ghz = random.uniform(args.lo_ghz - args.off_ghz, args.lo_ghz + args.off_ghz)
        if not tune(instrument, band, lo_ghz, lock_only=lock_only):
            logging.error('failed to tune to %.6f ghz', lo_ghz)
            return
        for m in pmeters:
            m.read_init()
        cart.update_all()
        if cart.state['pll_unlock']:
            logging.error('lost lock at %.6f GHz', lo_ghz)
            return
        powers = [p for m in pmeters for p in m.read_fetch()]
        sys.stdout.write('%.6f %d'%(lo_ghz, lock_only))
        for key in state_keys:
            if key not in cart.state:
                key,sep,index = key.rpartition('_')
                index = int(index)
                sys.stdout.write(' %s'%(cart.state[key][index]))
            else:
                sys.stdout.write(' %s'%(cart.state[key]))
        for p in powers:
            sys.stdout.write(' %.5f'%(p))
        sys.stdout.write('\n')
        sys.stdout.flush()


try:
    main_loop()
finally:
    sys.stdout.write(time.strftime('# %Y%m%d %H:%M:%S HST\n', time.localtime()))
    sys.stdout.flush()
    instrument.set_safe()
    logging.info('done')


