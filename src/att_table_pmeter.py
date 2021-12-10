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
the amplifier in the signal test source reference unit.

The output here could be modified and used as a starting point
for the full att_table.py script, but really it's just intended
as a bench test to show that we're hitting the desired power levels.

RMB 20211209: Update for GLT testing.  Remove band argument
and IFSwitch; the power meter will be connected to unused output #4
on the signal test source reference unit, which will be manually
set to use that output.  Use photonics_dbm table from config by default.


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
import namakanui.reference
import namakanui.photonics
import namakanui.pmeter
import namakanui.util
import namakanui.ini
import sys
import os
import argparse
import socket
import time
import math

import logging
namakanui.util.setup_logging()

config = namakanui.util.get_config()

parser = argparse.ArgumentParser(
    formatter_class=argparse.RawTextHelpFormatter,
    description=namakanui.util.get_description(__doc__)
    )
parser.add_argument('--target_dbm', nargs='?', default=12.0, type=float, choices=namakanui.util.interval(-20, 14), help='target dBm reading, default 12')
parser.add_argument('--start_att', nargs='?', default=63, type=int, choices=namakanui.util.interval(0, 63), help='starting attenuator setting (counts), default 63')  # TODO check nbits first
parser.add_argument('--ghz_range', nargs='?', default='18:31:1', help='synth freq range, start:end:step, default 18:31:1')
parser.add_argument('--dbm_table', nargs='?', default='', help='synth power table file path, default use photonics_dbm table from config')
parser.add_argument('--att_table', nargs='?', default='', help='attenuator table file path, overrides start_att')
parser.add_argument('--note', nargs='?', default='', help='note for file header')
args = parser.parse_args()


ghz_range = namakanui.util.parse_range(args.ghz_range, maxlen=100e3)
ghz_min = min(ghz_range)
ghz_max = max(ghz_range)
if ghz_min < 16 or ghz_max > 32:
    sys.stderr.write('error: ghz_range %s outside [16, 32] range\n'%(args.ghz_range))
    sys.exit(1)

reference = namakanui.reference.Reference(config, time.sleep, namakanui.nop)
reference.set_dbm(reference.safe_dbm)
reference.set_output(1)

photonics = namakanui.photonics.Photonics(config, time.sleep, namakanui.nop)
photonics.set_attenuation(photonics.max_att)

pmeter = namakanui.pmeter.PMeter(config, time.sleep, namakanui.nop)

dbm_table = reference.dbm_tables[0]  # photonics_dbm
if args.dbm_table:
    dbm_table = namakanui.ini.read_ascii(args.dbm_table)
att_table = []
if args.att_table:
    att_table = namakanui.ini.read_ascii(args.att_table)


# output file header
sys.stdout.write(time.strftime('# %Y%m%d %H:%M:%S UTC\n', time.gmtime()))
sys.stdout.write('# %s\n'%(sys.argv))
sys.stdout.write('#\n')
sys.stdout.write('#ghz dbm att pow\n')
sys.stdout.flush()



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
        reference.set_hz_dbm(hz, dbm)
        photonics.set_attenuation(att)
    else:
        photonics.set_attenuation(att)
        reference.set_hz_dbm(hz, dbm)
    pmeter.set_ghz(ghz)  # for power sensor cal tables
    # take initial reading
    time.sleep(delay)
    power = pmeter.read_power()
    sys.stderr.write('(%d, %.2f)'%(att,power))
    sys.stderr.flush()
    # quickly decrease attenuation until above target power
    while att > 0 and power < args.target_dbm:
        dcounts = (args.target_dbm - power) * photonics.counts_per_db/2 + 1
        att -= dcounts
        if att < 0:
            att = 0
        photonics.set_attenuation(att)
        time.sleep(delay)
        power = pmeter.read_power()
        sys.stderr.write('(%d, %.2f)'%(att,power))
        sys.stderr.flush()
    # quickly increase attenuation until below target power
    while att < photonics.max_att and power >= args.target_dbm:
        dcounts = (power - args.target_dbm) * photonics.counts_per_db/2 + 1
        att += dcounts
        if att > photonics.max_att:
            att = photonics.max_att
        photonics.set_attenuation(att)
        time.sleep(delay)
        power = pmeter.read_power()
        sys.stderr.write('(%d, %.2f)'%(att,power))
        sys.stderr.flush()
    # slowly decrease attenuation until just above target power
    while att > 0 and power < args.target_dbm:
        att -= 1
        photonics.set_attenuation(att)
        time.sleep(delay)
        power = pmeter.read_power()
        sys.stderr.write('(%d, %.2f)'%(att,power))
        sys.stderr.flush()
    # done, write it out.
    sys.stderr.write('\n')
    sys.stderr.flush()
    sys.stdout.write('%.3f %.2f %d %.3f\n'%(ghz,dbm,att,power))
    sys.stdout.flush()



reference.set_dbm(reference.safe_dbm)
photonics.set_attenuation(photonics.max_att)
sys.stderr.write('done.\n')




