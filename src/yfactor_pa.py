#!/local/python3/bin/python3
'''
yfactor_pa.py   20190918 RMB

Script to check Y-factor (hot power / cold power) across a PA sweep.
The receiver is tuned to its nominal values, then the PA is varied
from 0 to 2.5.  Since PA is shared between mixers in each polarization
stage, the data is organized by polarization instead of by mixer.

The motivation here is that it's hard to be confident in the relative
y-factors for each PA level when taking IV curves, since the weather
might change significantly between different PAs.

Update 20200221:
With the replacement of mixers 01/02, we're seeing saturated power values
when we level the IF at the nominal bias settings.  So unfortunately
we need to do an initial level, then hunt around for the PA setting
with the highest power value.  Level again, and repeat the process
a few times to be sure that we won't saturate during the PA Y-factor sweep.


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
import logging
import argparse
import namakanui.instrument
import namakanui.util
from namakanui_tune import tune


taskname = 'YFPA_%d'%(os.getpid())

logging.root.setLevel(logging.INFO)
logging.root.addHandler(logging.StreamHandler())

config = namakanui.util.get_config()
bands = namakanui.util.get_bands(config, simulated=False, has_sis_mixers=True)

# use explicit arguments to avoid confusion
parser = argparse.ArgumentParser(description='''
Y-factor across PA sweep, for nominal mV values.
Examples:
  yfactor.py 6 237 > b6_yf_237.ascii
  yfactor.py 7 303 > b7_yf_303.ascii
