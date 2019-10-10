#!/local/python3/bin/python3
'''
20190918 RMB

Script to check Y-factor (hot power / cold power) across a PA sweep.
The receiver is tuned to its nominal values, then the PA is varied
from 0 to 2.5.  Since PA is shared between mixers in each polarization
stage, the data is organized by polarization instead of by mixer.

The motivation here is that it's hard to be confident in the relative
y-factors for each PA level when taking IV curves, since the weather
might change significantly between different PAs.

We expect this script to work pretty well for mixers 11/12, but
with mixers 01/02 it might not be very useful.  Mixers 11/12 keep
the same (approximately) optimum bias voltage for different PA
levels, whereas mixer 01 has a strong PA dependency, and the
noisy part of the curve moves around as well.

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
import logging

taskname = 'YF_%d'%(os.getpid())

logging.root.setLevel(logging.INFO)
logging.root.addHandler(logging.StreamHandler())

binpath = os.path.dirname(os.path.realpath(sys.argv[0])) + '/'
# HACK, should crawl up
if 'install' in binpath:
    datapath = os.path.realpath(binpath + '../../data') + '/'
else:
    datapath = os.path.realpath(binpath + '../data') + '/'


# use explicit arguments to avoid confusion
parser = argparse.ArgumentParser(description='''
Y-factor across PA sweep, for nominal mV values.
Examples:
  yfactor.py 6 237 > b6_yf_237.ascii
  yfactor.py 7 303 > b7_yf_303.ascii
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
    logging.error('lo_ghz %g outside %s range for band %d\n'%(lo_ghz, lo_range, band))
    sys.exit(1)

# set agilent output to a safe level before setting ifswitch
agilent = namakanui.agilent.Agilent(datapath+'agilent.ini', time.sleep, namakanui.nop, simulate=0)
agilent.set_dbm(agilent.safe_dbm)
ifswitch = namakanui.ifswitch.IFSwitch(datapath+'ifswitch.ini', time.sleep, namakanui.nop, simulate=0)
ifswitch.set_band(band)

# set agilent output level for this frequency and tune the cartridge
cart = namakanui.cart.Cart(band, datapath+'band%d.ini'%(band), time.sleep, namakanui.nop, simulate=0)
cart.power(1)
cart.femc.set_cartridge_lo_pll_sb_lock_polarity_select(cart.ca, {'below':0, 'above':1}[args.lock_polarity])
floog = agilent.floog * {'below':1.0, 'above':-1.0}[args.lock_polarity]
fyig = lo_ghz / (cart.cold_mult * cart.warm_mult)
fsig = (fyig*cart.warm_mult + floog) / agilent.harmonic
agilent.set_hz(fsig*1e9)
agilent.set_dbm(agilent.interp_dbm(band, lo_ghz))
agilent.set_output(1)
time.sleep(0.05)
agilent.update()
cart.tune(lo_ghz, 0.0)
cart.update_all()

# save the nominal sis bias voltages
nom_v = cart.state['sis_v']

# TODO: adjust agilent dbm to optimize pll_if_power?

# init load controller and set to hot (ambient) load for this band
load = namakanui.load.Load(datapath+'load.ini', time.sleep, namakanui.nop, simulate=0)
load.move('b%d_hot'%(band))


# write out a header for our output file
sys.stdout.write(time.strftime('# %Y%m%d %H:%M:%S HST\n', time.localtime()))
sys.stdout.write('# %s\n'%(sys.argv))
sys.stdout.write('# nom_v: %s\n'%(nom_v))
sys.stdout.write('#\n')
sys.stdout.write('#pa ')
mixers = ['01', '02', '11', '12']
dcm_0 = list(range(20,28))
dcm_1 = list(range(12,16)) + list(range(8,12))
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

pas = []
pa = 0.0  # TODO better starting point
while pa <= 2.500001:
    pas.append(pa)
    pa += 0.01

# TODO: define a custom error type and raise/catch it like an adult


def if_setup(adjust):
    # LEVEL_ADJUST 0=setup_only, 1=setup_and_level, 2=level_only
    # BIT_MASK is DCMs to use: bit0=DCM0, bit1=DCM1, ... bit31=DCM31.
    setup_type = ['setup_only', 'setup_and_level', 'level_only']
    logging.info('setup IFTASK, LEVEL_ADJUST %d: %s', adjust, setup_type[adjust])
    # use DCMS 8-11, 12-15, 20-23, 24-27
    # TODO: maybe only specify DCMs that we take POWER readings from.
    bitmask = 0xf<<8 | 0xf<<12 | 0xf<<20 | 0xf<<24
    # TODO configurable IF_FREQ?  will 6 be default for both bands?
    msg = drama.obey('IFTASK@if-micro', 'TEST_SETUP',
                     NASM_SET='R_CABIN', BAND_WIDTH=1000, QUAD_MODE=4,
                     IF_FREQ=6, LEVEL_ADJUST=adjust, BIT_MASK=bitmask).wait(90)
    if msg.reason != drama.REA_COMPLETE or msg.status != 0:
        logging.error('bad reply from IFTASK.TEST_SETUP: %s', msg)
        return 1
    return 0



def ip(target, rows):
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
        
        # TODO do this right
        rows[i][p_index +  0] = msg.arg['POWER20']  # 1U
        rows[i][p_index +  1] = msg.arg['POWER21']  # 1U
        rows[i][p_index +  2] = msg.arg['POWER22']  # 1U
        rows[i][p_index +  3] = msg.arg['POWER23']  # 1U
        rows[i][p_index +  4] = msg.arg['POWER24']  # 1L
        rows[i][p_index +  5] = msg.arg['POWER25']  # 1L
        rows[i][p_index +  6] = msg.arg['POWER26']  # 1L
        rows[i][p_index +  7] = msg.arg['POWER27']  # 1L
        rows[i][p_index +  8] =  msg.arg['POWER12']  # 2U
        rows[i][p_index +  9] =  msg.arg['POWER13']  # 2U
        rows[i][p_index +  10] = msg.arg['POWER14']  # 2U
        rows[i][p_index +  11] = msg.arg['POWER15']  # 2U
        rows[i][p_index +  12] = msg.arg['POWER8']    # 2L
        rows[i][p_index +  13] = msg.arg['POWER9']    # 2L
        rows[i][p_index +  14] = msg.arg['POWER10']   # 2L
        rows[i][p_index +  15] = msg.arg['POWER11']   # 2L
        
    
    sys.stderr.write('\n')
    sys.stderr.flush()
    return 0
    # ip



# the rest of this needs to be DRAMA to be able to talk to IFTASK.
# TODO: could actually publish parameters.  also we need a task name.
def MAIN(msg):
    # TODO obey/kick check
    try:
        if_arg = [1,2][int(args.level_only)]
        if if_setup(if_arg):
            return
        
            
        # need to save output rows since they have both hot and sky data.
        rows = [None]*len(pas)
        for i in range(len(rows)):
            rows[i] = [0.0]*(yf_index+len(powers))
        
        if ip('hot', rows):
            return
        if ip('sky', rows):
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
    




