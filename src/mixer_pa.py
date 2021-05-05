#!/local/python3/bin/python3
'''
mixer_pa.py     RMB 20200221

Tune to a range of frequencies.
At each frequency, set PA to a range of values.
Record average mixer current at each PA, for each mixer.

Motivation:  Mixer current was much lower than expected
at LO 249 GHz with the new mixer block.  I'm wondering
if there are strange dropouts at various frequencies.

Data is saved to stdout in topcat ascii format,
with each column a separate mixer/pa combo.


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

parser = argparse.ArgumentParser(
    formatter_class=argparse.RawTextHelpFormatter,
    description=namakanui.util.get_description(__doc__)
    )
parser.add_argument('band', type=int, choices=bands)
parser.add_argument('--lo')  # range
parser.add_argument('--pa')  # range
parser.add_argument('--load', nargs='?', default='hot')
parser.add_argument('lock_side', nargs='?', choices=['below','above'], default='above')
parser.add_argument('--note', nargs='?', default='', help='note for file header')
args = parser.parse_args()

band = args.band
los = namakanui.util.parse_range(args.lo, maxlen=100e3)
pas = namakanui.util.parse_range(args.pa, maxlen=300)
if args.load == 'hot' or args.load == 'sky':
    args.load = 'b%d_'%(band) + args.load

# create file header.
# trying to plot this manually in topcat would be a nightmare anyway,
# so just use the order that makes it easy to write the file.
sys.stdout.write(time.strftime('# %Y%m%d %H:%M:%S HST\n', time.localtime()))
sys.stdout.write('# %s\n'%(sys.argv))
sys.stdout.write('# load: %s\n'%(args.load))
sys.stdout.write('#\n')
sys.stdout.write('#lo_ghz pa_3v pa_5v ')
for pa in pas:
    for mixer in ['01', '02', '11', '12']:
        sys.stdout.write('ua%s_%03d '%(mixer, pa*100))
    for po in ['0', '1']:
        sys.stdout.write('vd%s_%03d '%(po, pa*100))
    for po in ['0', '1']:
        sys.stdout.write('id%s_%03d '%(po, pa*100))
    for po in ['0', '1']:
        sys.stdout.write('vg%s_%03d '%(po, pa*100))
sys.stdout.write('\n')
sys.stdout.flush()

instrument = namakanui.instrument.Instrument(config)
instrument.set_safe()
instrument.set_band(args.band)
instrument.load.move(args.load)
cart = instrument.carts[band]
cart.power(1)
cart.set_lock_side(args.lock_side)


x = []
y = [[], [], [], []]
# we need a y for each mixer and pa; y[mixer][pa_index] is an array of len(x)
for i in range(4):
    for pa in pas:
        y[i].append([])

# main loop
for lo in los:
    if not tune(instrument, band, lo, skip_servo_pa=True):
        continue
    x.append(lo)
    sys.stdout.write('%.3f '%(lo))
    for j,pa in enumerate(pas):
        cart._set_pa([pa,pa])
        time.sleep(0.05)
        # check voltages
        pa_3v = cart.femc.get_cartridge_lo_pa_supply_voltage_3v(cart.ca)
        pa_5v = cart.femc.get_cartridge_lo_pa_supply_voltage_5v(cart.ca)
        sys.stdout.write('%.3f %.3f '%(pa_3v, pa_5v))
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
            y[i][j].append(uas[i])
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

# make a set of plots, one subplot per mixer
logging.info('done.  creating plot...')
from pylab import *
for i in range(4):
    p = subplot(2,2,i+1)
    for j,pa in enumerate(pas):
        p.plot(x,y[i][j])
    p.grid()
show()


