#!/local/python3/bin/python3
'''
20190918 RMB
Script to check Y-factor (hot power / cold power) across a mixer IV sweep.
This is a 2D optimization problem between the mixer bias voltage setting
and the PA drain voltage (which adjusts LO pumping power / mixer current).
So for each row in the output data we save the following columns:
    PA setting x1, same for both POLs
    bias voltage x1, same for all mixers
    mixer current avg x4
    mixer current dev x4
    amb power x4
    sky power x4
    y-factor x4

NOTE we only take one power reading (TPD2) from each quad switch.
From cm_wire_file.txt:
01: NX1U, POWER20
02: NX1L, POWER24
11: NX2U, POWER12
12: NX2L, POWER8

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

TODO: For band 3 we'll want a PA sweep only.  It could probably use
a separate program that also automatically steps through frequencies.

TODO: Given the need for drama comms with IFTASK, this might make more
sense as an action (pair) in namakanui/cartridge tasks.  That would
also allow for easy monitoring from the GUI.

TODO: Do we need separate mixer current readings for each load?
      Or is it okay to average hot/sky readings together?
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
import namakanui.femc
import logging

taskname = 'YF_%d'%(os.getpid())

logging.root.setLevel(logging.DEBUG)
logging.root.addHandler(logging.StreamHandler())

binpath = os.path.dirname(os.path.realpath(sys.argv[0])) + '/'
# HACK, should crawl up
if 'install' in binpath:
    datapath = os.path.realpath(binpath + '../../data') + '/'
else:
    datapath = os.path.realpath(binpath + '../data') + '/'


# use explicit arguments to avoid confusion
parser = argparse.ArgumentParser(description='''
Y-factor across PA/mV sweep.
Examples:
  yfactor.py 6 237 --mv=8.0:9.9:0.05 --pa=1.0:2.5:0.1 > b6_yf_237.ascii
  yfactor.py 7 303 --mv=1.5:3.0:0.05 --pa=0.3:0.9:0.1 > b7_yf_303.ascii

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
parser.add_argument('lock_polarity', nargs='?', choices=['below','above'], default='above')
args = parser.parse_args()

def parse_range(s, what, min_step, max_step):
    s = s.split(':')
    first = float(s[0])
    if first < 0:
        logging.error(what+': negative values not allowed\n')
        sys.exit(1)
    if len(s) == 1:
        return [first]
    last = float(s[1])
    if last <= first:
        logging.error(what+': last must be greater than first\n')
        sys.exit(1)
    if len(s) == 2:
        step = last - first
    else:
        step = float(s[2])
    if not min_step <= step <= max_step:
        logging.error(what+': step outside [%g,%g] range\n'%(min_step,max_step))
        sys.exit(1)
    arr = []
    val = first
    while val < last:
        arr.append(val)
        val += step
    if abs(arr[-1] - last) < 1e-6:
        arr[-1] = last
    else:
        arr.append(last)
    return arr

band = args.band
lo_ghz = args.lo_ghz
lo_range = {6:[219,266], 7:[281,367]}[band]
if not lo_range[0] <= lo_ghz <= lo_range[1]:
    logging.error('lo_ghz %g outside %s range for band %d\n'%(lo_ghz, lo_range, band))
    sys.exit(1)
mvs = parse_range(args.mv, 'mv', 0.001, 0.05)
pas = parse_range(args.pa, 'pa', 0.01, 2.5)

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

# TODO: adjust agilent dbm to optimize pll_if_power?

# init load controller and set to hot (ambient) load for this band
load = namakanui.load.Load(datapath+'load.ini', time.sleep, namakanui.nop, simulate=0)
load.move('b%d_hot'%(band))


# write out a header for our output file
sys.stdout.write(time.strftime('# %Y%m%d %H:%M:%S HST\n', time.localtime()))
sys.stdout.write('# %s\n'%(sys.argv))
sys.stdout.write('#\n')
sys.stdout.write('#pa mv')
mixers = ['01', '02', '11', '12']
sys.stdout.write(' ' + ' '.join('ua_avg_'+m for m in mixers))
sys.stdout.write(' ' + ' '.join('ua_dev_'+m for m in mixers))
sys.stdout.write(' ' + ' '.join('hot_p_'+m for m in mixers))
sys.stdout.write(' ' + ' '.join('sky_p_'+m for m in mixers))
sys.stdout.write(' ' + ' '.join('yf_'+m for m in mixers))
sys.stdout.write('\n')
sys.stdout.flush()

