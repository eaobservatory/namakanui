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
import namakanui.reference
import namakanui.photonics
import namakanui.ifswitch
import namakanui.pmeter
import namakanui.util
import sys
import os
import argparse
import socket
import time
import math

import logging
namakanui.util.setup_logging()

config = namakanui.util.get_config()
bands = namakanui.util.get_bands(config)

parser = argparse.ArgumentParser(
    formatter_class=argparse.RawTextHelpFormatter,
    description=namakanui.util.get_description(__doc__)
    )
parser.add_argument('band', type=int, choices=bands)
parser.add_argument('ghz', type=float, help='synth freq ghz')
parser.add_argument('dbm', type=float, help='synth power')
parser.add_argument('--note', nargs='?', default='', help='note for file header')
args = parser.parse_args()


reference = namakanui.reference.Reference(config, time.sleep, namakanui.nop)
reference.set_dbm(reference.safe_dbm)
reference.set_output(1)

ifswitch = namakanui.ifswitch.IFSwitch(config, time.sleep, namakanui.nop)
ifswitch.set_band(args.band)
ifswitch.close()  # done with ifswitch

photonics = namakanui.photonics.Photonics(config, time.sleep, namakanui.nop)
photonics.set_attenuation(photonics.max_att)

pmeter = namakanui.pmeter.PMeter(config, time.sleep, namakanui.nop)


# output file header
sys.stdout.write(time.strftime('# %Y%m%d %H:%M:%S HST\n', time.localtime()))
sys.stdout.write('# %s\n'%(sys.argv))
sys.stdout.write('#\n')
sys.stdout.write('#att pow\n')
sys.stdout.flush()


reference.set_hz_dbm(args.ghz*1e9, args.dbm)
att = photonics.max_att + 1
pmeter.set_ghz(args.ghz)  # for power sensor cal tables

while att > 0:
    att -= 1
    delay = 0.1  # generous sleep since pmeter takes 50ms/read
    photonics.set_attenuation(att)
    time.sleep(delay)
    power = pmeter.read_power()
    sys.stdout.write('%d %.2f\n'%(att,power))
    sys.stdout.flush()

att = -1
while att < photonics.max_att:
    att += 1
    delay = 0.1  # generous sleep since pmeter takes 50ms/read
    photonics.set_attenuation(att)
    time.sleep(delay)
    power = pmeter.read_power()
    sys.stdout.write('%d %.2f\n'%(att,power))
    sys.stdout.flush()

reference.set_dbm(reference.safe_dbm)
photonics.set_attenuation(photonics.max_att)
logging.info('done.\n')




