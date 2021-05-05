#!/local/python3/bin/python3
'''
pa_sweep.py     RMB 20190806

Tune a cartridge, then run through the PA drain voltage values [0, 2.5]
to see the shape of the curve.  Are there local maxima/minima?

This script instantiates a Cart instance directly, rather than
communicating with a running engineering task via DRAMA.  The two
probably shouldn't run at the same time.


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
import logging
import namakanui.instrument
import namakanui.util
from namakanui_tune import tune

namakanui.util.setup_logging(logging.DEBUG)

config = namakanui.util.get_config()
bands = namakanui.util.get_bands(config, simulated=False)

parser = argparse.ArgumentParser(
    formatter_class=argparse.RawTextHelpFormatter,
    description=namakanui.util.get_description(__doc__)
    )
parser.add_argument('band', type=int, choices=bands)
parser.add_argument('lo_ghz', type=float)
parser.add_argument('lock_side', nargs='?', choices=['below','above'], default='above')
# NOTE the documented value of 2.5/255 causes aliasing
# due to float32 rounding (I think), so we use a slightly higher value.
parser.add_argument('pa_step', type=float, nargs='?', default=0.009803923)
args = parser.parse_args()

# we don't need the load here
instrument = namakanui.instrument.Instrument(config, simulate=SIM_LOAD)
instrument.set_safe()
instrument.set_band(args.band)
cart = instrument.carts[band]
cart.log.setLevel(logging.DEBUG)
cart.power(1)
cart.set_lock_side(args.lock_side)

if not tune(instrument, args.band, args.lo_ghz):
    instrument.set_safe()
    logging.error('tune error, bailing out.')
    sys.exit(1)

cart.update_all()
logging.info('tuned, IF power: %g', cart.state['pll_if_power'])

# cart is tuned, do the pa sweep.
# band6 limit 70uA, band7 40uA.
if args.band == 3:
    logging.info('no SIS mixer for band 3; done.')
    sys.exit(0)
elif args.band == 6:
    limit = 70.0
else:
    limit = 50.0

logging.info('starting PA sweep with limit %g uA', limit)

pa = 0.0
step = 2.5/255;  # TODO where did this number come from?
# for band7 there are obvious steps -- different quantization?
if True:#args.band == 7:
    step = args.pa_step
    logging.info('setting step to %.9g for band %d', step, args.band)

pas = [[],[]]
mc = [[],[],[],[]]
done = False
# do each po separate since they tend to be quite different
for po in range(2):
    pa = 0.0
    while pa <= 2.5:
        pas[po].append(pa)
        cart.femc.set_cartridge_lo_pa_pol_drain_voltage_scale(cart.ca, po, pa)
        #time.sleep(0.01)
        for sb in range(2):
            curr = 0.0
            n = 10
            for i in range(n):
                curr += cart.femc.get_sis_current(cart.ca, po, sb)
            curr /= n
            curr *= 1e3
            mc[po*2+sb].append(curr)
            if abs(curr) > limit:
                # break loop
                pa = 3.0
                done = True
        pa += step
        if pa == 2.5:
            done = True
        if pa > 2.5 and not done:
            pa = 2.5
            done = True

#cart.femc.set_cartridge_lo_pa_pol_drain_voltage_scale(cart.ca, 0, 0.0)
#cart.femc.set_cartridge_lo_pa_pol_drain_voltage_scale(cart.ca, 1, 0.0)
# just tune again to restore nominal values
logging.info('sweep done, retuning...')
try:
    cart.tune(args.lo_ghz, 0.0)
except Exception as e:
    instrument.set_safe()
    logging.error('tune error: %s, IF power: %g', e, cart.state['pll_if_power'])


logging.info('done, plotting...')
logging.info('importing pylab...')
from pylab import *

for po in range(2):
    for sb in range(2):
        plot(pas[po], mc[po*2+sb], '-', label='%d%d'%(po,sb+1))

title('PA Sweep, band %d at %g GHz' % (args.band, args.lo_ghz))
xlabel('PA Drain Voltage Scale')
ylabel('Mixer Current uA')
legend(loc='best')
show()




