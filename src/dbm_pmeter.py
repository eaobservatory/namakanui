#!/local/python3/bin/python3
'''
dbm_pmeter.py   RMB 20200715

Set synthesizer to a range of values and check power via an N1913A power meter.
Writes table to stdout; use 'tee' to monitor output progress.

NOTE: This script does not set the Namakanui IF Switch, since it's assumed
that we're running in a nonstandard configuration.  If needed,
use tune.py or other script to set the IF switch to the desired position
before running this script.

This script runs in three different modes:

1. If "--table" is given, the power meter should be connected between the
signal generator output and the receiver harmonic mixer.  The table given
should be created by the dbm_table.py script; the signal generator output
frequency and power will be set according to the table entries.
The cartridge band (which affects the lo_ghz -> sig_hz calculation)
is assumed from the table filename, like "bX_dbm*".

2. If "--sig_ghz" and "--sig_dbm" are given, the power meter should again
be connected between the signal generator output and the receiver
harmonic mixer.  The signal generator output is set according to
the ranges given.

3. If "--band" is given, the power meter should be connected to the
receiver output: either an IF output or a WCA waveguide.  The receiver
will be tuned according to the following arguments:
  "--lock_polarity": Lock rx "below" or "above" reference (default above).
  "--lo_ghz": Range of LOs to tune to.
  "--pa": Range of PA values; if missing, no override.
  "--if_ghz": Frequency for pmeter; if missing, use WCA output frequency.


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
import namakanui.agilent
import namakanui.util
import namakanui.ini
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
parser.add_argument('ip', help='N1913A power meter IP address')  # 128.171.92.36
parser.add_argument('--table', nargs='?', default='', help='dbm table file, overrides ghz/dbm')
parser.add_argument('--ghz', nargs='?', default='20', help='ghz range, first:last:step')
parser.add_argument('--dbm', nargs='?', default='-20', help='dbm range, first:last:step')
parser.add_argument('--band', nargs='?', type=int, default=0, help='rx band for tuning')
parser.add_argument('--lo_ghz', nargs='?', default='0', help='LO range for tuning')
parser.add_argument('--pa', nargs='?', default='', help='PA range for tuning')
parser.add_argument('--pol', nargs='?', type=int, choices=[0,1], help='which polarization (other is set to zero)')
parser.add_argument('--if_ghz', nargs='?', type=float, default=0.0, help='pmeter frequency')
parser.add_argument('--lock_polarity', nargs='?', choices=['below','above'], default='above')
parser.add_argument('--note', nargs='?', default='', help='note for file header')
args = parser.parse_args()

sys.stdout.write(time.strftime('# %Y%m%d %H:%M:%S HST\n', time.localtime()))
sys.stdout.write('# %s\n'%(sys.argv))
sys.stdout.write('#\n')
sys.stdout.flush()

agilent = namakanui.agilent.Agilent(datapath+'agilent.ini', time.sleep, namakanui.nop)
agilent.log.setLevel(logging.INFO)
agilent.set_dbm(agilent.safe_dbm)
agilent.set_output(1)


# TODO: is it worth making a class for the N1913A?
pmeter = socket.socket()
pmeter.settimeout(1)
pmeter.connect((args.ip, 5025))
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


if args.band:
    if args.pa and args.pol is None:
        logging.error('missing arg "pol", must be 0 or 1.')
        agilent.set_dbm(agilent.safe_dbm)
        logging.info('done.')
        sys.exit(1)
    # tune rx to range of values and take power readings.
    # for this mode we might be using the photonics attenuator as well.
    band = args.band
    import namakanui.cart
    cart = namakanui.cart.Cart(band, datapath+'band%d.ini'%(band), time.sleep, namakanui.nop)
    cart.power(1)
    cart.femc.set_cartridge_lo_pll_sb_lock_polarity_select(cart.ca, {'below':0, 'above':1}[args.lock_polarity])
    photonics = None
    nconfig = namakanui.ini.IncludeParser(datapath+'namakanui.ini')
    if 'photonics_ini' in nconfig['namakanui']:
        pini = nconfig['namakanui']['photonics_ini']
        photonics = namakanui.photonics.Photonics(datapath+pini, time.sleep, namakanui.nop)
        photonics.set_attenuation(photonics.max_att)
    los = namakanui.util.parse_range(args.lo_ghz)
    if args.pa:
        pas = namakanui.util.parse_range(args.pa)
    if args.if_ghz:
        sys.stdout.write('#lo_ghz if_ghz pa0 pa1 vd0 vd1 id0 id1 pmeter_dbm\n')
    else:
        sys.stdout.write('#lo_ghz wca_ghz pa0 pa1 vd0 vd1 id0 id1 pmeter_dbm\n')
    sys.stdout.flush()
    for lo_ghz in los:
        if not namakanui.util.tune(cart, agilent, photonics, lo_ghz):
            logging.error('failed to tune to %.3f ghz', lo_ghz)
            continue
        if args.if_ghz:
            if_ghz = args.if_ghz
        else:
            # use WCA output frequency
            if_ghz = lo_ghz / cart.cold_mult
        pmeter.send(b'freq %gGHz\n'%(if_ghz))
        if args.pa:
            for pa in pas:
                if args.pol == 0:
                    pa0 = pa;
                    pa1 = 0;
                    vg0 = 0.06  # HACK
                    vg1 = 0;
                elif args.pol == 1:
                    pa0 = 0;
                    pa1 = pa;
                    vg0 = 0
                    vg1 = -0.19  # HACK
                cart._set_pa([pa0,pa1,vg0,vg1])
                time.sleep(0.1)
                cart.update_all()
                dv = cart.state['pa_drain_v']
                di = cart.state['pa_drain_c']
                power = read_power()
                sys.stdout.write('%.3f %.3f %.2f %.2f %.3f %.3f %.3f %.3f %.3f\n'%(lo_ghz, if_ghz, pa0, pa1, dv[0], dv[1], di[0], di[1], power))
                sys.stdout.flush()
        else:
            pa0,pa1 = cart.state['pa_drain_s']
            time.sleep(0.1)
            cart.update_all()
            dv = cart.state['pa_drain_v']
            di = cart.state['pa_drain_c']
            power = read_power()
            sys.stdout.write('%.3f %.3f %.2f %.2f %.3f %.3f %.3f %.3f %.3f\n'%(lo_ghz, if_ghz, pa0, pa1, dv[0], dv[1], di[0], di[1], power))
            sys.stdout.flush()
elif args.table:
    # read in a dbm table, assume band from filename.
    # set synthesizer to each point and take a reading.
    fname = args.table.rpartition('/')[-1]
    assert len(fname)>1 and fname[0]=='b' and fname[1] in ['3','6','7'], 'bad filename format, expecting "b[3,6,7]_dbm*"'
    band = int(fname[1])
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




