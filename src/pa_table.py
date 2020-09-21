#!/local/python3/bin/python3
'''
pa_table.py     RMB 20200406
Create PA drain/gate voltage table (LOParams).

Perform a Vg sweep at each frequency with Vd set to 2.5
in order to find the point of maximum available mixer current.
Then repeat _servo_pa to find Vd for target mixer current
from the MixerParams table.


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
import numpy
import logging

logging.root.setLevel(logging.INFO)
logging.root.addHandler(logging.StreamHandler())

binpath, datapath = namakanui.util.get_paths()

parser = argparse.ArgumentParser(description='''
Generate LOParam (PA drain/gate voltage) table.
''', formatter_class=argparse.RawTextHelpFormatter)

parser.add_argument('band', type=int, choices=[6,7])
parser.add_argument('--lo')  # range
parser.add_argument('--vg')  # range (for b6, use -.40:.14:.01)
parser.add_argument('--vd', type=float, default=2.5)  # vd for both pols during vg sweep
# note: always use 'above' reference tuning
args = parser.parse_args()

los = namakanui.util.parse_range(args.lo, maxlen=1e3)
vgs = namakanui.util.parse_range(args.vg, maxlen=1e2)  # TODO okay for b7?

# set agilent output to a safe level before setting ifswitch
agilent = namakanui.agilent.Agilent(datapath+'agilent.ini', time.sleep, namakanui.nop)
agilent.set_dbm(agilent.safe_dbm)
ifswitch = namakanui.ifswitch.IFSwitch(datapath+'ifswitch.ini', time.sleep, namakanui.nop)
ifswitch.set_band(args.band)

# init load controller and set to hot (ambient) load for this band
load = namakanui.load.Load(datapath+'load.ini', time.sleep, namakanui.nop)
load.move('b%d_hot'%(args.band))

# setup cartridge
cart = namakanui.cart.Cart(args.band, datapath+'band%d.ini'%(args.band), time.sleep, namakanui.nop)
cart.power(1)
cart.femc.set_cartridge_lo_pll_sb_lock_polarity_select(cart.ca, {'below':0, 'above':1}['above'])#args.lock_polarity])

# for _servo_pa output
cart.log.setLevel(logging.DEBUG)


# write out a header for our output file
print(time.strftime('# %Y%m%d %H:%M:%S HST', time.localtime()))
print('#', sys.argv)
print('# vdX: LO PA drain voltage for polX')
print('# vdX: LO PA gate voltage for polX')
print('#')
print('#lo_ghz vd0   vd1   vg0  vg1')

# 7-point averaging function to smooth vg-ua curves
def smooth(y):
    # assume equal x spacing
    # mirror data around endpoints
    # dy = y-y0; ym = y0 - dy = y0 - (y-y0) = 2y0 - y
    ym0 = 2*y[0] - y[1:4]
    ym1 = 2*y[-1] - y[-4:-1]
    ym0 = ym0[::-1]
    ym1 = ym1[::-1]
    yb = numpy.concatenate((ym0,y,ym1))
    w = numpy.array([1,4,8,10,8,4,1])
    ws = w.sum()
    s = y.copy()
    for i in range(len(s)):
        yw = yb[i:i+7]*w
        s[i] = yw.sum()/ws
    return s

# main loops
for lo_ghz in los:
    if not namakanui.util.tune(cart, agilent, None, lo_ghz, pll_range=[-1.0, -2.0]):
        continue
    
    # get nominal pa, it's probably close to target and will save time later
    nom_vd = cart.state['pa_drain_s']
    
    logging.info('set pa %.2f', args.vd)
    cart._set_pa([args.vd, args.vd])
    
    ua = [[], [], [], []]
    for vg in vgs:
        cart.femc.set_cartridge_lo_pa_pol_gate_voltage(cart.ca, 0, vg)
        cart.femc.set_cartridge_lo_pa_pol_gate_voltage(cart.ca, 1, vg)
        #cart.update_all()  # not necessary
        # average 10 mixer current readings
        n = 10
        sis_c = [0.0]*4
        for i in range(n):
            for po in range(2):
                for sb in range(2):
                    sis_c[po*2 + sb] += cart.femc.get_sis_current(cart.ca,po,sb)*1e3
        sis_c = [x/n for x in sis_c]
        for i,ua_list in enumerate(ua):
            ua_list.append(sis_c[i])
    ua = [numpy.array(ua_list) for ua_list in ua]
    s = [smooth(ua[1]-ua[0]), smooth(ua[3]-ua[2])]
    si = [y.argmax() for y in s]
    vg = [vgs[i] for i in si]
    
    pa = nom_vd + vg
    logging.info('set pa %s', pa)
    cart._set_pa(pa)
    logging.info('_servo_pa')
    cart._servo_pa()  # TODO might want to see debug output here
    vd = cart.state['pa_drain_s']
    
    print('%.3f %.2f %.2f %.2f %.2f'%(lo_ghz, vd[0], vd[1], vg[0], vg[1]))
    
logging.info('done.')






