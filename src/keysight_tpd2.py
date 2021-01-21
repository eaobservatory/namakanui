#!/local/python3/bin/python3
'''
keysight_tpd2.py    20200629 RMB
Test how TPD2 varies with Keysight output power.  It shouldn't!


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
import namakanui.util as util
import logging

taskname = 'KST_%d'%(os.getpid())

logging.root.setLevel(logging.INFO)
logging.root.addHandler(logging.StreamHandler())

binpath, datapath = util.get_paths()

# use explicit arguments to avoid confusion
parser = argparse.ArgumentParser(description='''
''',
  formatter_class=argparse.RawTextHelpFormatter)
parser.add_argument('band', type=int, choices=[6,7])
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

# perform basic setup and get handles
cart, agilent, photonics = util.setup_script(args.band, args.lock_side)

# init load controller and set to hot (ambient) load for this band
load = namakanui.load.Load(datapath+'load.ini', time.sleep, namakanui.nop)
load.move('b%d_hot'%(band))

# tune cartridge, adjusting power as needed
if not util.tune(cart, agilent, photonics, lo_ghz):
    logging.error('failed to tune to %.3f ghz', lo_ghz)
    sys.exit(1)

# determine dbm limits
dbm = agilent.state['dbm']
orig_dbm = dbm
while dbm < agilent.max_dbm and cart.state['pll_if_power'] > -2.5 and not cart.state['pll_unlock']:
    dbm += 0.1
    agilent.set_dbm(dbm)
    time.sleep(0.05)
    cart.update_all()
    logging.info('+ dbm %.2f, pll_if %.3f', dbm, cart.state['pll_if_power'])
dbm = agilent.state['dbm']
hi_dbm = dbm
while dbm > agilent.safe_dbm and cart.state['pll_if_power'] < -0.5 and not cart.state['pll_unlock']:
    dbm -= 0.1
    agilent.set_dbm(dbm)
    time.sleep(0.05)
    cart.update_all()
    logging.info('- dbm %.2f, pll_if %.3f', dbm, cart.state['pll_if_power'])
lo_dbm = dbm + 0.2
logging.info('dbm limits: [%.2f, %.2f]', lo_dbm, hi_dbm)
if lo_dbm >= hi_dbm:
    logging.error('bad dbm limits, bailing out.')
    agilent.set_dbm(agilent.safe_dbm)
    photonics.set_attenuation(photonics.max_att) if photonics else None
    sys.exit(1)

# relock the receiver
dbm = orig_dbm
agilent.set_dbm(dbm)
time.sleep(0.05)
cart.tune(lo_ghz, 0.0)
cart.update_all()
if cart.state['pll_unlock']:
    logging.error('failed to retune')
    agilent.set_dbm(agilent.safe_dbm)
    photonics.set_attenuation(photonics.max_att) if photonics else None
    sys.exit(1)

# write out a header for our output file
sys.stdout.write(time.strftime('# %Y%m%d %H:%M:%S HST\n', time.localtime()))
sys.stdout.write('# %s\n'%(sys.argv))
sys.stdout.write('#\n')
sys.stdout.write('#dbm pll_if_power')
mixers = ['01', '02', '11', '12']
uw = ['U','W'][args.band-6]
dcm_0U = util.get_dcms('N%s0U'%(uw))
dcm_0L = util.get_dcms('N%s0L'%(uw))
dcm_1U = util.get_dcms('N%s1U'%(uw))
dcm_1L = util.get_dcms('N%s1L'%(uw))
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

# output column starting indices
dbm_index = 0
hot_p_index = 2


def print_dbm(i, dbm):
    #logging.info('%d dbm %.2f', i, dbm)
    transid = drama.obey("IFTASK@if-micro", "WRITE_TP2", FILE="NONE", ITIME=0.1)
    cart.update_all()
    logging.info('%d dbm %.2f, pll_if %.3f', i, dbm, cart.state['pll_if_power'])
    msg = transid.wait(5)
    if msg.reason != drama.REA_COMPLETE or msg.status != 0:
        logging.error('bad reply from IFTASK.WRITE_TP2: %s', msg)
        return False
    if cart.state['pll_unlock']:
        return False
    sys.stdout.write('%.2f %.3f'%(dbm, cart.state['pll_if_power']))
    for dcm in dcms:
            sys.stdout.write(' %.3f'%(msg.arg['POWER%d'%(dcm)]))
    sys.stdout.write('\n')
    sys.stdout.flush()
    return True
    

def dbm_sweep():
    # take a random sample of 300 points in case of drift
    global dbm
    i = 0
    random.seed()
    while i < 300 and print_dbm(i, dbm):
        i += 1
        dbm = random.uniform(lo_dbm, hi_dbm)
        agilent.set_dbm(dbm)
    

# the rest of this needs to be DRAMA to be able to talk to IFTASK.
def MAIN(msg):
    # TODO obey/kick check
    try:
        if_arg = [1,2][int(args.level_only)]
        if util.iftask_setup(if_arg, 1000, 6, dcms):
            return
        
        dbm_sweep()
        
    finally:
        # final timestamp
        sys.stdout.write(time.strftime('# %Y%m%d %H:%M:%S HST\n', time.localtime()))
        sys.stdout.flush()
        agilent.set_dbm(agilent.safe_dbm)
        photonics.set_attenuation(photonics.max_att) if photonics else None
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
    





