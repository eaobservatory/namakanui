#!/local/python3/bin/python3
'''
jumping_tpd2.py     20200630 RMB

During keysight_tpd2.py tests there was an instance where retuning the
receiver at the same frequency (225 GHz) resulted in a jump in TPD2 power
for the p1 mixers.

This script looks for such jumps and logs relevant info.


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
import drama
import sys
import os
import time
import random
import argparse
import namakanui.cart
import namakanui.agilent
import namakanui.ifswitch
import namakanui.load
import namakanui.femc
import namakanui.util
import logging

taskname = 'JTP_%d'%(os.getpid())

logging.root.setLevel(logging.INFO)
logging.root.addHandler(logging.StreamHandler())

binpath, datapath = namakanui.util.get_paths()

# use explicit arguments to avoid confusion
parser = argparse.ArgumentParser(description='''
''',
  formatter_class=argparse.RawTextHelpFormatter)
parser.add_argument('band', type=int, choices=[6,7])
parser.add_argument('lo_ghz', type=float)
parser.add_argument('lock_polarity', nargs='?', choices=['below','above'], default='above')
parser.add_argument('--level_only', action='store_true')
args = parser.parse_args()

band = args.band
lo_ghz = args.lo_ghz
lo_range = {6:[219,266], 7:[281,367]}[band]
if not lo_range[0] <= lo_ghz <= lo_range[1]:
    logging.error('lo_ghz %g outside %s range for band %d', lo_ghz, lo_range, band)
    sys.exit(1)

# set agilent output to a safe level before setting ifswitch
agilent = namakanui.agilent.Agilent(datapath+'agilent.ini', time.sleep, namakanui.nop)
agilent.set_dbm(agilent.safe_dbm)
agilent.set_output(1)
ifswitch = namakanui.ifswitch.IFSwitch(datapath+'ifswitch.ini', time.sleep, namakanui.nop)
ifswitch.set_band(band)

# init load controller and set to hot (ambient) load for this band
load = namakanui.load.Load(datapath+'load.ini', time.sleep, namakanui.nop)
load.move('b%d_hot'%(band))

# setup cartridge and tune, adjusting power as needed
cart = namakanui.cart.Cart(band, datapath+'band%d.ini'%(band), time.sleep, namakanui.nop)
cart.power(1)
cart.femc.set_cartridge_lo_pll_sb_lock_polarity_select(cart.ca, {'below':0, 'above':1}[args.lock_polarity])
if not namakanui.util.tune(cart, agilent, None, lo_ghz):
    logging.error('failed to tune to %.3f ghz', lo_ghz)
    sys.exit(1)

# save this dbm we found
orig_dbm = agilent.state['dbm']

# write out a header for our output file
sys.stdout.write(time.strftime('# %Y%m%d %H:%M:%S HST\n', time.localtime()))
sys.stdout.write('# %s\n'%(sys.argv))
sys.stdout.write('#\n')
sys.stdout.write('#time ')

state_keys = sorted(cart.state)
for key in sorted(cart.state):
    if isinstance(cart.state[key], list):
        state_keys.remove(key)
        state_keys += ['%s_%d'%(key,i) for i in range(len(cart.state[key]))]
    elif not str(cart.state[key]).strip():
        state_keys.remove(key)
    elif len(str(cart.state[key]).split()) > 1:
        state_keys.remove(key)
state_keys.sort()
sys.stdout.write(' '.join(state_keys))

mixers = ['01', '02', '11', '12']
uw = ['U','W'][args.band-6]
dcm_0U = namakanui.util.get_dcms('N%s0U'%(uw))
dcm_0L = namakanui.util.get_dcms('N%s0L'%(uw))
dcm_1U = namakanui.util.get_dcms('N%s1U'%(uw))
dcm_1L = namakanui.util.get_dcms('N%s1L'%(uw))
dcm_0 = dcm_0U + dcm_0L
dcm_1 = dcm_1U + dcm_1L
dcms = dcm_0 + dcm_1
powers = []
powers += ['N%s0U_dcm%d'%(uw,x) for x in dcm_0U]
powers += ['N%s0L_dcm%d'%(uw,x) for x in dcm_0L]
powers += ['N%s1U_dcm%d'%(uw,x) for x in dcm_1U]
powers += ['N%s1L_dcm%d'%(uw,x) for x in dcm_1L]
sys.stdout.write(' ' + ' '.join('hot_p_'+p for p in powers))
sys.stdout.write('\n')
sys.stdout.flush()



def if_setup(adjust):
    # LEVEL_ADJUST 0=setup_only, 1=setup_and_level, 2=level_only
    # BIT_MASK is DCMs to use: bit0=DCM0, bit1=DCM1, ... bit31=DCM31.
    setup_type = ['setup_only', 'setup_and_level', 'level_only']
    logging.info('setup IFTASK, LEVEL_ADJUST %d: %s', adjust, setup_type[adjust])
    bitmask = 0
    for dcm in dcm_0 + dcm_1:
        bitmask |= 1<<dcm
    # TODO configurable IF_FREQ?  will 6 be default for both bands?
    msg = drama.obey('IFTASK@if-micro', 'TEST_SETUP',
                     NASM_SET='R_CABIN', BAND_WIDTH=1000, QUAD_MODE=4,
                     IF_FREQ=6, LEVEL_ADJUST=adjust, BIT_MASK=bitmask).wait(90)
    if msg.reason != drama.REA_COMPLETE or msg.status != 0:
        if msg.status == 261456746:  # ACSISIF__ATTEN_ZERO
            logging.warning('low attenuator setting from IFTASK.TEST_SETUP')
        else:
            logging.error('bad reply from IFTASK.TEST_SETUP: %s', msg)
            return 1
    return 0


def output(powers):
    sys.stdout.write(time.strftime('%Y-%m-%dT%H:%M:%S'))
    for key in state_keys:
        if key not in cart.state:
            key,sep,index = key.rpartition('_')
            index = int(index)
            sys.stdout.write(' %s'%(cart.state[key][index]))
        else:
            sys.stdout.write(' %s'%(cart.state[key]))
    for p in powers:
        sys.stdout.write(' %s'%(p))
    sys.stdout.write('\n')
    sys.stdout.flush()


i = int(-1e300)
prev_powers = []


def loop():
    global i, prev_powers
    while i < 23:
        time.sleep(1)
        i += 1
        if i < 0:
            sys.stderr.write('.')
        else:
            sys.stderr.write('%d '%(i))
        sys.stderr.flush()
        if i % 5 == 4:
            # retune the cart; make sure it loses the lock
            dbm = agilent.state['dbm']
            while dbm > agilent.safe_dbm and not cart.state['pll_unlock']:
                agilent.set_dbm(dbm)
                cart.update_all()
                dbm -= 0.1
            dbm = agilent.safe_dbm
            agilent.set_dbm(dbm)
            agilent.set_output(0)
            time.sleep(0.05)
            agilent.set_output(1)
            agilent.set_dbm(orig_dbm)
            time.sleep(0.05)
            cart.tune(lo_ghz, 0.0)
            time.sleep(0.05)
        transid = drama.obey("IFTASK@if-micro", "WRITE_TP2", FILE="NONE", ITIME=0.1)
        cart.update_all()
        msg = transid.wait(5)
        if msg.reason != drama.REA_COMPLETE or msg.status != 0:
            logging.error('bad reply from IFTASK.WRITE_TP2: %s', msg)
            return
        if cart.state['pll_unlock']:
            logging.error('failed to tune')
            return
        powers = []
        for dcm in dcms:
            powers.append(msg.arg['POWER%d'%(dcm)])
        for j,(prev,curr) in enumerate(zip(prev_powers, powers)):
            pdiff = abs((prev-curr)/min(prev,curr)) * 100.0
            if pdiff > 1.5:
                logging.info('%.2f%% jump in DCM %d', pdiff, dcms[j])
                # let's write to the output file too, might come in handy
                sys.stdout.write('# jump DCM %d, %.2f%%\n'%(dcms[j], pdiff))
                if i < 0:
                    i = 0  # collect a bit more data, then quit
        prev_powers = powers
        output(powers)
    
    

# the rest of this needs to be DRAMA to be able to talk to IFTASK.
def MAIN(msg):
    # TODO obey/kick check
    try:
        if_arg = [1,2][int(args.level_only)]
        if if_setup(if_arg):
            return
        
        loop()
        
    finally:
        # final timestamp
        sys.stdout.write(time.strftime('# %Y%m%d %H:%M:%S HST\n', time.localtime()))
        sys.stdout.flush()
        agilent.set_dbm(agilent.safe_dbm)
        drama.Exit('MAIN done')
    # MAIN
        

try:
    logging.info('drama.init...')
    drama.init(taskname, actions=[MAIN])
    drama.blind_obey(taskname, "MAIN")
    logging.info('drama.run...')
    drama.run()
finally:
    logging.info('drama.stop...')
    drama.stop()
    logging.info('done.')
    





