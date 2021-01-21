#!/local/python3/bin/python3
'''
yfactor_same.py  20201022 RMB

Simplified version of the yfactor.py script.
I noticed for band 7 that all of the chosen bias voltages
used the same value for both mixers in each polarization block.
This script therefore sweeps all mixers through the same values
simultaneously, and collects data for both mixers at once.

This script also expects only one or two PA values,
and knows to use the first value for P0 and the second for P1.
So this script should run 4x faster than yfactor.py.


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
import namakanui.util
import logging

taskname = 'YF_%d'%(os.getpid())

logging.root.setLevel(logging.INFO)
logging.root.addHandler(logging.StreamHandler())

binpath, datapath = namakanui.util.get_paths()

# use explicit arguments to avoid confusion
parser = argparse.ArgumentParser(description='''
Y-factor across PA/mV sweep.
Examples:
  yfactor.py 6 237 --mv=8.0:9.9:0.05 --pa=1.00:2.50 > b6_yf_237.ascii
  yfactor.py 7 303 --mv=1.2:2.8:0.01 --pa=0.60:0.70 > b7_yf_303.ascii

The range specification for mv and pa is <first>[:last[:step]].

Note for band 6 the upper sideband bias voltage and mixer current is
automatically negated; you will need to manually invert their values
when creating config file tables from this program's output.
''',
  formatter_class=argparse.RawTextHelpFormatter)
parser.add_argument('band', type=int, choices=[6,7])
parser.add_argument('lo_ghz', type=float)
parser.add_argument('--mv')
parser.add_argument('--pa')
parser.add_argument('lock_side', nargs='?', choices=['below','above'], default='above')
parser.add_argument('--level_only', action='store_true')
parser.add_argument('--note', nargs='?', default='', help='note for output file')
args = parser.parse_args()

band = args.band
lo_ghz = args.lo_ghz
lo_range = {6:[219,266], 7:[281,367]}[band]
if not lo_range[0] <= lo_ghz <= lo_range[1]:
    logging.error('lo_ghz %g outside %s range for band %d', lo_ghz, lo_range, band)
    sys.exit(1)
mvs = namakanui.util.parse_range(args.mv, maxlen=30e3, maxstep=0.05)
pas = namakanui.util.parse_range(args.pa, maxlen=300)

if len(pas) > 2:
    logging.error('more than 2 PA values given')
    sys.exit(1)
if len(pas) == 1:
    pas.append(pas[0])

# perform basic setup and get handles
cart, agilent, photonics = namakanui.util.setup_script(args.band, args.lock_side)

# init load controller and set to hot (ambient) load for this band
load = namakanui.load.Load(datapath+'load.ini', time.sleep, namakanui.nop)
load.move('b%d_hot'%(band))

# setup cartridge and tune, adjusting power as needed
if not namakanui.util.tune(cart, agilent, photonics, lo_ghz):
    logging.error('failed to tune to %.3f ghz', lo_ghz)
    sys.exit(1)

# save the nominal sis bias voltages
nom_v = cart.state['sis_v']


# write out a header for our output file
sys.stdout.write(time.strftime('# %Y%m%d %H:%M:%S HST\n', time.localtime()))
sys.stdout.write('# %s\n'%(sys.argv))
sys.stdout.write('#\n')
sys.stdout.write('#mv')
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
powers += ['0U_dcm%d'%(x) for x in dcm_0U]
powers += ['0L_dcm%d'%(x) for x in dcm_0L]
powers += ['1U_dcm%d'%(x) for x in dcm_1U]
powers += ['1L_dcm%d'%(x) for x in dcm_1L]
sys.stdout.write(' ' + ' '.join('ua_avg_'+m for m in mixers))
sys.stdout.write(' ' + ' '.join('ua_dev_'+m for m in mixers))
sys.stdout.write(' ' + ' '.join('hot_p_'+p for p in powers))
sys.stdout.write(' ' + ' '.join('sky_p_'+p for p in powers))
sys.stdout.write(' ' + ' '.join('yf_'+p for p in powers))
sys.stdout.write('\n')
sys.stdout.flush()

# output column starting indices
mv_index = 0
ua_avg_index = 1
ua_dev_index = 5
hot_p_index = 9
sky_p_index = hot_p_index + len(powers)
yf_index = sky_p_index + len(powers)

# number of mixer current readings to take per bias voltage (per load)
# TODO might be able to increase this without impacting runtime due to ITIME,
# but it depends on the actual value of ppcomm_time.
ua_n = 10


def iv(target, rows):
    if target == 'hot':
        p_index = hot_p_index
    else:
        p_index = sky_p_index
    load.move('b%d_%s'%(band,target))
    
    if target == 'hot':
        cart.tune(lo_ghz, 0.0, skip_servo_pa=True)
        cart._set_pa([pas[0],pas[1]])
        cart.update_all()
        if namakanui.util.iftask_setup(2, 1000, 6, dcms):  # level only
            return 1
    
    sys.stderr.write('%s: '%(target))
    sys.stderr.flush()
    
    mult = 1.0
    if band == 6:
        mult = -1.0
    cart._ramp_sis_bias_voltages([mult*mvs[0], mvs[0], mult*mvs[0], mvs[0]])
    for i,mv in enumerate(mvs):
        if (i+1) % 20 == 0:
            sys.stderr.write('%.2f%% '%(0.0 + 50*i/len(mvs)))
            sys.stderr.flush()
            cart.update_all()  # for anyone monitoring
        for po in range(2):
            cart.femc.set_sis_voltage(cart.ca, po, 0, mult*mv)
            cart.femc.set_sis_voltage(cart.ca, po, 1, mv)
        rows[i][mv_index] = mv
        # start IFTASK action while we average the mixer current readings
        transid = drama.obey("IFTASK@if-micro", "WRITE_TP2", FILE="NONE", ITIME=0.1)
        # TODO: separate hot/cold mixer currents, or only calc hot
        for j in range(ua_n):
            for po in range(2):
                for sb in range(2):
                    ua = cart.femc.get_sis_current(cart.ca,po,sb)*1e3
                    rows[i][ua_avg_index + po*2 + sb] += abs(ua)  # for band 6
                    rows[i][ua_dev_index + po*2 + sb] += ua*ua
        # get IFTASK reply
        msg = transid.wait(5)
        if msg.reason != drama.REA_COMPLETE or msg.status != 0:
            logging.error('bad reply from IFTASK.WRITE_TP2: %s', msg)
            return 1
        for j,dcm in enumerate(dcms):
            rows[i][p_index + j] = msg.arg['POWER%d'%(dcm)]
    
    sys.stderr.write('\n')
    sys.stderr.flush()
    return 0
    # iv



# the rest of this needs to be DRAMA to be able to talk to IFTASK.
# TODO: could actually publish parameters.  also we need a task name.
def MAIN(msg):
    # TODO obey/kick check
    try:
        if_arg = [1,2][int(args.level_only)]
        if namakanui.util.iftask_setup(if_arg, 1000, 6, dcms):
            return
            
        # need to save output rows since they have both hot and sky data.
        rows = [None]*len(mvs)
        for i in range(len(rows)):
            rows[i] = [0.0]*(yf_index+len(powers))
        
        if iv('hot', rows):
            return
        if iv('sky', rows):
            return
        
        n = ua_n*2
        for r in rows:
            for j in range(4):
                # calculate mixer current avg/dev.
                # iv just saves sum(x) and sum(x^2);
                # remember stddev is sqrt(E(x^2) - E(x)^2)
                avg = r[ua_avg_index + j] / n
                dev = (r[ua_dev_index + j]/n - avg**2)**.5
                r[ua_avg_index + j] = avg
                r[ua_dev_index + j] = dev
            
            for j in range(len(powers)):
                # calculate y-factors
                r[yf_index + j] = r[hot_p_index + j] / r[sky_p_index + j]
                
            # write out the data
            sys.stdout.write(' '.join('%g'%x for x in r) + '\n')
            sys.stdout.flush()
    finally:
        # final timestamp
        sys.stdout.write(time.strftime('# %Y%m%d %H:%M:%S HST\n', time.localtime()))
        sys.stdout.flush()
        
        # retune the receiver to get settings back to nominal
        cart.tune(lo_ghz, 0.0)
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
    




