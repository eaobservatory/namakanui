#!/local/python3/bin/python3
'''
dcm_att.py    20201008 RMB

Tune to a range of frequencies and check the DCM attenuator level at each.
Sometimes the attenuators are left at zero, especially in 250 MHz bandwidth,
which is an error in the most recent version of acsisIf.


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
import argparse
import logging
import namakanui.cart
import namakanui.load
import namakanui.util as util


taskname = 'DCMA_%d'%(os.getpid())

logging.root.setLevel(logging.INFO)
logging.root.addHandler(logging.StreamHandler())

binpath, datapath = util.get_paths()

# use explicit arguments to avoid confusion
parser = argparse.ArgumentParser(description='''
DCM attenuation for a range of frequencies.
''',
  formatter_class=argparse.RawTextHelpFormatter)
parser.add_argument('band', type=int, choices=[6,7])
parser.add_argument('lo_ghz', help='LO GHz range, first:last:step')
parser.add_argument('--lock_side', nargs='?', choices=['below','above'], default='above')
parser.add_argument('--level_only', action='store_true')
parser.add_argument('--bw_mhz', nargs='?', default='1000', help='BW MHz range, first:last:step')
parser.add_argument('--if_ghz', nargs='?', default='6', help='IF GHz range, first:last:step')
args = parser.parse_args()

band = args.band
los = util.parse_range(args.lo_ghz, maxlen=100e3)
bws = util.parse_range(args.bw_mhz, maxlen=1e3)
ifs = util.parse_range(args.if_ghz, maxlen=1e3)

# perform basic setup and get handles
cart, agilent, photonics = util.setup_script(args.band, args.lock_side)

# init load controller and set to hot (ambient) load for this band
load = namakanui.load.Load(datapath+'load.ini', time.sleep, namakanui.nop)
load.move('b%d_hot'%(band))

# tune to a central frequency just for the sake of the first IFTASK setup
lo_ghz = los[len(los)//2]
if not util.tune(cart, agilent, photonics, lo_ghz):
    logging.error('failed to tune to %.3f ghz', lo_ghz)
    sys.exit(1)


# write out a header for our output file
sys.stdout.write(time.strftime('# %Y%m%d %H:%M:%S HST\n', time.localtime()))
sys.stdout.write('# %s\n'%(sys.argv))
sys.stdout.write('#\n')
sys.stdout.write('#lo_ghz if_ghz bw_mhz')
mixers = ['01', '02', '11', '12']
uw = ['U','W'][args.band-6]  # UU or AWEOWEO
dcm_0U = util.get_dcms('N%s0U'%(uw))
dcm_0L = util.get_dcms('N%s0L'%(uw))
dcm_1U = util.get_dcms('N%s1U'%(uw))
dcm_1L = util.get_dcms('N%s1L'%(uw))
dcms = dcm_0U + dcm_0L + dcm_1U + dcm_1L
powers = []
powers += ['0U_dcm%d'%(x) for x in dcm_0U]
powers += ['0L_dcm%d'%(x) for x in dcm_0L]
powers += ['1U_dcm%d'%(x) for x in dcm_1U]
powers += ['1L_dcm%d'%(x) for x in dcm_1L]
sys.stdout.write(' ' + ' '.join('att_'+p for p in powers))
sys.stdout.write(' ' + ' '.join('hot_p_'+p for p in powers))
sys.stdout.write('\n')
sys.stdout.flush()

# output column starting indices
pa_index = 0
att_index = 3
hot_p_index = att_index + len(powers)


def main_loop():
    for bw_mhz in bws:
        if util.iftask_set_bw(bw_mhz):
            return
        
        for if_ghz in ifs:
            lo2_mhz = if_ghz*1e3 + 2500
            if bw_mhz == 250:
                lo2_mhz += 125
            if util.iftask_set_lo2(lo2_mhz):
                return
            
            for lo_ghz in los:
                
                if not util.tune(cart, agilent, photonics, lo_ghz):
                    logging.error('failed to tune to %.3f ghz', lo_ghz)
                    continue
                # level only (won't actually set bw/lo2)
                if util.iftask_setup(2, bw_mhz, if_ghz, dcms):
                    return
                att = util.iftask_get_att(dcms)
                if not att:
                    return
                hotp = util.iftask_get_tp2(dcms)
                if not hotp:
                    return
                # collect values into a row
                r = [0.0]*(hot_p_index + len(powers))
                r[0] = lo_ghz
                r[1] = if_ghz
                r[2] = bw_mhz
                for j in range(len(powers)):
                    r[att_index + j] = att[j]
                    r[hot_p_index + j] = hotp[j]
                # write out the row
                sys.stdout.write(' '.join('%g'%x for x in r) + '\n')
                sys.stdout.flush()
    # main_loop


# the rest of this needs to be DRAMA to be able to talk to IFTASK.
def MAIN(msg):
    try:
        adjust = [1,2][int(args.level_only)]
        if util.iftask_setup(adjust, bws[0], ifs[0], dcms):
            return
        main_loop()
    finally:
        # final timestamp
        sys.stdout.write(time.strftime('# %Y%m%d %H:%M:%S HST\n', time.localtime()))
        sys.stdout.flush()
        # retune the receiver to get settings back to nominal
        util.tune(cart, agilent, photonics, lo_ghz)
        drama.Exit('MAIN done')
    # MAIN
        

try:
    logging.info('drama.init...')
    drama.init(taskname,
               tidefile = datapath+'namakanui.tide',
               buffers = [64000, 8000, 8000, 2000],
               actions=[MAIN])
    drama.blind_obey(taskname, "MAIN")
    logging.info('drama.run...')
    drama.run()
finally:
    logging.info('drama.stop...')
    drama.stop()
    logging.info('done.')
    




