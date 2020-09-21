#!/local/python3/bin/python3
'''
lo_sweep.py     RMB 20200909

Tune to a range of frequencies, save PA/SIS parameters in topcat ascii format.
The goal is to create a plot similar to those in Ted Huang's email.


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
import namakanui.femc
import namakanui.load
import namakanui.ifswitch
import namakanui.util
import logging

logging.root.setLevel(logging.INFO)
logging.root.addHandler(logging.StreamHandler())

binpath, datapath = namakanui.util.get_paths()
    
parser = argparse.ArgumentParser()
parser.add_argument('band', type=int, choices=[6,7])
parser.add_argument('--lo')  # range
parser.add_argument('--load', nargs='?', default='hot')
parser.add_argument('lock_polarity', nargs='?', choices=['below','above'], default='above')
parser.add_argument('--note', nargs='?', default='', help='note for file header')
args = parser.parse_args()

band = args.band
los = namakanui.util.parse_range(args.lo, maxlen=100e3)

# create file header.
# trying to plot this manually in topcat would be a nightmare anyway,
# so just use the order that makes it easy to write the file.
sys.stdout.write(time.strftime('# %Y%m%d %H:%M:%S HST\n', time.localtime()))
sys.stdout.write('# %s\n'%(sys.argv))
sys.stdout.write('# load: %s\n'%(args.load))
sys.stdout.write('#\n')
sys.stdout.write('#lo_ghz pa0 pa1')
for mixer in ['01', '02', '11', '12']:
    sys.stdout.write(' ua%s'%(mixer))
for po in ['0', '1']:
    sys.stdout.write(' vd%s'%(po))
for po in ['0', '1']:
    sys.stdout.write(' id%s'%(po))
for po in ['0', '1']:
    sys.stdout.write(' vg%s'%(po))
sys.stdout.write('\n')
sys.stdout.flush()

# init load controller and set desired load (default hot)
load = namakanui.load.Load(datapath+'load.ini', time.sleep, namakanui.nop, simulate=0)
if args.load == 'hot' or args.load == 'sky':
    args.load = 'b%d_'%(band) + args.load
load.move(args.load)

# set agilent output to a safe level before setting ifswitch
agilent = namakanui.agilent.Agilent(datapath+'agilent.ini', time.sleep, namakanui.nop, simulate=0)
agilent.set_dbm(agilent.safe_dbm)
agilent.set_output(1)
ifswitch = namakanui.ifswitch.IFSwitch(datapath+'ifswitch.ini', time.sleep, namakanui.nop)
ifswitch.set_band(band)

# power up the cartridge
cart = namakanui.cart.Cart(band, datapath+'band%d.ini'%(band), time.sleep, namakanui.nop, simulate=0)
cart.power(1)
cart.femc.set_cartridge_lo_pll_sb_lock_polarity_select(cart.ca, {'below':0, 'above':1}[args.lock_polarity])
floog = agilent.floog * {'below':1.0, 'above':-1.0}[args.lock_polarity]


# main loop
for lo in los:
    if not namakanui.util.tune(cart, agilent, None, lo):
        continue
    sys.stdout.write('%.3f '%(lo))
    pa_drain_s = cart.state['pa_drain_s']
    sys.stdout.write('%.3f %.3f '%(pa_drain_s[0], pa_drain_s[1]))
    # average mixer currents
    n = 10
    uas = [0.0]*4
    for i in range(n):
        for po in range(2):
            for sb in range(2):
                uas[po*2 + sb] += cart.femc.get_sis_current(cart.ca,po,sb)*1e3
    for i in range(4):
        uas[i] /= n
        sys.stdout.write('%.3f '%(uas[i]))
    # amp feedback
    pa_vd = [0.0]*2
    pa_id = [0.0]*2
    pa_vg = [0.0]*2
    for po in range(2):
        pa_vg[po] = cart.femc.get_cartridge_lo_pa_gate_voltage(cart.ca, po)
        pa_vd[po] = cart.femc.get_cartridge_lo_pa_drain_voltage(cart.ca, po)
        pa_id[po] = cart.femc.get_cartridge_lo_pa_drain_current(cart.ca, po)
    sys.stdout.write('%.3f %.3f '%(pa_vd[0], pa_vd[1]))
    sys.stdout.write('%.3f %.3f '%(pa_id[0], pa_id[1]))
    sys.stdout.write('%.3f %.3f '%(pa_vg[0], pa_vg[1]))
    sys.stdout.write('\n')
    sys.stdout.flush()




