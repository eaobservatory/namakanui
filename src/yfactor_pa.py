#!/local/python3/bin/python3
'''
yfactor_pa.py   20190918 RMB

Script to check Y-factor (hot power / cold power) across a PA sweep.
The receiver is tuned to its nominal values, then the PA is varied
from 0 to 2.5.  Since PA is shared between mixers in each polarization
stage, the data is organized by polarization instead of by mixer.

The motivation here is that it's hard to be confident in the relative
y-factors for each PA level when taking IV curves, since the weather
might change significantly between different PAs.



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
from namakanui_tune import tune


taskname = 'YFPA_%d'%(os.getpid())

namakanui.util.setup_logging()

config = namakanui.util.get_config()
bands = namakanui.util.get_bands(config, simulated=False, has_sis_mixers=True)

parser = argparse.ArgumentParser(
    formatter_class=argparse.RawTextHelpFormatter,
    description=namakanui.util.get_description(__doc__)
    )
parser.add_argument('band', type=int, choices=bands)
parser.add_argument('lo_ghz', type=float)
parser.add_argument('lock_side', nargs='?', choices=['below','above'], default='above')
parser.add_argument('--level_only', action='store_true')
parser.add_argument('--pa', nargs='?', default='0.0:2.5:0.01', help='PA range')
args = parser.parse_args()

band = args.band
lo_ghz = args.lo_ghz
lo_range = {6:[219,266], 7:[281,367]}[band]  # TODO get from config
if not lo_range[0] <= lo_ghz <= lo_range[1]:
    logging.error('lo_ghz %g outside %s range for band %d\n'%(lo_ghz, lo_range, band))
    sys.exit(1)

pas = namakanui.util.parse_range(args.pa, maxlen=300)

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

# save the nominal sis bias voltages
nom_v = cart.state['sis_v']

load = instrument.load  # shorten name

pmeters = namakanui.util.init_rfsma_pmeters_49()

# write out a header for our output file
sys.stdout.write(time.strftime('# %Y%m%d %H:%M:%S HST\n', time.localtime()))
sys.stdout.write('# %s\n'%(sys.argv))
sys.stdout.write('# nom_v: %s\n'%(nom_v))
sys.stdout.write('#\n')
sys.stdout.write('#pa ')
mixers = ['01', '02', '11', '12']
powers = []
#powers += ['B%d_U0'%(band)]
#powers += ['B%d_U1'%(band)]
#powers += ['B%d_L0'%(band)]
#powers += ['B%d_L1'%(band)]
# note these are reordered by polarization
powers += ['B%d_U0'%(band)]
powers += ['B%d_L0'%(band)]
powers += ['B%d_U1'%(band)]
powers += ['B%d_L1'%(band)]
sys.stdout.write(' ' + ' '.join('ua_avg_'+m for m in mixers))
sys.stdout.write(' ' + ' '.join('ua_dev_'+m for m in mixers))
sys.stdout.write(' ' + ' '.join('hot_mw_'+p for p in powers))
sys.stdout.write(' ' + ' '.join('sky_mw_'+p for p in powers))
sys.stdout.write(' ' + ' '.join('yf_'+p for p in powers))
sys.stdout.write('\n')
sys.stdout.flush()

# output column starting indices
pa_index = 0
ua_avg_index = 1
ua_dev_index = 5
hot_p_index = 9
sky_p_index = hot_p_index + len(powers)
yf_index = sky_p_index + len(powers)

# number of mixer current readings to take per PA (per load)
# TODO might be able to increase this without impacting runtime due to ITIME,
# but it depends on the actual value of ppcomm_time.
ua_n = 10


def ip(target, rows, pas):
    if target == 'hot':
        p_index = hot_p_index
    else:
        p_index = sky_p_index
    load.move('b%d_%s'%(band,target))
    
    sys.stderr.write('%s: '%(target))
    sys.stderr.flush()

    for i,pa in enumerate(pas):
        if (i+1)%20 == 0:
            sys.stderr.write('%.2f%% '%(100.0*i/len(pas)))
            sys.stderr.flush()
            cart.update_all()

        cart._set_pa([pa,pa])
        rows[i][pa_index] = pa
        
        # start pmeter reads
        for m in pmeters:
            m.read_init()
        
        for j in range(ua_n):
            for po in range(2):
                for sb in range(2):
                    ua = cart.femc.get_sis_current(cart.ca,po,sb)*1e3
                    rows[i][ua_avg_index + po*2 + sb] += abs(ua)  # for band 6
                    rows[i][ua_dev_index + po*2 + sb] += ua*ua
        
        # fetch pmeter results, convert to mW, and reorder by polarization
        dbm = [p for m in pmeters for p in m.read_fetch()]
        mw = [10.0**(0.1*p) for p in dbm]
        mw = [mw[0], mw[2], mw[1], mw[3]]
        rows[i][p_index:p_index+len(mw)] = mw
    
    sys.stderr.write('\n')
    sys.stderr.flush()
    return 0
    # ip



try:
        
    # need to save output rows since they have both hot and sky data.
    rows = [None]*len(pas)
    for i in range(len(rows)):
        rows[i] = [0.0]*(yf_index+len(powers))
    
    if ip('hot', rows, pas):
        return
    if ip('sky', rows, pas):
        return
        
    n = ua_n*2
    for r in rows:
        for j in range(4):
            # calculate mixer current avg/dev.
            # iv just saves sum(x) and sum(x^2);
            # remember stddev is sqrt(E(x^2) - E(x)^2)
            avg = r[ua_avg_index + j] / n
            dev = (r[ua_dev_index + j]/n - avg**2)**.5
            r[ua_avg_index + j] = avg
            r[ua_dev_index + j] = dev
        
        for j in range(len(powers)):
            # calculate y-factors
            r[yf_index + j] = r[hot_p_index + j] / r[sky_p_index + j]
            
        # write out the data
        sys.stdout.write(' '.join('%g'%x for x in r) + '\n')
        sys.stdout.flush()
finally:
    # final timestamp
    sys.stdout.write(time.strftime('# %Y%m%d %H:%M:%S HST\n', time.localtime()))
    sys.stdout.flush()
    
    # retune the receiver to get settings back to nominal
    cart.tune(lo_ghz, 0.0)
    logging.info('done.')