# output column starting indices
pa_index = 0
mv_index = 1
ua_avg_index = 2
ua_dev_index = 6
hot_p_index = 10
sky_p_index = 14
yf_index = 18

# number of mixer current readings to take per bias voltage (per load)
# TODO might be able to double this without impacting runtime due to ITIME;
# depends on actual value of ppcomm_time.
ua_n = 10


# TODO: define a custom error type and raise/catch it like an adult


def if_setup(adjust):
    # LEVEL_ADJUST 0=setup_only, 1=setup_and_level, 2=level_only
    # BIT_MASK is DCMs to use: bit0=DCM0, bit1=DCM1, ... bit31=DCM31.
    setup_type = ['setup_only', 'setup_and_level', 'level_only']
    logging.info('setup IFTASK, LEVEL_ADJUST %d: %s', adjust, setup_type[adjust])
    # use DCMS 8-11, 12-15, 20-23, 24-27
    bitmask = 0xf<<8 | 0xf<<12 | 0xf<<20 | 0xf<<24
    # TODO configurable IF_FREQ?  will 6 be default for both bands?
    msg = drama.obey('IFTASK@if-micro', 'TEST_SETUP',
                     NASM_SET='R_CABIN', BAND_WIDTH=1000, QUAD_MODE=4,
                     IF_FREQ=6, LEVEL_ADJUST=adjust, BIT_MASK=bitmask).wait(5)
    if msg.reason != drama.REA_COMPLETE or msg.status != 0:
        logging.error('bad reply from IFTASK.TEST_SETUP: %s', msg)
        return 1
    return 0


def iv(target, rows):
    if target == 'hot':
        p_index = hot_p_index
    else:
        p_index = sky_p_index
    load.move('b%d_%s'%(band,target))
    sys.stderr.write('%s: '%(target))
    sys.stderr.flush()
    
    # at the start of a HOT row, re-tune and re-level the power meters
    # at the nominal values.  do not relevel on SKY or y-factor won't work.
    if target == 'hot':
        cart.tune(lo_ghz, 0.0)
        cart.update_all()
        if if_setup(2):  # level only
            return 1
    
    cart._ramp_sis_bias_voltages([mvs[0]*4)
    for i,mv in enumerate(mvs):
        if (i+1) % 10 == 0:
            sys.stderr.write('%.2f%% '%(100*i/len(mvs))
            sys.stderr.flush()
            cart.update_all()  # for anyone monitoring
        for po in range(2):
            #for sb in range(2):
            #    cart.femc.set_sis_voltage(cart.ca, po, sb, mv)
            
            # flip bias voltage for band 6 USB
            if band == 6:
                cart.femc.set_sis_voltage(cart.ca, po, 0, -mv)
                cart.femc.set_sis_voltage(cart.ca, po, 1,  mv)
            else:
                cart.femc.set_sis_voltage(cart.ca, po, 0, mv)
                cart.femc.set_sis_voltage(cart.ca, po, 1, mv)
        rows[i][mv_index] = mv
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
        rows[i][p_index + 0] = msg.arg['POWER20']
        rows[i][p_index + 1] = msg.arg['POWER24']
        rows[i][p_index + 2] = msg.arg['POWER12']
        rows[i][p_index + 3] = msg.arg['POWER8']
    
    return 0
    # iv



# the rest of this needs to be DRAMA to be able to talk to IFTASK.
# TODO: could actually publish parameters.  also we need a task name.
def MAIN(msg):
    # TODO obey/kick check
    
    if if_setup(1):  # setup and level
        drama.Exit('MAIN done')
        return
    
    for k,pa in enumerate(pas):
        logging.info('========= PA: %g (%.2f%%) =========', pa, 100*k/len(pas))
        cart._set_pa([pa,pa])
        
        # need to save output rows since they have both hot and sky data.
        rows = [None]*len(mvs)
        for i in range(len(rows)):
            rows[i] = [0.0]*22  # TODO unmagic
            rows[i][pa_index] = pa
        
        if iv('hot', rows):
            break
        if iv('sky', rows):
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
                
                # calculate y-factors
                r[yf_index + j] = r[hot_p_index + j] / r[sky_p_index + j]
                
            # write out the data
            sys.stdout.write(' '.join('%g'%x for x in r) + '\n')
            sys.stdout.flush()
        
    # finally retune the receiver to get settings back to nominal
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
    




