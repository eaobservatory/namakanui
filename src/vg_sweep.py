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
import argparse
import namakanui.cart
import namakanui.agilent
import namakanui.ifswitch
import namakanui.load
import namakanui.util
import logging

logging.root.setLevel(logging.INFO)
logging.root.addHandler(logging.StreamHandler())

binpath,datapath = namakanui.util.get_paths()

parser = argparse.ArgumentParser(description='''
Test effect of PA gate voltage setting.
''', formatter_class=argparse.RawTextHelpFormatter)

parser.add_argument('band', type=int, choices=[6,7])
parser.add_argument('--lo')  # range
parser.add_argument('--vg')  # range
parser.add_argument('--vd', type=float)  # optional, fixed vd value for both pols
# we'll just always use 'above' reference tuning; add later if needed
args = parser.parse_args()

los = namakanui.util.parse_range(args.lo, maxlen=1e3)
vgs = namakanui.util.parse_range(args.vg, maxlen=1e2)

# set agilent output to a safe level before setting ifswitch
agilent = namakanui.agilent.Agilent(datapath+'agilent.ini', time.sleep, namakanui.nop, simulate=0)
agilent.set_dbm(agilent.safe_dbm)
ifswitch = namakanui.ifswitch.IFSwitch(datapath+'ifswitch.ini', time.sleep, namakanui.nop, simulate=0)
ifswitch.set_band(args.band)

# init load controller and set to hot (ambient) load for this band
load = namakanui.load.Load(datapath+'load.ini', time.sleep, namakanui.nop, simulate=0)
load.move('b%d_hot'%(args.band))

# setup cartridge
cart = namakanui.cart.Cart(args.band, datapath+'band%d.ini'%(args.band), time.sleep, namakanui.nop, simulate=0)
cart.power(1)
cart.femc.set_cartridge_lo_pll_sb_lock_polarity_select(cart.ca, {'below':0, 'above':1}['above'])#args.lock_polarity])

# write out a header for our output file
print(time.strftime('# %Y%m%d %H:%M:%S HST', time.localtime()))
print('#', sys.argv)
print('#')
print('#lo_ghz vg ua01 ua02 ua11 ua12 drain_c0 drain_c1')

# main loops
for lo_ghz in los:
    if not namakanui.util.tune(cart, agilent, None, lo_ghz, pll_range=[-1.0, -2.0]):
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
namakanui.util.tune(cart, agilent, None, los[0], pll_range=[-1.0, -2.0])
logging.info('done.')


        


