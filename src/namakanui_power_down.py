#!/local/python3/bin/python3
'''
namakanui_power_down.py   RMB 20190827

Set reference to a safe level, then power down all cartridges.

Run this script before turning off the FEMC to avoid sudden changes
in the SIS mixers that might cause trapped flux.


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
import namakanui.instrument
import namakanui.util
import namakanui.sim as sim
import socket
import time
import os
import sys
import argparse

import logging
namakanui.util.setup_logging()

# just for the sake of a -h message
parser = argparse.ArgumentParser(
    formatter_class=argparse.RawTextHelpFormatter,
    description=namakanui.util.get_description(__doc__)
    )
args = parser.parse_args()

# we don't care about the load here
simulate = sim.SIM_LOAD
instrument = namakanui.instrument.Instrument(simulate=simulate)

logging.info('\nDisabling reference signal and setting STSR switches to ch4')
try:
    instrument.set_safe()
except:
    logging.exception('*** WARNING reference signal may still have power ***')

for band in instrument.bands:
    logging.info('\nBand %d:', band)
    instrument.carts[band].power(0)

logging.info('\nAll cartridges powered down.')
logging.info('Now safe to turn off FEMC.')
