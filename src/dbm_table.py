#!/local/python3/bin/python3
'''
dbm_table.py
RMB 20190805

Build a dBm table for a receiver by tuning in a range of frequencies and
adjusting the power output from the signal generator.  Ideally we want
the IF total power reading to be in the [-1,-2]V range, though being
in the [-.7,-3]V range is still acceptable.

This script instantiates a Cart instance directly, rather than
communicating with a running engineering task via DRAMA.  The two
probably shouldn't run at the same time.

The <dbm> parameter gives the starting dBm setting at each frequency;
I've used -12 dBm for the ASIAA IF switch and -16 dBm for Bill's IF switch.
You can also give "ini-X" for this parameter to start with the value
interpolated from the table in the agilent.ini file, minus X dBm.
In any case, the resulting value will be clamped to [-20,-6] dBm for safety.

Once you've created an output file, it can be converted to an ini table:

grep -v '^#' <file> | sort -n | awk '{ printf "dbm%02d=%s, %6s\n", NR, $1, $2 }'


Usage:
dbm_table.py <band> <LO_GHz_start> <LO_GHz_end> <LO_GHz_step> <lock_polarity> <dbm>

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
# HACK, should crawl up
if 'install' in binpath:
    datapath = os.path.realpath(binpath + '../../data') + '/'
else:
    datapath = os.path.realpath(binpath + '../data') + '/'

parser = argparse.ArgumentParser()
parser.add_argument('band', type=int, choices=[3,6,7])
parser.add_argument('LO_GHz_start', type=float)
parser.add_argument('LO_GHz_end', type=float)
parser.add_argument('LO_GHz_step', type=float)
parser.add_argument('lock_polarity', choices=['below','above'])
parser.add_argument('dbm')
args = parser.parse_args()
#print(args.band, args.LO_GHz_start, args.LO_GHz_end, args.LO_GHz_step)

if args.LO_GHz_step < 0.01:
    logging.error('invalid step, must be >= 0.01 GHz')
    sys.exit(1)
if args.LO_GHz_start > args.LO_GHz_end:
    logging.error('start/end out of order')
    sys.exit(1)

use_ini = False
try:
    args.dbm = float(args.dbm)
except:
    if not args.dbm.startswith('ini'):
        logging.error('invalid dbm, must be a number or "ini"')
        sys.exit(1)
    use_ini = True
    args.dbm = float(args.dbm[3:] or '0')

#sys.exit(0)

def mypub(n,s):
    pass


agilent = namakanui.agilent.Agilent(datapath+'agilent.ini', time.sleep, mypub, simulate=0)
agilent.log.setLevel(logging.INFO)
agilent.set_dbm(agilent.safe_dbm)
agilent.set_output(1)    
cart = namakanui.cart.Cart(args.band, datapath+'band%d.ini'%(args.band), time.sleep, mypub, simulate=0)
cart.power(1)
cart.femc.set_cartridge_lo_pll_sb_lock_polarity_select(cart.ca, {'below':0, 'above':1}[args.lock_polarity])
floog = agilent.floog * {'below':1.0, 'above':-1.0}[args.lock_polarity]

# check to make sure this receiver is selected.
# TODO: once Bill's switch is installed, control it directly.
rp = cart.state['pll_ref_power']
if rp < -3.0:
    logging.error('PLL reference power (FLOOG, 31.5 MHz) is too strong (%.2f V).  Please attenuate.', rp)
    sys.exit(1)
if rp > -0.5:
    logging.error('PLL reference power (FLOOG, 31.5 MHz) is too weak (%.2f V).', rp)
    logging.error('Please make sure the IF switch has band %d selected.', args.band)
    sys.exit(1)


def adjust_dbm(lo_ghz):
    
    # sanity check
    lo_ghz_range = {3:[75,90], 6:[210,270], 7:[280,365]}[args.band]
    if lo_ghz < lo_ghz_range[0] or lo_ghz > lo_ghz_range[1]:
        logging.error('skipping lo_ghz %g, outside range %s for band %d', lo_ghz, lo_ghz_range, args.band)
        return
    
    delay = .05
    fyig = lo_ghz / (cart.cold_mult * cart.warm_mult)
    fsig = (fyig*cart.warm_mult + floog) / agilent.harmonic
    agilent.set_hz(fsig*1e9)
    
    # get starting dbm value
    dbm = args.dbm
    if use_ini:
        dbm += agilent.interp_dbm(args.band, lo_ghz)
    
    if dbm < -20.0:
        dbm = -20.0
    elif dbm > agilent.max_dbm -1.0:
        dbm = agilent.max_dbm -1.0
    
    while dbm <= agilent.max_dbm:
        logging.info('lo_ghz %g, dbm %g', lo_ghz, dbm)
        agilent.set_dbm(dbm)
        time.sleep(delay)
        try:
            cart.tune(lo_ghz, 0.0)
            break
        except RuntimeError as e:
            logging.error('tune error: %s, IF power: %g', e, cart.state['pll_if_power'])
            dbm += 1.0
    time.sleep(delay)
    cart.update_all()
    if cart.state['pll_unlock']:
        agilent.set_dbm(agilent.safe_dbm)
        logging.error('failed to lock at %g', lo_ghz)
        return
    logging.info('LOCKED, dbm=%g, pll_if_power=%g', dbm, cart.state['pll_if_power'])
    
    # quickly reduce power if initial lock is too strong
    while cart.state['pll_if_power'] < -1.5 and dbm > -20.0 and not cart.state['pll_unlock']:
        dbm -= 0.5
        agilent.set_dbm(dbm)
        time.sleep(delay)
        cart.update_all()
        logging.info('lowering power, dbm=%g, pll_if_power=%g', dbm, cart.state['pll_if_power'])
        if cart.state['pll_unlock']:
            logging.error('lost lock, relocking...')
            try:
                cart.tune(lo_ghz, 0.0)
                time.sleep(delay)
                cart.update_all()
            except RuntimeError as e:
                logging.error('tune error: %s', e)
                break   
    
    # slowly increase power to target
    while cart.state['pll_if_power'] > -1.5 and dbm < agilent.max_dbm-0.1 and not cart.state['pll_unlock']:
        if cart.state['pll_if_power'] > -1.0 and dbm < agilent.max_dbm-0.3:
            dbm += 0.3
        elif cart.state['pll_if_power'] > -1.25 and dbm < agilent.max_dbm-0.2:
            dbm += 0.2
        else:
            dbm += 0.1
        agilent.set_dbm(dbm)
        time.sleep(delay)
        cart.update_all()
        logging.info('raising power, dbm=%g, pll_if_power=%g', dbm, cart.state['pll_if_power'])
        if cart.state['pll_unlock']:
            logging.error('lost lock, relocking...')
            try:
                cart.tune(lo_ghz, 0.0)
                time.sleep(delay)
                cart.update_all()
            except RuntimeError as e:
                logging.error('tune error: %s', e)
                break
    
    if cart.state['pll_unlock']:
        agilent.set_dbm(agilent.safe_dbm)
        logging.error('lost lock at %g', lo_ghz)
        return
    #print(lo_ghz, dbm, cart.state['pll_if_power'])
    sys.stdout.write('%.3f %6.2f %.3f %.3f %.3f\n' % (lo_ghz, dbm, cart.state['pll_if_power'], cart.state['pa_drain_s'][0], cart.state['pa_drain_s'][1]))
    sys.stdout.flush()


def try_adjust_dbm(lo_ghz):
    try:
        adjust_dbm(lo_ghz)
    except Exception as e:
        agilent.set_dbm(agilent.safe_dbm)
        logging.error('unhandled exception: %s', e)
        raise


sys.stdout.write('#lo_ghz dbm pll_if_power pa_0 pa_1\n')  # topcat ascii
lo_ghz = args.LO_GHz_start
while lo_ghz < args.LO_GHz_end:
    try_adjust_dbm(lo_ghz)
    lo_ghz += args.LO_GHz_step
lo_ghz = args.LO_GHz_end
try_adjust_dbm(lo_ghz)

# since this script is also used to tune the receiver, retune once we've
# found the optimal IF power to servo the PA.
cart.update_all()
if cart.state['lo_ghz'] == lo_ghz and not cart.state['pll_unlock']:
    logging.info('retuning at %g to adjust PA...', lo_ghz)
    try:
        cart.tune(lo_ghz, 0.0)
        time.sleep(0.1)
        cart.update_all()
        if cart.state['pll_unlock']:
            agilent.set_dbm(agilent.safe_dbm)
            logging.error('lost lock at %g', lo_ghz)
        logging.info('band %d tuned to %g GHz, IF power: %g', args.band, lo_ghz, cart.state['pll_if_power'])
    except Exception as e:
        agilent.set_dbm(agilent.safe_dbm)
        logging.error('final retune exception: %s', e)

# show the last dbm setting
agilent.update()
logging.info('final dbm: %.2f', agilent.state['dbm'])

logging.info('done.')





