#!/local/python3/bin/python3
'''
RMB 20200715

Set synthesizer to a range of values and check power via an N1913A power meter.
Writes table to stdout; use 'tee' to monitor output progress.
'''

import jac_sw
import namakanui.agilent
import namakanui.util
import sys
import os
import argparse
import socket
import time

import logging
logging.root.setLevel(logging.INFO)
logging.root.addHandler(logging.StreamHandler())

binpath, datapath = namakanui.util.get_paths()

parser = argparse.ArgumentParser()
#parser.add_argument('IP', help='prologix adapter IP address')
#parser.add_argument('GPIB', type=int, help='power meter GPIB address')
parser.add_argument('ip', help='N1913A power meter IP address')
parser.add_argument('--table', nargs='?', default='', help='dbm table file, overrides ghz/dbm')
parser.add_argument('--ghz', nargs='?', default='20', help='ghz range, first:last:step')
parser.add_argument('--dbm', nargs='?', default='-20', help='dbm range, first:last:step')
args = parser.parse_args()

sys.stdout.write(time.strftime('# %Y%m%d %H:%M:%S HST\n', time.localtime()))
sys.stdout.write('# %s\n'%(sys.argv))
sys.stdout.write('#\n')
sys.stdout.flush()

agilent = namakanui.agilent.Agilent(datapath+'agilent.ini', time.sleep, namakanui.nop, simulate=0)
agilent.log.setLevel(logging.INFO)
agilent.set_dbm(agilent.safe_dbm)
agilent.set_output(1)


# TODO: is it worth making a class for the N1913A?
pmeter = socket.socket()
pmeter.settimeout(1)
pmeter.connect((args.IP, 5025))
pmeter.send(b'*idn?\n')
idn = pmeter.recv(256)
if b'N1913A' not in idn:
    logging.error('expected power meter model N1913A, but got %s', idn)
    sys.exit(1)
# just assume all this succeeds
pmeter.send(b'*cls\n')  # clear errors
pmeter.send(b'unit:power dbm\n')  # dBm readings
pmeter.send(b'init:cont on\n')  # free run mode
pmeter.send(b'mrate normal\n')  # 20 reads/sec
pmeter.send(b'calc:hold:stat off\n')  # no min/max stuff
pmeter.send(b'aver:count:auto on\n')  # auto filter settings
pmeter.send(b'syst:err?\n')
err = pmeter.recv(256)
if not err.startswith(b'+0,"No error"'):
    logging.error('N1913A setup failure: %s', err)
    sys.exit(1)



def read_power():
    '''Return power reading in dBm.'''
    #raise RuntimeError('TODO')
    pmeter.send(b'fetch?\n')
    return float(pmeter.recv(256))

if args.table:
    # read in a dbm table, assume band from filename.
    # set synthesizer to each point and take a reading.
    assert len(args.table)>1 and args.table[0]=='b' and args.table[1] in ['3','6','7'], 'bad filename format, expecting "b[3,6,7]_dbm*"'
    band = int(args.table[1])
    # HACK, i'm not going to bother with full bandX.ini read here
    cold_mult = 3
    warm_mult = 6
    if band == 3:
        cold_mult = 1
    # HACK, assume lock above reference
    lock_polarity = 1
    floog = agilent.floog * [1.0, -1.0][lock_polarity]  # [below, above]
    sys.stdout.write('#lo_ghz sig_ghz sig_dbm pmeter_dbm\n')
    sys.stdout.flush()
    logging.info('looping over entries in %s', args.table)
    for line in open(args.table):
        line = line.strip()
        if not line:
            continue
        if line.startswith('#'):
            continue
        vals = [float(x) for x in line.split()]
        lo_ghz = vals[0]
        dbm = vals[1]
        fyig = lo_ghz / (cold_mult * warm_mult)
        fsig = (fyig*warm_mult + floog) / agilent.harmonic
        agilent.set_hz_dbm(fsig*1e9, dbm)
        pmeter.send(b'freq %gGHz\n'%(fsig))  # for power sensor calibration tables
        time.sleep(0.1)  # generous sleep since pmeter takes 50ms/read
        power = read_power()
        sys.stdout.write('%.3f %.6f %.2f %.3f\n'%(lo_ghz, fsig, dbm, power))
        sys.stdout.flush()
else:
    # loop over ghz range for each dbm
    ghzs = namakanui.util.parse_range(args.ghz)
    dbms = namakanui.util.parse_range(args.dbm)
    sys.stdout.write('#sig_ghz sig_dbm pmeter_dbm\n')
    sys.stdout.flush()
    logging.info('looping over ghz range %s for each dbm in %s', args.ghz, args.dbm)
    for dbm in dbms:
        for ghz in ghzs:
            agilent.set_hz_dbm(ghz*1e9, dbm)
            pmeter.send(b'freq %gGHz\n'%(ghz))  # for power sensor calibration tables
            time.sleep(0.1)  # generous sleep since pmeter takes 50ms/read
            power = read_power()
            sys.stdout.write('%.6f %.2f %.3f\n'%(ghz, dbm, power))
            sys.stdout.flush()

agilent.set_dbm(agilent.safe_dbm)
logging.info('done.')




