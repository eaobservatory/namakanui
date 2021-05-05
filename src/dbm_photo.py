#!/local/python3/bin/python3
'''
dbm_photo.py    RMB 20191227

Create a table for the Agilent/Keysight signal generator
with the necessary output power setting to produce the desired
input power level (normally +10 dBm)
for the photonics transmission system at each frequency.

The signal generator output must be connected to a power meter, N1913A,
which is connected directly to LAN and uses SCPI commands.

NOTE: Range for the different bands, based on FLOYIG/FHIYIG:
    b3: 18.308 - 22.153
    b6: 18.325 - 22.162
    b7: 23.416 - 30.571
Typically this script will run with a simple 18:31:.01 GHz range.


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

binpath, datapath = namakanui.util.get_paths()

parser = argparse.ArgumentParser(
    formatter_class=argparse.RawTextHelpFormatter,
    description=namakanui.util.get_description(__doc__)
    )
parser.add_argument('target_dbm', type=float, choices=namakanui.util.interval(-20, 14), help='target dBm reading')
parser.add_argument('start_dbm', type=float, choices=namakanui.util.interval(-20, 14), help='starting dBm output')
parser.add_argument('ghz_range', help='synth freq range, start:end:step')
parser.add_argument('--table', nargs='?', default='', help='input power table file path, overrides start_dbm')
parser.add_argument('--deadband', nargs='?', type=float, default=0.05, help='close-enough error, default %(default)s dBm')
parser.add_argument('--note', nargs='?', default='', help='note for file header')
args = parser.parse_args()

ghz_range = namakanui.util.parse_range(args.ghz_range, maxlen=100e3)
ghz_min = min(ghz_range)
ghz_max = max(ghz_range)
if ghz_min < 16 or ghz_max > 32:
    sys.stderr.write('error: ghz_range %s outside [16, 32] range\n'%(args.ghz_range))
    sys.exit(1)

# if we have an input table, read it in
dbm_table = []
if args.table:
    dbm_table = namakanui.ini.read_ascii(args.table)

# threshold to break optimization loop
deadband = abs(args.deadband)

reference = namakanui.reference.Reference(datapath+'reference.ini', time.sleep, namakanui.nop)
reference.set_dbm(reference.safe_dbm)
reference.set_output(1)

pmeter = namakanui.pmeter.PMeter(datapath+'pmeter.ini', time.sleep, namakanui.nop)


# output file header
sys.stdout.write(time.strftime('# %Y%m%d %H:%M:%S HST\n', time.localtime()))
sys.stdout.write('# %s\n'%(sys.argv))
sys.stdout.write('#\n')
sys.stdout.flush()


def sign(x):
    if x > 0:
        return 1
    elif x < 0:
        return -1
    return 0

def do_ghz(ghz):
    '''Optimize power output for given frequency.'''
    sys.stderr.write('%.6f: '%(ghz))
    sys.stderr.flush()
    delay = 0.1  # generous sleep since pmeter takes 50ms/read
    dbm = args.start_dbm
    if dbm_table:
        interp_row = namakanui.ini.interp_table(dbm_table, ghz)
        dbm = interp_row.dbm
    reference.set_hz_dbm(ghz*1e9, dbm)
    pmeter.set_ghz(ghz)  # for power sensor calibration tables
    # assuming meter and generator are both reasonably accurate,
    # we only need to iterate a few times to get close to optimal setting.
    #
    # RMB 20200930: add some basic gain estimation to speed convergence.
    # we don't really trust the estimate, so bias toward 1.0
    # by multiplying its logarithm with a scale factor <1.
    prev_dbm = dbm
    prev_power = 0.0
    gain_bias = 0.5  # multiplied with log(gain) to skew toward 1
    for i in range(5):
        time.sleep(delay)
        power = pmeter.read_power()
        err = args.target_dbm - power
        sys.stderr.write('(%.2f, %.3f, '%(dbm, power))
        #sys.stderr.flush()
        if abs(err) <= deadband:
            break
        dout = dbm - prev_dbm
        dpow = power - prev_power
        prev_dbm = dbm
        prev_power = power
        gain = 1.0
        if dout != 0.0 and dpow != 0.0 and sign(dout) == sign(dpow):
            gain = dpow / dout
            gain = 10**(math.log10(gain)*gain_bias)
        sys.stderr.write('%.3f)'%(gain))
        sys.stderr.flush()
        dbm += err / gain
        # NOTE: even if we rail, don't bail out early -- might have overshot
        if dbm < reference.safe_dbm:
            dbm = reference.safe_dbm
        if dbm > reference.max_dbm:
            dbm = reference.max_dbm
        reference.set_dbm(dbm)
    time.sleep(delay)
    power = pmeter.read_power()
    sys.stderr.write('(%.2f, %.3f)\n'%(dbm, power))
    sys.stderr.flush()
    print('%.3f %.2f %.3f'%(ghz, dbm, power))
    sys.stdout.flush()

print('#ghz dbm pow')
for ghz in ghz_range:
    do_ghz(ghz)

reference.set_dbm(reference.safe_dbm)
sys.stderr.write('done.\n')




