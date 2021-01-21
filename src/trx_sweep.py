#!/local/python3/bin/python3
'''
trx_sweep.py    20200812 RMB

Tune to a range of frequencies and calculate Trx at each one.
Unfortunately this script will spend most of its time just moving
the load around, but, given the potential power difference across
the range and thus the need to relevel ACSIS at each frequency,
I don't think there's a faster way to do it.

NOTE: TEST_SETUP action in IFTASK is inadequate.
      Must setup to set bandwidth and IF frequency,
      only handles 4/5/6 GHz IF,
      and doesn't set LO2s right for 250 MHz bandwidth.
      Hence we use extra DCM/LO2 commands to the IFTASK.



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
import namakanui.cart
import namakanui.agilent
import namakanui.ifswitch
import namakanui.load
import namakanui.femc
import namakanui.util as util
import logging

taskname = 'TRXS_%d'%(os.getpid())

logging.root.setLevel(logging.INFO)
logging.root.addHandler(logging.StreamHandler())

binpath, datapath = util.get_paths()

# use explicit arguments to avoid confusion
parser = argparse.ArgumentParser(description='''
Trx for a range of frequencies.
''',
  formatter_class=argparse.RawTextHelpFormatter)
parser.add_argument('band', type=int, choices=[6,7])
parser.add_argument('lo_ghz', help='LO GHz range, first:last:step')
parser.add_argument('lock_side', nargs='?', choices=['below','above'], default='above')
parser.add_argument('--level_only', action='store_true')
parser.add_argument('--bw_mhz', nargs='?', default='1000', help='BW MHz range, first:last:step')
parser.add_argument('--if_ghz', nargs='?', default='6', help='IF GHz range, first:last:step')
parser.add_argument('--note', nargs='?', default='', help='note for output file')
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

# a guess for LN2 brightness temp.  TODO might be frequency-dependent.
coldk = 80.0

# write out a header for our output file
sys.stdout.write(time.strftime('# %Y%m%d %H:%M:%S HST\n', time.localtime()))
sys.stdout.write('# %s\n'%(sys.argv))
sys.stdout.write('# coldk = %.3f\n'%(coldk))
sys.stdout.write('# NOTE ua values are actually abs(ua)\n')
sys.stdout.write('#\n')
sys.stdout.write('#lo_ghz if_ghz bw_mhz pa0 pa1 hotk')
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
sys.stdout.write(' ' + ' '.join('ua_avg_'+m for m in mixers))
sys.stdout.write(' ' + ' '.join('ua_dev_'+m for m in mixers))
sys.stdout.write(' ' + ' '.join('hot_p_'+p for p in powers))
sys.stdout.write(' ' + ' '.join('sky_p_'+p for p in powers))
sys.stdout.write(' ' + ' '.join('trx_'+p for p in powers))
sys.stdout.write('\n')
sys.stdout.flush()

# output column starting indices
pa_index = 0
ua_avg_index = 6
ua_dev_index = 10
hot_p_index = 14
sky_p_index = hot_p_index + len(powers)
trx_index = sky_p_index + len(powers)

# number of mixer current readings to take per PA (per load)
# TODO might be able to increase this without impacting runtime due to ITIME,
# but it depends on the actual value of ppcomm_time.
ua_n = 10


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
                ua_avg = [0.0]*4
                ua_dev = [0.0]*4
                hotp = [0.0]*len(dcms)
                coldp = [0.0]*len(dcms)
                
                # HOT
                load.move('b%d_hot'%(band))
                if not util.tune(cart, agilent, photonics, lo_ghz):
                    logging.error('failed to tune to %.3f ghz', lo_ghz)
                    continue
                # level only (won't actually set bw/lo2)
                if util.iftask_setup(2, bw_mhz, if_ghz, dcms):  
                    return
                # start IFTASK action
                transid = drama.obey("IFTASK@if-micro", "WRITE_TP2", FILE="NONE", ITIME=0.1)
                # collect mixer current readings
                for j in range(ua_n):
                    for po in range(2):
                        for sb in range(2):
                            ua = cart.femc.get_sis_current(cart.ca,po,sb)*1e3
                            ua_avg[po*2 + sb] += abs(ua)  # for band 6
                            ua_dev[po*2 + sb] += ua*ua
                # get hot load temperature
                hotk = drama.get_param('LAKESHORE')['temp5']
                # get IFTASK reply
                msg = transid.wait(5)
                if msg.reason != drama.REA_COMPLETE or msg.status != 0:
                    logging.error('bad reply from IFTASK.WRITE_TP2: %s', msg)
                    return 1
                for j,dcm in enumerate(dcms):
                    hotp[j] = msg.arg['POWER%d'%(dcm)]
                
                # COLD
                load.move('b%d_sky'%(band))
                # start IFTASK action
                transid = drama.obey("IFTASK@if-micro", "WRITE_TP2", FILE="NONE", ITIME=0.1)
                # collect mixer current readings
                for j in range(ua_n):
                    for po in range(2):
                        for sb in range(2):
                            ua = cart.femc.get_sis_current(cart.ca,po,sb)*1e3
                            ua_avg[po*2 + sb] += abs(ua)  # for band 6
                            ua_dev[po*2 + sb] += ua*ua
                # get IFTASK reply
                msg = transid.wait(5)
                if msg.reason != drama.REA_COMPLETE or msg.status != 0:
                    logging.error('bad reply from IFTASK.WRITE_TP2: %s', msg)
                    return 1
                for j,dcm in enumerate(dcms):
                    coldp[j] = msg.arg['POWER%d'%(dcm)]
                
                # collect values into a row
                pa_drain_s = cart.state['pa_drain_s']
                r = [0.0]*(trx_index+len(powers))
                r[0] = lo_ghz
                r[1] = if_ghz
                r[2] = bw_mhz
                r[3] = pa_drain_s[0]
                r[4] = pa_drain_s[1]
                r[5] = hotk
                n = ua_n*2
                for j in range(4):
                    # calculate mixer current avg/dev.
                    # iv just saves sum(x) and sum(x^2);
                    # remember stddev is sqrt(E(x^2) - E(x)^2)
                    avg = ua_avg[j] / n
                    dev = (ua_dev[j]/n - avg**2)**.5
                    r[ua_avg_index + j] = avg
                    r[ua_dev_index + j] = dev
                for j in range(len(powers)):
                    # calc Trx.
                    r[hot_p_index + j] = hotp[j]
                    r[sky_p_index + j] = coldp[j]
                    y = hotp[j]/coldp[j]
                    r[trx_index + j] = y*(hotk - coldk)/(y-1) - hotk
                        
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
    




