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
import logging
import argparse
import namakanui.instrument
import namakanui.util
from namakanui_tune import tune


taskname = 'JTP_%d'%(os.getpid())

namakanui.util.setup_logging()

config = namakanui.util.get_config()
bands = namakanui.util.get_bands(config, simulated=False, has_sis_mixers=True)

# use explicit arguments to avoid confusion
parser = argparse.ArgumentParser(description='''
''',
  formatter_class=argparse.RawTextHelpFormatter)
parser.add_argument('band', type=int, choices=bands)
parser.add_argument('lo_ghz', type=float)
parser.add_argument('lock_side', nargs='?', choices=['below','above'], default='above')
parser.add_argument('--level_only', action='store_true')
args = parser.parse_args()

band = args.band
lo_ghz = args.lo_ghz
lo_range = {6:[219,266], 7:[281,367]}[band]
if not lo_range[0] <= lo_ghz <= lo_range[1]:
    logging.error('lo_ghz %g outside %s range for band %d', lo_ghz, lo_range, band)
    sys.exit(1)

instrument = namakanui.instrument.Instrument(config)
instrument.set_safe()
instrument.set_band(args.band)
instrument.load.move('b%d_hot'%(band))
cart = instrument.carts[band]
cart.power(1)
cart.set_lock_side(args.lock_side)

if not tune(instrument, band, lo_ghz):
    logging.error('failed to tune to %.3f ghz', lo_ghz)
    sys.exit(1)

# save this dbm we found
orig_dbm = instrument.reference.state['dbm']

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

reference = instrument.reference  # shorten name for loop

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
            dbm = reference.state['dbm']
            while dbm > reference.safe_dbm and not cart.state['pll_unlock']:
                reference.set_dbm(dbm)
                cart.update_all()
                dbm -= 0.1
            dbm = reference.safe_dbm
            reference.set_dbm(dbm)
            reference.set_output(0)
            time.sleep(0.05)
            reference.set_output(1)
            reference.set_dbm(orig_dbm)
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
        namakanui.util.iftask_setup(if_arg, 1000, 6, dcms)
        loop()
        
    finally:
        # final timestamp
        sys.stdout.write(time.strftime('# %Y%m%d %H:%M:%S HST\n', time.localtime()))
        sys.stdout.flush()
        instrument.set_safe()
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
    





