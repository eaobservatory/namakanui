#!/local/python3/bin/python3
'''
yfactor.py  20190918 RMB

Script to check Y-factor (hot power / cold power) across a mixer IV sweep.
This is a 2D optimization problem between the mixer bias voltage setting
and the PA drain voltage (which adjusts LO pumping power / mixer current).
So for each row in the output data we save the following columns:
    PA setting x1, same for both POLs
    bias voltage x1, same for all mixers
    mixer current avg x4
    mixer current dev x4
    amb power x16
    sky power x16
    y-factor x16

Keeping the PA drain voltage the same for both polarizations is mainly
for the sake of simplifying this program so we only have two dimensions
to sweep through.

IMPORTANT:
Since we plan to use the sky as a cold load, it's important that conditions
remain stable across each IV sweep.  To keep the sweep time short,
for band 6 we invert the signs of the bias voltage and mixer current
for the upper sideband mixers.  Therefore this program will only accept
positive ranges as input parameters, and you will need to manually
negate the output data's voltage/current for mixers 01 and 11.

Examples:
  yfactor.py 6 237 --mv=8.0:9.9:0.05 --pa=1.0:2.5:0.1 > b6_yf_237.ascii
  yfactor.py 7 303 --mv=1.5:3.0:0.05 --pa=0.3:0.9:0.1 > b7_yf_303.ascii

The range specification for mv and pa is <first>[:last[:step]].


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
import sys
import os
import time
import logging
import argparse
import namakanui.instrument
import namakanui.util
from namakanui_tune import tune


taskname = 'YF_%d'%(os.getpid())

namakanui.util.setup_logging()

config = namakanui.util.get_config()
bands = namakanui.util.get_bands(config, simulated=False, has_sis_mixers=True)

parser = argparse.ArgumentParser(
    formatter_class=argparse.RawTextHelpFormatter,
    description=namakanui.util.get_description(__doc__)
    )
parser.add_argument('band', type=int, choices=bands)
parser.add_argument('lo_ghz', type=float)
parser.add_argument('--mv')
parser.add_argument('--pa')
parser.add_argument('lock_side', nargs='?', choices=['below','above'], default='above')
parser.add_argument('--zero', action='store_true', help='zero bias voltage of unused mixer instead of leaving at nominal value')
args = parser.parse_args()

band = args.band
lo_ghz = args.lo_ghz
lo_range = {6:[219,266], 7:[281,367]}[band]  # TODO get from config
if not lo_range[0] <= lo_ghz <= lo_range[1]:
    logging.error('lo_ghz %g outside %s range for band %d', lo_ghz, lo_range, band)
    sys.exit(1)
mvs = namakanui.util.parse_range(args.mv, maxlen=30e3, maxstep=0.05)
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

pmeters = namakanui.util.init_rfsma_pmeters_49()

# write out a header for our output file
sys.stdout.write(time.strftime('# %Y%m%d %H:%M:%S HST\n', time.localtime()))
sys.stdout.write('# %s\n'%(sys.argv))
sys.stdout.write('#\n')
sys.stdout.write('#pa mv')
mixers = ['01', '02', '11', '12']
powers = []
#powers += ['B%d_U0'%(band)]
#powers += ['B%d_U1'%(band)]
#powers += ['B%d_L0'%(band)]
#powers += ['B%d_L1'%(band)]
# put powers in order by mixer instead of normal usb/lsb order;
# these are doubled since we read out each mixer in a block individually.
powers += ['01_B%d_U0'%(band)]
powers += ['01_B%d_L0'%(band)]
powers += ['02_B%d_U0'%(band)]
powers += ['02_B%d_L0'%(band)]
powers += ['11_B%d_U1'%(band)]
powers += ['11_B%d_L1'%(band)]
powers += ['12_B%d_U1'%(band)]
powers += ['12_B%d_L1'%(band)]
sys.stdout.write(' ' + ' '.join('ua_avg_'+m for m in mixers))
sys.stdout.write(' ' + ' '.join('ua_dev_'+m for m in mixers))
sys.stdout.write(' ' + ' '.join('hot_mw_'+p for p in powers))
sys.stdout.write(' ' + ' '.join('sky_mw_'+p for p in powers))
sys.stdout.write(' ' + ' '.join('yf_'+p for p in powers))
sys.stdout.write('\n')
sys.stdout.flush()

# output column starting indices
pa_index = 0
mv_index = 1
ua_avg_index = 2
ua_dev_index = 6
hot_p_index = 10
sky_p_index = hot_p_index + len(powers)
yf_index = sky_p_index + len(powers)

# number of mixer current readings to take per bias voltage (per load)
# TODO might be able to increase this without impacting runtime due to ITIME,
# but it depends on the actual value of ppcomm_time.
ua_n = 10


def iv(target, rows, pa):
    if target == 'hot':
        p_index = hot_p_index
    else:
        p_index = sky_p_index
    load.move('b%d_%s'%(band,target))
    
    # TODO Maybe it's wrong to relevel for each PA; it makes it harder
    # to compare power between PAs if the leveling is slightly different.
    # Ambient temperature shouldn't be changing much compared to the
    # difference between hot load and sky, either.
    
    # at the start of a HOT row, re-tune and re-level the power meters
    # at the nominal values.  do not relevel on SKY or y-factor won't work.
    # actually re-leveling makes it difficult to compare power levels
    # across sweeps, so skip it.  retuning is fine though.
    # 20200221 but ACTUALLY we're having problems with saturating power levels,
    # so DO relevel the detectors here.  we won't be able to see
    # relative power levels, but we mostly only do 2 PAs these days and care
    # more about Y-factor values anyway.
    if target == 'hot':
        cart.tune(lo_ghz, 0.0, skip_servo_pa=True)
        cart._set_pa([pa,pa])
        cart.update_all()
    
    sys.stderr.write('%s: '%(target))
    sys.stderr.flush()
    
    # NOTE: The two SIS mixers in each polarization module are not really USB and LSB.
    # Rather the input to one is phase-shifted relative to the other, and their 
    # signals are then combined to produce USB and LSB outputs.  So to check the
    # power output and Y-factor from each mixer individually, the other one needs
    # to have its output disabled by setting its bias voltage to zero.
    # Since we still need to smoothly ramp SIS bias voltage for large changes,
    # we therefore do two separate loops for sis1 and sis2.
    
    # TODO: Once we have the mixers optimized individually, we might still need
    # to optimize their combined outputs.  This will require a 2D scan of
    # mixer bias voltage for each PA setting.
    
    # sis1, mixers 01, 11
    sb = 0
    mult = 1.0
    if band == 6:
        mult = -1.0
    if args.zero:
        cart._ramp_sis_bias_voltages([mult*mvs[0], 0.0, mult*mvs[0], 0.0])
    else:
        cart._ramp_sis_bias_voltages([mult*mvs[0], nom_v[1], mult*mvs[0], nom_v[3]])
    for i,mv in enumerate(mvs):
        if (i+1) % 20 == 0:
            sys.stderr.write('%.2f%% '%(0.0 + 50*i/len(mvs)))
            sys.stderr.flush()
            cart.update_all()  # for anyone monitoring
        for po in range(2):
            cart.femc.set_sis_voltage(cart.ca, po, sb, mult*mv)
        rows[i][mv_index] = mv
        # start pmeter reads
        for m in pmeters:
            m.read_init()
        for j in range(ua_n):
            for po in range(2):
                ua = cart.femc.get_sis_current(cart.ca,po,sb)*1e3
                rows[i][ua_avg_index + po*2 + sb] += abs(ua)  # for band 6
                rows[i][ua_dev_index + po*2 + sb] += ua*ua
        # fetch pmeter results and convert to mW
        dbm = [p for m in pmeters for p in m.read_fetch()]
        mw = [10.0**(0.1*p) for p in dbm]
        rows[i][p_index+0] = mw[0]  # 01, P0U
        rows[i][p_index+1] = mw[2]  # 01, P0L
        rows[i][p_index+4] = mw[1]  # 11, P1U
        rows[i][p_index+5] = mw[3]  # 11, P1L
    
    # sis2, mixers 02, 12
    sb = 1
    if args.zero:
        cart._ramp_sis_bias_voltages([0.0, mvs[0], 0.0, mvs[0]])
    else:
        cart._ramp_sis_bias_voltages([nom_v[0], mvs[0], nom_v[2], mvs[0]])
    for i,mv in enumerate(mvs):
        if (i+1) % 20 == 0:
            sys.stderr.write('%.2f%% '%(50.0 + 50*i/len(mvs)))
            sys.stderr.flush()
            cart.update_all()  # for anyone monitoring
        for po in range(2):
            cart.femc.set_sis_voltage(cart.ca, po, sb, mv)
        rows[i][mv_index] = mv
        # start pmeter reads
        for m in pmeters:
            m.read_init()
        for j in range(ua_n):
            for po in range(2):
                ua = cart.femc.get_sis_current(cart.ca,po,sb)*1e3
                rows[i][ua_avg_index + po*2 + sb] += ua
                rows[i][ua_dev_index + po*2 + sb] += ua*ua
        # fetch pmeter results and convert to mW
        dbm = [p for m in pmeters for p in m.read_fetch()]
        mw = [10.0**(0.1*p) for p in dbm]
        rows[i][p_index+2] = mw[0]  # 02, P0U
        rows[i][p_index+3] = mw[2]  # 02, P0L
        rows[i][p_index+6] = mw[1]  # 12, P1U
        rows[i][p_index+7] = mw[3]  # 12, P1L
    
    sys.stderr.write('\n')
    sys.stderr.flush()
    return 0
    # iv



try:
    
    for k,pa in enumerate(pas):
        logging.info('========= PA: %g (%.2f%%) =========', pa, 100*k/len(pas))
        #cart._set_pa([pa,pa])  since iv retunes we do this there
        
        # need to save output rows since they have both hot and sky data.
        rows = [None]*len(mvs)
        for i in range(len(rows)):
            rows[i] = [0.0]*(yf_index+len(powers))
            rows[i][pa_index] = pa
        
        if iv('hot', rows, pa):
            break
        if iv('sky', rows, pa):
            break
        
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
    logging.info('done')

