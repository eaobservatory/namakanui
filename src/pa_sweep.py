#!/local/python3/bin/python3
'''
pa_sweep.py
RMB 20190806

Tune a cartridge, then run through the PA drain voltage values [0, 2.5]
to see the shape of the curve.  Are there local maxima/minima?

This script instantiates a Cart instance directly, rather than
communicating with a running engineering task via DRAMA.  The two
probably shouldn't run at the same time.

Usage:
pa_sweep.py <band> <lo_ghz> <lock_polarity> [pa_step=0.01]
'''

import jac_sw
import sys
import os
import time
import argparse
import namakanui.cart
import namakanui.agilent
import logging

logging.root.setLevel(logging.DEBUG)
logging.root.addHandler(logging.StreamHandler())

logging.info('importing pylab...')
from pylab import *

binpath = os.path.dirname(os.path.realpath(sys.argv[0])) + '/'
# HACK, should crawl up
if 'install' in binpath:
    datapath = os.path.realpath(binpath + '../../data') + '/'
else:
    datapath = os.path.realpath(binpath + '../data') + '/'

parser = argparse.ArgumentParser()
parser.add_argument('band', type=int, choices=[3,6,7])
parser.add_argument('lo_ghz', type=float)
parser.add_argument('lock_polarity', choices=['below','above'])
# NOTE the documented value of 2.5/255 causes aliasing
# due to float32 rounding (I think), so we use a slightly higher value.
parser.add_argument('pa_step', type=float, nargs='?', default=0.009803923)
args = parser.parse_args()

def mypub(n,s):
    pass

agilent = namakanui.agilent.Agilent(datapath+'agilent.ini', time.sleep, mypub, simulate=0)
agilent.log.setLevel(logging.INFO)
agilent.set_dbm(-30.0)
agilent.set_output(1)
cart = namakanui.cart.Cart(args.band, datapath+'band%d.ini'%(args.band), time.sleep, mypub, simulate=0)
cart.power(1)
cart.femc.set_cartridge_lo_pll_sb_lock_polarity_select(cart.ca, {'below':0, 'above':1}[args.lock_polarity])
floog = agilent.floog * {'below':1.0, 'above':-1.0}[args.lock_polarity]

logging.info('setting agilent...')

fyig = args.lo_ghz / (cart.cold_mult * cart.warm_mult)
fsig = (fyig*cart.warm_mult + floog) / agilent.harmonic
agilent.set_hz(fsig*1e9)
dbm = agilent.interp_dbm(args.band, args.lo_ghz)
agilent.set_dbm(dbm)

logging.info('tuning cartridge...')

try:
    cart.tune(args.lo_ghz, 0.0)
except Exception as e:
    agilent.set_dbm(-30.0)
    logging.error('tune error: %s, IF power: %g', e, cart.state['pll_if_power'])
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
    agilent.set_dbm(-30.0)
    logging.error('tune error: %s, IF power: %g', e, cart.state['pll_if_power'])

logging.info('done, plotting...')

for po in range(2):
    for sb in range(2):
        plot(pas[po], mc[po*2+sb], '-', label='%d%d'%(po,sb+1))

title('PA Sweep, band %d at %g GHz' % (args.band, args.lo_ghz))
xlabel('PA Drain Voltage Scale')
ylabel('Mixer Current uA')
legend(loc='best')
show()




