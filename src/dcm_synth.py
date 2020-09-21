#!/local/python3/bin/python3
'''
dcm_synth.py   20200909 RMB

TP2 test with the signal generator connected directly to the DCM quad input.

TODO: Is there some way to guarantee that we're not accidentally
      talking to the wrong signal generator?


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
import namakanui.agilent
import namakanui.util

import logging

taskname = 'TRXS_%d'%(os.getpid())

logging.root.setLevel(logging.INFO)
logging.root.addHandler(logging.StreamHandler())

binpath, datapath = namakanui.util.get_paths()

# use explicit arguments to avoid confusion
parser = argparse.ArgumentParser(description='''
TP2 readings for direct synthesizer-to-DCM connection.
''',
  formatter_class=argparse.RawTextHelpFormatter)
parser.add_argument('--level_only', action='store_true')
parser.add_argument('--bw_mhz', nargs='?', default='1000', help='BW MHz range, first:last:step')
parser.add_argument('--if_ghz', nargs='?', default='6', help='IF GHz range, first:last:step')
parser.add_argument('--dbm', nargs='?', default='14:-20:.1', help='dBm range, hi:lo:step')
parser.add_argument('--dcm', type=int, help='starting DCM id (0-based); TP2 collected thru dcm+3.')
parser.add_argument('--note', nargs='?', default='', help='note for output file')
args = parser.parse_args()


bws = namakanui.util.parse_range(args.bw_mhz, maxlen=1e3)
ifs = namakanui.util.parse_range(args.if_ghz, maxlen=1e3)
dbms = namakanui.util.parse_range(args.dbm, maxlen=4e3)
dcms = range(args.dcm, args.dcm+4)

# set agilent output to a safe level
# RMB 20200911: paranoia, make sure to use cabin agilent instead of keysight
agilent = namakanui.agilent.Agilent(datapath+'agilent_cabin.ini', time.sleep, namakanui.nop)
agilent.set_dbm(agilent.safe_dbm)
agilent.set_output(1)

# write out a header for our output file
sys.stdout.write(time.strftime('# %Y%m%d %H:%M:%S HST\n', time.localtime()))
sys.stdout.write('# %s\n'%(sys.argv))
sys.stdout.write('#\n')
sys.stdout.write('#dbm if_ghz bw_mhz')
for dcm in dcms:
    sys.stdout.write(' dcm_%02d'%(dcm))
sys.stdout.write('\n')
sys.stdout.flush()

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
            
            agilent.set_hz_dbm(if_ghz*1e9, dbms[0])
            if if_setup(2, bw_mhz, if_ghz):  # level only (won't actually set bw/lo2)
                return
            
            for dbm in dbms:
                agilent.set_dbm(dbm)
                time.sleep(0.05)
                # start IFTASK action
                transid = drama.obey("IFTASK@if-micro", "WRITE_TP2", FILE="NONE", ITIME=0.1)
                # get IFTASK reply
                msg = transid.wait(5)
                if msg.reason != drama.REA_COMPLETE or msg.status != 0:
                    logging.error('bad reply from IFTASK.WRITE_TP2: %s', msg)
                    return 1
                sys.stdout.write('%.2f %g %g'%(dbm, if_ghz, bw_mhz))
                for j,dcm in enumerate(dcms):
                    sys.stdout.write(' %g'%(msg.arg['POWER%d'%(dcm)]))
                sys.stdout.write('\n')
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
        agilent.set_dbm(agilent.safe_dbm)
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
    
