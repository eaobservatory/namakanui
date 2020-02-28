#!/local/python3/bin/python3
'''
RMB 20200221
Tune to a range of frequencies.
At each frequency, set PA to a range of values.
Record average mixer current at each PA, for each mixer.

Motivation:  Mixer current was much lower than expected
at LO 249 GHz with the new mixer block.  I'm wondering
if there are strange dropouts at various frequencies.

Recording this data is a little troublesome.
I'll use topcat ascii format, with each column
a separate mixer/pa combo.  Plotting data is also
troublesome.  I might want a separate program for that.
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
import logging

logging.root.setLevel(logging.INFO)
logging.root.addHandler(logging.StreamHandler())

binpath = os.path.dirname(os.path.realpath(sys.argv[0])) + '/'
# HACK, should crawl up
if 'install' in binpath:
    datapath = os.path.realpath(binpath + '../../data') + '/'
else:
    datapath = os.path.realpath(binpath + '../data') + '/'
    
parser = argparse.ArgumentParser()
parser.add_argument('band', type=int, choices=[6,7])
parser.add_argument('--lo')  # range
parser.add_argument('--pa')  # range
parser.add_argument('lock_polarity', nargs='?', choices=['below','above'], default='above')
args = parser.parse_args()

# borrowed from yfactor.py.  TODO utility module for these scripts
def parse_range(s, what, min_step, max_step):
    s = s.split(':')
    first = float(s[0])
    if first < 0:
        logging.error(what+': negative values not allowed\n')
        sys.exit(1)
    if len(s) == 1:
        return [first]
    last = float(s[1])
    if last <= first:
        logging.error(what+': last must be greater than first\n')
        sys.exit(1)
    if len(s) == 2:
        step = last - first
    else:
        step = float(s[2])
    if not min_step <= step <= max_step:
        logging.error(what+': step outside [%g,%g] range\n'%(min_step,max_step))
        sys.exit(1)
    arr = []
    val = first
    while val < last:
        arr.append(val)
        val += step
    if abs(arr[-1] - last) < 1e-6:
        arr[-1] = last
    else:
        arr.append(last)
    return arr


band = args.band
los = parse_range(args.lo, 'lo', 0.001, 500.0)
pas = parse_range(args.pa, 'pa', 0.01, 2.5)

# create file header.
# trying to plot this manually in topcat would be a nightmare anyway,
# so just use the order that makes it easy to write the file.
sys.stdout.write('#lo_ghz ')
for pa in pas:
    for mixer in ['01', '02', '11', '12']:
        sys.stdout.write('%s_%.3f '%(mixer, pa))
sys.stdout.write('\n')

# init load controller and set to hot (ambient) load for this band
load = namakanui.load.Load(datapath+'load.ini', time.sleep, namakanui.nop, simulate=0)
load.move('b%d_hot'%(band))

# set agilent output to a safe level before setting ifswitch
agilent = namakanui.agilent.Agilent(datapath+'agilent.ini', time.sleep, namakanui.nop, simulate=0)
agilent.set_dbm(agilent.safe_dbm)
agilent.set_output(1)
ifswitch = namakanui.ifswitch.IFSwitch(datapath+'ifswitch.ini', time.sleep, namakanui.nop, simulate=0)
ifswitch.set_band(band)

# power up the cartridge
cart = namakanui.cart.Cart(band, datapath+'band%d.ini'%(band), time.sleep, namakanui.nop, simulate=0)
cart.power(1)
cart.femc.set_cartridge_lo_pll_sb_lock_polarity_select(cart.ca, {'below':0, 'above':1}[args.lock_polarity])
floog = agilent.floog * {'below':1.0, 'above':-1.0}[args.lock_polarity]

# define a function to tune and adjust agilent output if needed
def tune(lo_ghz):
    logging.info('tuning to %.3f ghz...', lo_ghz)
    agilent.set_dbm(agilent.safe_dbm)
    fyig = lo_ghz / (cart.cold_mult * cart.warm_mult)
    fsig = (fyig*cart.warm_mult + floog) / agilent.harmonic
    agilent.set_hz(fsig*1e9)
    dbm = agilent.interp_dbm(band, lo_ghz)
    hi_dbm = dbm + 3.0  # at most double power
    agilent.set_dbm(dbm)
    time.sleep(0.05)
    agilent.update()
    try:
        cart.tune(lo_ghz, 0.0, skip_servo_pa=True)
    except RuntimeError as e:
        logging.error('tune failed at %.3f ghz, dbm %.3f', lo_ghz, dbm)
    cart.update_all()
    # increase power if needed
    while (cart.state['pll_unlock'] or cart.state['pll_if_power'] > -0.8) and dbm < agilent.max_dbm and dbm < hi_dbm:
        dbm += 1.0
        if dbm > agilent.max_dbm:
            dbm = agilent.max_dbm
        if dbm > hi_dbm:
            dbm = hi_dbm
        logging.info('unlock: %d, pll_if: %.3f; raising power to %.2f...', cart.state['pll_unlock'], cart.state['pll_if_power'], dbm)
        agilent.set_dbm(dbm)
        time.sleep(0.05)
        agilent.update()
        cart.update_all()
        if cart.state['pll_unlock']:
            try:
                cart.tune(lo_ghz, 0.0, skip_servo_pa=True)
            except RuntimeError as e:
                logging.error('tune failed at %.3f ghz, dbm %.3f', lo_ghz, dbm)
            cart.update_all()
    # decrease power if too strong
    while (not cart.state['pll_unlock']) and cart.state['pll_if_power'] < -2.5 and dbm > agilent.safe_dbm:
        dbm -= 0.2
        if dbm < agilent.safe_dbm:
            dbm = agilent.safe_dbm
        logging.info('unlock: %d, pll_if: %.3f; lowering power to %.2f...', cart.state['pll_unlock'], cart.state['pll_if_power'], dbm)
        agilent.set_dbm(dbm)
        time.sleep(0.05)
        agilent.update()
        cart.update_all()
        if cart.state['pll_unlock']:
            try:
                cart.tune(lo_ghz, 0.0, skip_servo_pa=True)
            except RuntimeError as e:
                logging.error('tune failed at %.3f ghz, dbm %.3f', lo_ghz, dbm)
            cart.update_all()
    logging.info('unlock: %d, pll_if: %.3f; final dbm %.2f', cart.state['pll_unlock'], cart.state['pll_if_power'], dbm)
    if cart.state['pll_unlock']:
        logging.info('unlocked at %.3f ghz, setting to safe dbm.', lo_ghz)
        agilent.set_dbm(agilent.safe_dbm)
        return False
    logging.info('tuned to %.3f ghz', lo_ghz)
    return True
    # tune

x = []
y = [[], [], [], []]
# we need a y for each mixer and pa; y[mixer][pa_index] is an array of len(x)
for i in range(4):
    for pa in pas:
        y[i].append([])

# main loop
for lo in los:
    if not tune(lo):
        continue
    x.append(lo)
    sys.stdout.write('%.3f '%(lo))
    for j,pa in enumerate(pas):
        cart._set_pa([pa,pa])
        time.sleep(0.05)
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
    sys.stdout.write('\n')

# make a set of plots, one subplot per mixer
logging.info('done.  creating plot...')
from pylab import *
for i in range(4):
    p = subplot(2,2,i+1)
    for j,pa in enumerate(pas):
        p.plot(x,y[i][j])
    p.grid()
show()

                








