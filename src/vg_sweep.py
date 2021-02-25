#!/local/python3/bin/python3
'''
vg_sweep.py     RMB 20200330
Sweep PA gate voltage to test effect on SIS mixer current.


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


namakanui.util.setup_logging()

config = namakanui.util.get_config()
bands = namakanui.util.get_bands(config, simulated=False, has_sis_mixers=True)

parser = argparse.ArgumentParser(description='''
Test effect of PA gate voltage setting.
''', formatter_class=argparse.RawTextHelpFormatter)
parser.add_argument('band', type=int, choices=bands)
parser.add_argument('--lo')  # range
parser.add_argument('--vg')  # range
parser.add_argument('--vd', type=float)  # optional, fixed vd value for both pols
parser.add_argument('--lock_side', nargs='?', choices=['below','above'], default='above')
args = parser.parse_args()

los = namakanui.util.parse_range(args.lo, maxlen=1e3)
vgs = namakanui.util.parse_range(args.vg, maxlen=1e2)

instrument = namakanui.instrument.Instrument(config)
instrument.set_safe()
instrument.set_band(args.band)
instrument.load.move('b%d_hot'%(args.band))
cart = instrument.carts[band]
cart.power(1)
cart.set_lock_side(args.lock_side)

# write out a header for our output file
print(time.strftime('# %Y%m%d %H:%M:%S HST', time.localtime()))
print('#', sys.argv)
print('#')
print('#lo_ghz vg ua01 ua02 ua11 ua12 drain_c0 drain_c1')

# main loops
for lo_ghz in los:
    if not tune(instrument, args.band, lo_ghz, pll_if=[-1.0, -2.0]):
        continue
    
    if args.vd:
        logging.info('set pa %.2f', args.vd)
        cart._set_pa([args.vd, args.vd])
    
    for vg in vgs:
        cart.femc.set_cartridge_lo_pa_pol_gate_voltage(cart.ca, 0, vg)
        cart.femc.set_cartridge_lo_pa_pol_gate_voltage(cart.ca, 1, vg)
        cart.update_all()
        #sis_c = cart.state['sis_c']
        #sis_c = [x*1e3 for x in sis_c]  # mA to uA
        # average 10 mixer current readings
        n = 10
        sis_c = [0.0]*4
        for i in range(n):
            for po in range(2):
                for sb in range(2):
                    sis_c[po*2 + sb] += cart.femc.get_sis_current(cart.ca,po,sb)*1e3
        sis_c = [x/n for x in sis_c]
        drain_c = cart.state['pa_drain_c']
        a = [lo_ghz, vg] + sis_c + drain_c  # being able to *sis_c would be nice
        print('%.3f %.2f %.2f %.2f %.2f %.2f %.2f %.2f'%tuple(a))

logging.info('tuning back to starting freq to reset pa...')
tune(instrument, args.band, los[0], pll_if=[-1.0, -2.0])
logging.info('done.')


        