''',
  formatter_class=argparse.RawTextHelpFormatter)
parser.add_argument('band', type=int, choices=bands)
parser.add_argument('lo_ghz', type=float)
parser.add_argument('lock_side', nargs='?', choices=['below','above'], default='above')
parser.add_argument('--level_only', action='store_true')
parser.add_argument('--pa', nargs='?', default='0.0:2.5:0.01', help='PA range')
args = parser.parse_args()

band = args.band
lo_ghz = args.lo_ghz
lo_range = {6:[219,266], 7:[281,367]}[band]  # TODO get from config
if not lo_range[0] <= lo_ghz <= lo_range[1]:
    logging.error('lo_ghz %g outside %s range for band %d\n'%(lo_ghz, lo_range, band))
    sys.exit(1)

pas = namakanui.util.parse_range(args.pa, maxlen=300)

instrument = namakanui.instrument.Instrument(config)
instrument.set_safe()
instrument.set_band(args.band)
instrument.load.move('b%d_hot'%(args.band))
cart = instrument.carts[band]
cart.power(1)
cart.set_lock_side(args.lock_side)

if not tune(instrument, band, lo_ghz):
    logging.error('failed to tune to %.3f ghz', lo_ghz)
    sys.exit(1)

# save the nominal sis bias voltages
nom_v = cart.state['sis_v']

load = instrument.load  # shorten name

# write out a header for our output file
sys.stdout.write(time.strftime('# %Y%m%d %H:%M:%S HST\n', time.localtime()))
sys.stdout.write('# %s\n'%(sys.argv))
sys.stdout.write('# nom_v: %s\n'%(nom_v))
sys.stdout.write('#\n')
sys.stdout.write('#pa ')
mixers = ['01', '02', '11', '12']
uw = ['U','W'][args.band-6]
dcm_0U = namakanui.util.get_dcms('N%s0U'%(uw))
dcm_0L = namakanui.util.get_dcms('N%s0L'%(uw))
dcm_1U = namakanui.util.get_dcms('N%s1U'%(uw))
dcm_1L = namakanui.util.get_dcms('N%s1L'%(uw))
dcm_0 = dcm_0U + dcm_0L
dcm_1 = dcm_1U + dcm_1L
dcms = dcm_0 + dcm1
powers = []
powers += ['0_dcm%d'%(x) for x in dcm_0]
powers += ['1_dcm%d'%(x) for x in dcm_1]
sys.stdout.write(' ' + ' '.join('ua_avg_'+m for m in mixers))
sys.stdout.write(' ' + ' '.join('ua_dev_'+m for m in mixers))
sys.stdout.write(' ' + ' '.join('hot_p_'+p for p in powers))
sys.stdout.write(' ' + ' '.join('sky_p_'+p for p in powers))
sys.stdout.write(' ' + ' '.join('yf_'+p for p in powers))
sys.stdout.write('\n')
sys.stdout.flush()

# output column starting indices
pa_index = 0
ua_avg_index = 1
ua_dev_index = 5
hot_p_index = 9
sky_p_index = hot_p_index + len(powers)
yf_index = sky_p_index + len(powers)

# number of mixer current readings to take per PA (per load)
# TODO might be able to increase this without impacting runtime due to ITIME,
# but it depends on the actual value of ppcomm_time.
ua_n = 10


def ip(target, rows, pas):
    if target == 'hot':
        p_index = hot_p_index
    else:
        p_index = sky_p_index
    load.move('b%d_%s'%(band,target))
    
    sys.stderr.write('%s: '%(target))
    sys.stderr.flush()

    for i,pa in enumerate(pas):
        if (i+1)%20 == 0:
            sys.stderr.write('%.2f%% '%(100.0*i/len(pas)))
            sys.stderr.flush()
            cart.update_all()

        cart._set_pa([pa,pa])
        rows[i][pa_index] = pa

        # start IFTASK action while we average the mixer current readings
        transid = drama.obey("IFTASK@if-micro", "WRITE_TP2", FILE="NONE", ITIME=0.1)
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
        
        for j,dcm in enumerate(dcm_0+dcm_1):
            rows[i][p_index + j] = msg.arg['POWER%d'%(dcm)]
    
    sys.stderr.write('\n')
    sys.stderr.flush()
    return 0
    # ip


    

def adjust_levels(dup_pas):
    '''look for max power levels across dup_pas for each mixer.
       level at median max PA for 01/02 and 11/12.
       return the 2 max power PAs for further iterations.'''
    # remove dups
    dup_pas = list(set(dup_pas))
    dup_pas.sort()
    rows = [None]*len(dup_pas)
    for i in range(len(rows)):
        rows[i] = [0.0]*(yf_index+len(powers))
    if ip('hot', rows, dup_pas):
        return 0,0  # fail
    max_pa = [0]*16
    max_pow = [-1e300]*16
    for i in range(len(dup_pas)):
        for j in range(16):
            if rows[i][hot_p_index+j] > max_pow[j]:
                max_pow[j] = rows[i][hot_p_index+j]
                max_pa[j] = dup_pas[i]
    logging.info('max power PAs: %s', max_pa)
    p0_pas = max_pa[:8]
    p1_pas = max_pa[8:]
    p0_pas.sort()
    p1_pas.sort()
    cart._set_pa([p0_pas[4],p1_pas[4]])
    if if_setup(2):  # level only
        return 0,0  # fail
    return p0_pas[4],p1_pas[4]

def iter_adjust_levels():
    #coarse_pas = [.1*i*2.5 for i in range(1,11)]
    coarse_pas = [.1*i for i in range(1,26)]
    if len(pas) < len(coarse_pas):
        coarse_pas = pas
    p0,p1 = adjust_levels(coarse_pas)
    if p0==0 and p1==0:
        return 1  # fail
    logging.info('leveled at pa %.2f, %.2f', p0, p1)
    fine_pas_p0 = [p0-.08, p0-.04, p0, p0+.04, p0+.08]
    fine_pas_p1 = [p1-.08, p1-.04, p1, p1+.04, p1+.08]
    p0,p1 = adjust_levels(fine_pas_p0+fine_pas_p1)
    if p0==0 and p1==0:
        return 1
    logging.info('leveled at pa %.2f, %.2f', p0, p1)
    finer_pas_p0 = [p0-.03, p0-.02, p0-.01, p0, p0+.01, p0+.02, p0+.03]
    finer_pas_p1 = [p1-.03, p1-.02, p1-.01, p1, p1+.01, p1+.02, p1+.03]
    p0,p1 = adjust_levels(finer_pas_p0+finer_pas_p1)
    if p0==0 and p1==0:
        return 1
    logging.info('leveled at pa %.2f, %.2f', p0, p1)
    return 0


# the rest of this needs to be DRAMA to be able to talk to IFTASK.
# TODO: could actually publish parameters.  also we need a task name.
def MAIN(msg):
    # TODO obey/kick check
    try:
        if_arg = [1,2][int(args.level_only)]
        namakanui.util.iftask_setup(if_arg, dcms=dcms)
        
        # we want to level close to the max power for each pair of mixers.
        # use a coarse, full 0-2.5 PA sweep, find max power for each DCM.
        # we'll get a set of 4 PAs; do a finer sweep around these.
        # repeat again, then avg PA for 01/02 and 11/12 and do final level.
        if iter_adjust_levels():
            return
            
        # need to save output rows since they have both hot and sky data.
        rows = [None]*len(pas)
        for i in range(len(rows)):
            rows[i] = [0.0]*(yf_index+len(powers))
        
        if ip('hot', rows, pas):
            return
        if ip('sky', rows, pas):
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
    




