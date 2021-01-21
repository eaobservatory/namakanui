#!/local/python3/bin/python3
'''
retune_tpd2.py  20200713 RMB

Test ACSIS TPD2 against small-scale retunings, as might occur
during a typical doppler-tracking observation.


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

taskname = 'RTPD_%d'%(os.getpid())

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
parser.add_argument('--off_ghz', nargs='?', type=float, default=0.01)
parser.add_argument('--iters', nargs='?', type=int, default=200)
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

# setup cartridge and tune, adjusting power as needed
if not util.tune(cart, agilent, photonics, lo_ghz):
    logging.error('failed to tune to %.3f ghz', lo_ghz)
    sys.exit(1)

# write out a header for our output file
sys.stdout.write(time.strftime('# %Y%m%d %H:%M:%S HST\n', time.localtime()))
sys.stdout.write('# %s\n'%(sys.argv))
sys.stdout.write('#\n')
sys.stdout.write('#lo_ghz lock_only ')

# debug, this should exist
#sys.stderr.write('sis_v_s: %s'%(repr(cart.state['sis_v_s'])))
#sys.stderr.flush()

state_keys = sorted(cart.state)
for key in sorted(cart.state):
    if isinstance(cart.state[key], (list,tuple)):
        state_keys.remove(key)
        state_keys += ['%s_%d'%(key,i) for i in range(len(cart.state[key]))]
    elif not str(cart.state[key]).strip():
        state_keys.remove(key)
    elif len(str(cart.state[key]).split()) > 1:
        state_keys.remove(key)
state_keys.sort()
state_keys.remove('lo_ghz')
sys.stdout.write(' '.join(state_keys))

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



def main_loop():
    random.seed()
    lock_only = 1
    sys.stderr.write('starting %d iters\n'%(args.iters))
    sys.stderr.flush()
    for i in range(args.iters):
        sys.stderr.write('%d '%(i))
        sys.stderr.flush()
        if i == args.iters//2:
            lock_only = 0
            sys.stderr.write('\nhalfway\n')
            sys.stderr.flush()
        lo_ghz = random.uniform(args.lo_ghz - args.off_ghz, args.lo_ghz + args.off_ghz)
        if not util.tune(cart, agilent, photonics, lo_ghz, lock_only=lock_only):
            logging.error('failed to tune to %.6f ghz', lo_ghz)
            return
        transid = drama.obey("IFTASK@if-micro", "WRITE_TP2", FILE="NONE", ITIME=0.1)
        cart.update_all()
        msg = transid.wait(5)
        if msg.reason != drama.REA_COMPLETE or msg.status != 0:
            logging.error('bad reply from IFTASK.WRITE_TP2: %s', msg)
            return
        if cart.state['pll_unlock']:
            logging.error('lost lock at %.6f GHz', lo_ghz)
            return
        sys.stdout.write('%.6f %d'%(lo_ghz, lock_only))
        for key in state_keys:
            if key not in cart.state:
                key,sep,index = key.rpartition('_')
                index = int(index)
                sys.stdout.write(' %s'%(cart.state[key][index]))
            else:
                sys.stdout.write(' %s'%(cart.state[key]))
        for dcm in dcms:
            sys.stdout.write(' %.5f'%(msg.arg['POWER%d'%(dcm)]))
        sys.stdout.write('\n')
        sys.stdout.flush()


# the rest of this needs to be DRAMA to be able to talk to IFTASK.
def MAIN(msg):
    # TODO obey/kick check
    try:
        if_arg = [1,2][int(args.level_only)]
        if util.iftask_setup(if_arg, 1000, 6, dcms):
            return
        
        main_loop()
        
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
    





