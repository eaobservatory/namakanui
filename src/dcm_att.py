#!/local/python3/bin/python3
'''
dcm_att.py    20201008 RMB

Tune to a range of frequencies and check the DCM attenuator level at each.
Sometimes the attenuators are left at zero, especially in 250 MHz bandwidth,
which is an error in the most recent version of acsisIf.

TODO: photonics support


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

taskname = 'DCMA_%d'%(os.getpid())

logging.root.setLevel(logging.INFO)
logging.root.addHandler(logging.StreamHandler())

binpath, datapath = namakanui.util.get_paths()

# use explicit arguments to avoid confusion
parser = argparse.ArgumentParser(description='''
DCM attenuation for a range of frequencies.
''',
  formatter_class=argparse.RawTextHelpFormatter)
parser.add_argument('band', type=int, choices=[6,7])
parser.add_argument('lo_ghz', help='LO GHz range, first:last:step')
parser.add_argument('--lock_polarity', nargs='?', choices=['below','above'], default='above')
parser.add_argument('--level_only', action='store_true')
parser.add_argument('--bw_mhz', nargs='?', default='1000', help='BW MHz range, first:last:step')
parser.add_argument('--if_ghz', nargs='?', default='6', help='IF GHz range, first:last:step')
args = parser.parse_args()

band = args.band
los = namakanui.util.parse_range(args.lo_ghz, maxlen=100e3)
bws = namakanui.util.parse_range(args.bw_mhz, maxlen=1e3)
ifs = namakanui.util.parse_range(args.if_ghz, maxlen=1e3)


# set agilent output to a safe level before setting ifswitch
agilent = namakanui.agilent.Agilent(datapath+'agilent.ini', time.sleep, namakanui.nop)
agilent.set_dbm(agilent.safe_dbm)
agilent.set_output(1)
ifswitch = namakanui.ifswitch.IFSwitch(datapath+'ifswitch.ini', time.sleep, namakanui.nop)
ifswitch.set_band(band)

# init load controller and set to hot (ambient) load for this band
load = namakanui.load.Load(datapath+'load.ini', time.sleep, namakanui.nop)
load.move('b%d_hot'%(band))

# setup cartridge
cart = namakanui.cart.Cart(band, datapath+'band%d.ini'%(band), time.sleep, namakanui.nop)
cart.power(1)
cart.femc.set_cartridge_lo_pll_sb_lock_polarity_select(cart.ca, {'below':0, 'above':1}[args.lock_polarity])
# tune to a central frequency just for the sake of the first IFTASK setup
lo_ghz = los[len(los)//2]
if not namakanui.util.tune(cart, agilent, None, lo_ghz):
    logging.error('failed to tune to %.3f ghz', lo_ghz)
    sys.exit(1)


# write out a header for our output file
sys.stdout.write(time.strftime('# %Y%m%d %H:%M:%S HST\n', time.localtime()))
sys.stdout.write('# %s\n'%(sys.argv))
sys.stdout.write('#\n')
sys.stdout.write('#lo_ghz if_ghz bw_mhz')
mixers = ['01', '02', '11', '12']
uw = ['U','W'][args.band-6]  # UU or AWEOWEO
dcm_0U = namakanui.util.get_dcms('N%s0U'%(uw))
dcm_0L = namakanui.util.get_dcms('N%s0L'%(uw))
dcm_1U = namakanui.util.get_dcms('N%s1U'%(uw))
dcm_1L = namakanui.util.get_dcms('N%s1L'%(uw))
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



def if_setup(adjust, bw_mhz, if_ghz):
    # LEVEL_ADJUST 0=setup_only, 1=setup_and_level, 2=level_only
    # BIT_MASK is DCMs to use: bit0=DCM0, bit1=DCM1, ... bit31=DCM31.
    setup_type = ['setup_only', 'setup_and_level', 'level_only']
    logging.info('setup IFTASK, LEVEL_ADJUST %d: %s', adjust, setup_type[adjust])
    bitmask = 0
    for dcm in dcms:
        bitmask |= 1<<dcm
    # TODO configurable IF_FREQ?  will 6 be default for both bands?
    msg = drama.obey('IFTASK@if-micro', 'TEST_SETUP',
                     NASM_SET='R_CABIN', BAND_WIDTH=bw_mhz, QUAD_MODE=4,
                     IF_FREQ=if_ghz, LEVEL_ADJUST=adjust, BIT_MASK=bitmask).wait(90)
    if msg.reason != drama.REA_COMPLETE or msg.status != 0:
        if msg.status == 261456746:  # ACSISIF__ATTEN_ZERO
            logging.warning('low attenuator setting from IFTASK.TEST_SETUP')
        else:
            logging.error('bad reply from IFTASK.TEST_SETUP: %s', msg)
            return 1
    return 0

def set_bw(bw_mhz):
    # this goes fast; probably doesn't do much.
    logging.info('set bandwidth %g MHz', bw_mhz)
    msg = drama.obey('IFTASK@if-micro', 'SET_DCM_BW', DCM=-1, MHZ=bw_mhz).wait(10)
    if msg.reason != drama.REA_COMPLETE or msg.status != 0:
        logging.error('bad reply from IFTASK.SET_DCM_BW: %s', msg)
        return 1
    return 0

def set_lo2(lo2_mhz):
    # this can take ~20s, or ~40s if it needs to change the coax switches.
    # why so slow?
    logging.info('set lo2 freq %g MHz', lo2_mhz)
    msg = drama.obey('IFTASK@if-micro', 'SET_LO2_FREQ', LO2=-1, MHZ=lo2_mhz).wait(90)
    if msg.reason != drama.REA_COMPLETE or msg.status != 0:
        logging.error('bad reply from IFTASK.SET_LO2_FREQ: %s', msg)
        return 1
    return 0

def get_tp2():
    msg = drama.obey("IFTASK@if-micro", "WRITE_TP2", FILE="NONE", ITIME=0.1).wait(5)
    if msg.reason != drama.REA_COMPLETE or msg.status != 0:
        logging.error('bad reply from IFTASK.WRITE_TP2: %s', msg)
        return None
    tps = []
    for dcm in dcms:
        tps.append(msg.arg['POWER%d'%(dcm)])
    return tps

def get_att():
    msg = drama.obey('IFTASK@if-micro', 'GET_DCM_ATTEN', DCM=-1).wait(5)
    if msg.reason != drama.REA_COMPLETE or msg.status != 0:
        logging.error('bad reply from IFTASK.GET_DCM_ATTEN: %s', msg)
        return None
    att = []
    for dcm in dcms:
        att.append(msg.arg['ATTEN%d'%(dcm)])
    return att

def main_loop():
    for bw_mhz in bws:
        if set_bw(bw_mhz):
            return
        
        for if_ghz in ifs:
            lo2_mhz = if_ghz*1e3 + 2500
            if bw_mhz == 250:
                lo2_mhz += 125
            if set_lo2(lo2_mhz):
                return
            
            for lo_ghz in los:
                
                if not namakanui.util.tune(cart, agilent, None, lo_ghz):
                    logging.error('failed to tune to %.3f ghz', lo_ghz)
                    continue
                if if_setup(2, bw_mhz, if_ghz):  # level only (won't actually set bw/lo2)
                    return
                att = get_att()
                if not att:
                    return
                hotp = get_tp2()
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
        if if_setup(adjust, bws[0], ifs[0]):
            return
        main_loop()
    finally:
        # final timestamp
        sys.stdout.write(time.strftime('# %Y%m%d %H:%M:%S HST\n', time.localtime()))
        sys.stdout.flush()
        # retune the receiver to get settings back to nominal
        namakanui.util.tune(cart, agilent, None, lo_ghz)
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
    




