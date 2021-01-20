#!/local/python3/bin/python3
'''
att_pmeter.py    RMB 20210119

Test power at the harmonic mixer using the new attenuator
in the photonic receiver.

Set signal generator to a constant frequency and output power,
then sweep the attenuator across its full range.  The point of
this script is to make sure the attenuator is working and that
I haven't swapped any bits.


Copyright (C) 2021 East Asian Observatory

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
import namakanui.ifswitch
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
parser.add_argument('IP', help='N1913A power meter IP address')  # 128.171.92.36
parser.add_argument('band', type=int)
parser.add_argument('ghz', type=float, help='synth freq ghz')
parser.add_argument('dbm', type=float, help='synth power')
parser.add_argument('--note', nargs='?', default='', help='note for file header')
args = parser.parse_args()


agilent = namakanui.agilent.Agilent(datapath+'agilent.ini', time.sleep, namakanui.nop)
agilent.log.setLevel(logging.INFO)
agilent.set_dbm(agilent.safe_dbm)
agilent.set_output(1)

ifswitch = namakanui.ifswitch.IFSwitch(datapath+'ifswitch.ini', time.sleep, namakanui.nop)
ifswitch.set_band(args.band)
ifswitch.close()  # done with ifswitch

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
sys.stdout.write('#att pow\n')
sys.stdout.flush()


def read_power():
    '''Return power reading in dBm.'''
    #raise RuntimeError('TODO')
    pmeter.send(b'fetch?\n')
    return float(pmeter.recv(256))


agilent.set_hz_dbm(args.ghz*1e9, args.dbm)
att = photonics.max_att + 1
pmeter.send(b'freq %gGHz\n'%(args.ghz))  # for power sensor cal tables

while att > 0:
    att -= 1
    delay = 0.1  # generous sleep since pmeter takes 50ms/read
    photonics.set_attenuation(att)
    time.sleep(delay)
    power = read_power()
    sys.stdout.write('%d %.2f\n'%(att,power))
    sys.stdout.flush()

att = -1
while att < photonics.max_att:
    att += 1
    delay = 0.1  # generous sleep since pmeter takes 50ms/read
    photonics.set_attenuation(att)
    time.sleep(delay)
    power = read_power()
    sys.stdout.write('%d %.2f\n'%(att,power))
    sys.stdout.flush()

agilent.set_dbm(agilent.safe_dbm)
photonics.set_attenuation(photonics.max_att)
sys.stderr.write('done.\n')




