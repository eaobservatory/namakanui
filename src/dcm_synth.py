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
import namakanui.reference
import namakanui.util

import logging

taskname = 'TRXS_%d'%(os.getpid())

namakanui.util.setup_logging()

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

# TODO: script arg for inifile
reference = namakanui.reference.Reference(datapath+'reference.ini', time.sleep, namakanui.nop)
reference.set_dbm(reference.safe_dbm)
reference.set_output(1)

# write out a header for our output file
sys.stdout.write(time.strftime('# %Y%m%d %H:%M:%S HST\n', time.localtime()))
sys.stdout.write('# %s\n'%(sys.argv))
sys.stdout.write('#\n')
sys.stdout.write('#dbm if_ghz bw_mhz')
for dcm in dcms:
    sys.stdout.write(' dcm_%02d'%(dcm))
sys.stdout.write('\n')
sys.stdout.flush()


def main_loop():
    for bw_mhz in bws:
        namakanui.util.iftask_set_bw(bw_mhz)
        
        for if_ghz in ifs:
            lo2_mhz = if_ghz*1e3 + 2500
            if bw_mhz == 250:
                lo2_mhz += 125
            namakanui.util.iftask_set_lo2(lo2_mhz)
            
            reference.set_hz_dbm(if_ghz*1e9, dbms[0])
            namakanui.util.iftask_setup(2, bw_mhz, if_ghz, dcms)  # level only
            
            for dbm in dbms:
                reference.set_dbm(dbm)
                time.sleep(0.05)
                pwr = namakanui.util.iftask_get_tp2(dcms)
                sys.stdout.write('%.2f %g %g'%(dbm, if_ghz, bw_mhz))
                for p in pwr:
                    sys.stdout.write(' %g'%(p))
                sys.stdout.write('\n')
                sys.stdout.flush()
    # main_loop



# the rest of this needs to be DRAMA to be able to talk to IFTASK.
def MAIN(msg):
    try:
        adjust = [1,2][int(args.level_only)]
        namakanui.util.iftask_setup(adjust, bws[0], ifs[0], dcms)
        main_loop()
    finally:
        # final timestamp
        sys.stdout.write(time.strftime('# %Y%m%d %H:%M:%S HST\n', time.localtime()))
        sys.stdout.flush()
        reference.set_dbm(reference.safe_dbm)
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
    
