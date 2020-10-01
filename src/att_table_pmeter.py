#!/local/python3/bin/python3
'''
att_table_pmeter.py    RMB 20200930

Test power at the harmonic mixer using the new attenuator
in the photonic receiver.

This script uses the output table from dbm_photo.py,
which is made to feed a constant power level (+10 dBm)
to the photonic transmitter.  It controls the attenuator
in the photonic receiver to produce approximately +12 dBm
at the input to the harmonic mixer, after passing through
the amplifier in the IF switch.

The output here could be modified and used as a starting point
for the full att_table.py script, but really it's just intended
as a bench test to show that we're hitting the desired power levels.


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
import namakanui.photonics
import namakanui.util
import namakanui.ini
import sys
import os
import argparse
import socket
import time
import math

import logging
logging.root.setLevel(logging.INFO)
logging.root.addHandler(logging.StreamHandler())

binpath, datapath = namakanui.util.get_paths()

parser = argparse.ArgumentParser()
#parser.add_argument('IP', help='prologix adapter IP address')
#parser.add_argument('GPIB', type=int, help='power meter GPIB address')
parser.add_argument('IP', help='N1913A power meter IP address')
parser.add_argument('target_dbm', type=float, help='target dBm reading')
parser.add_argument('start_att', type=int, help='starting attenuator setting (counts)')
parser.add_argument('ghz_range', help='synth freq range, start:end:step')
parser.add_argument('dbm_table', help='synth power table file path')
parser.add_argument('--att_table', nargs='?', default='', help='attenuator table file path, overrides start_att')
parser.add_argument('--note', nargs='?', default='', help='note for file header')
args = parser.parse_args()

if args.target_dbm < -20.0 or args.target_dbm > 14.0:
    sys.stderr.write('error: target dBm %g outside [-20, 14] range\n'%(args.target_dbm))
    sys.exit(1)

if args.start_att < 0 or args.start_att > 63:
    sys.stderr.write('error: starting att %d outside [0, 63] range\n'%(args.start_att))
    sys.exit(1)

ghz_range = namakanui.util.parse_range(args.ghz_range, maxlen=100e3)
ghz_min = min(ghz_range)
ghz_max = max(ghz_range)
if ghz_min < 16 or ghz_max > 32:
    sys.stderr.write('error: ghz_range %s outside [16, 32] range\n'%(args.ghz_range))
    sys.exit(1)
    
dbm_table = namakanui.ini.read_ascii(args.dbm_table)
att_table = []
if args.att_table:
    att_table = namakanui.ini.read_ascii(args.att_table)


agilent = namakanui.agilent.Agilent(datapath+'agilent.ini', time.sleep, namakanui.nop)
agilent.log.setLevel(logging.INFO)
agilent.set_dbm(agilent.safe_dbm)
agilent.set_output(1)

photonics = namakanui.photonics.Photonics(datapath+'photonics.ini', time.sleep, namakanui.nop)
photonics.set_attenuation(photonics.max_att)

#prologix = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
#prologix.settimeout(1)
#prologix.connect((args.IP, 1234))
#prologix.send(b'++savecfg 0\n')  # don't save settings to prologix EPROM
#prologix.send(b'++addr %d\n'%(args.GPIB))

# TODO: is it worth making a class for the N1913A?
pmeter = socket.socket()
pmeter.settimeout(1)
pmeter.connect((args.IP, 5025))
pmeter.send(b'*idn?\n')
idn = pmeter.recv(256)
if b'N1913A' not in idn:
    sys.stderr.write('error: expected power meter model N1913A, but got %s\n'%(idn))
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
    sys.stderr.write('error: N1913A setup failure: %s\n'%(err))
    sys.exit(1)


# output file header
sys.stdout.write(time.strftime('# %Y%m%d %H:%M:%S HST\n', time.localtime()))
sys.stdout.write('# %s\n'%(sys.argv))
sys.stdout.write('#\n')
sys.stdout.write('#ghz dbm att pow\n')
sys.stdout.flush()


def read_power():
    '''Return power reading in dBm.'''
    #raise RuntimeError('TODO')
    pmeter.send(b'fetch?\n')
    return float(pmeter.recv(256))

def sign(x):
    if x > 0:
        return 1
    elif x < 0:
        return -1
    return 0


for ghz in ghz_range:
    sys.stderr.write('%.3f: '%(ghz))
    sys.stderr.flush()
    delay = 0.1  # generous sleep since pmeter takes 50ms/read
    interp_row = namakanui.ini.interp_table(dbm_table, ghz)
    dbm = interp_row.dbm
    att = args.start_att
    if att_table:
        interp_row = namakanui.ini.interp_table(att_table, ghz)
        att = interp_row.att
    # set power safely: if decreasing attenuation, set freq first.
    hz = ghz*1e9
    if att < photonics.state['attenuation']:
        agilent.set_hz_dbm(hz, dbm)
        photonics.set_attenuation(att)
    else:
        photonics.set_attenuation(att)
        agilent.set_hz_dbm(hz, dbm)
    pmeter.send(b'freq %gGHz\n'%(ghz))  # for power sensor cal tables
    # take initial reading
    time.sleep(delay)
    power = read_power()
    sys.stderr.write('(%d, %.2f)'%(att,power))
    sys.stderr.flush()
    # quickly decrease attenuation until above target power
    while att > 0 and power < args.target_dbm:
        dcounts = (args.target_dbm - power) * 2 + 1
        att -= dcounts
        if att < 0:
            att = 0
        photonics.set_attenuation(att)
        time.sleep(delay)
        power = read_power()
        sys.stderr.write('(%d, %.2f)'%(att,power))
        sys.stderr.flush()
    # quickly increase attenuation until below target power
    while att < photonics.max_att and power >= args.target_dbm:
        dcounts = (power - args.target_dbm) * 2 + 1
        att += dcounts
        if att > photonics.max_att:
            att = photonics.max_att
        photonics.set_attenuation(att)
        time.sleep(delay)
        power = read_power()
        sys.stderr.write('(%d, %.2f)'%(att,power))
        sys.stderr.flush()
    # slowly decrease attenuation until just above target power
    while att > 0 and power < args.target_dbm:
        att -= 1
        photonics.set_attenuation(att)
        time.sleep(delay)
        power = read_power()
        sys.stderr.write('(%d, %.2f)'%(att,power))
        sys.stderr.flush()
    # done, write it out.
    sys.stderr.write('\n')
    sys.stderr.flush()
    sys.stdout.write('%.3f %.2f %d %.3f\n'%(ghz,dbm,att,power))
    sys.stdout.flush()



agilent.set_dbm(agilent.safe_dbm)
photonics.set_attenuation(photonics.max_att)
sys.stderr.write('done.\n')




