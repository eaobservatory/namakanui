#!/local/python3/bin/python3
'''
tune_only.py
RMB 20190827

Tune the receiver, using interpolated values from the dbm table.
Locks with 'above' polarity by default.

This script replaces tune.sh, which was a wrapper around dbm_table.py,
and might have set the signal generator up to 0 dbm if it failed to lock.
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

binpath = os.path.dirname(os.path.realpath(sys.argv[0])) + '/'
datapath = os.path.realpath(binpath + '../../data') + '/'

parser = argparse.ArgumentParser()
parser.add_argument('band', type=int, choices=[3,6,7])
parser.add_argument('lo_ghz', type=float)
parser.add_argument('lock_polarity', nargs='?', choices=['below', 'above'], default='above')
args = parser.parse_args()

# sanity check
lo_ghz_range = {3:[75,90], 6:[210,270], 7:[280,365]}[args.band]
if args.lo_ghz < lo_ghz_range[0] or args.lo_ghz > lo_ghz_range[1]:
    logging.error('lo_ghz %g outside range %s for band %d', args.lo_ghz, lo_ghz_range, args.band)
    sys.exit(1)

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

fyig = args.lo_ghz / (cart.cold_mult * cart.warm_mult)
fsig = (fyig*cart.warm_mult + floog) / agilent.harmonic
agilent.set_hz(fsig*1e9)

dbm = agilent.interp_dbm(args.band, args.lo_ghz)
logging.info('setting signal generator power to %.2f dbm', dbm)
agilent.set_dbm(dbm)
time.sleep(0.1)
try:
    cart.tune(args.lo_ghz, 0.0)
except RuntimeError as e:
    agilent.set_dbm(-30.0)
    logging.error('tune error: %s, IF power: %g', e, cart.state['pll_if_power'])
    sys.exit(1)

time.sleep(0.1)
cart.update_all()
if cart.state['pll_unlock']:
    agilent.set_dbm(-30.0)
    logging.error('lost lock after tuning, IF power: %g', cart.state['pll_if_power'])
    sys.exit(1)

logging.info('band %d tuned to %g GHz, IF power: %g', args.band, args.lo_ghz, cart.state['pll_if_power'])
logging.info('done.')





