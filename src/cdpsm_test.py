#!/local/python3/bin/python3
'''
cdpsm_test.py  RMB  20220120

Test the new CDPSM (Continuum Detector & Phase Stability Monitor) class.



Copyright (C) 2022 East Asian Observatory

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
import namakanui.cdpsm
import namakanui.pmeter2
import namakanui.util
import namakanui.sim as sim
import time
import argparse
import pprint

import logging
namakanui.util.setup_logging(level=logging.DEBUG)

parser = argparse.ArgumentParser(
    formatter_class=argparse.RawTextHelpFormatter,
    description=namakanui.util.get_description(__doc__)
    )
parser.add_argument('--lhc', nargs='?', default='usb', help='SW1 LHC source, [USB]/LSB')
parser.add_argument('--rhc', nargs='?', default='usb', help='SW2 RHC source, [USB]/LSB')
parser.add_argument('--pol', nargs='?', default='lhc', help='SW3 polarization source, [LHC]/RHC')
parser.add_argument('--band', nargs='?', default='3', help='SW456 analysis signal band, [3]/6/7')
args = parser.parse_args()

config = namakanui.util.get_config('cdpsm.ini')  # holds pmeter config also
cdpsm = namakanui.cdpsm.CDPSM(config, level=logging.DEBUG)
pmeter = namakanui.pmeter2.PMeter2(config, 'cdpsm_p5', level=logging.DEBUG)

def log_states(msg):
    logging.info('%s:', msg)
    logging.info('\n%s', pprint.pformat(cdpsm.state))
    logging.info('\n%s', pprint.pformat(pmeter.state))

log_states('initial states')

logging.info('setting switches for args: %s', args)
cdpsm.set_LHC_source(args.lhc)
cdpsm.set_RHC_source(args.rhc)
cdpsm.set_polarization(args.pol)
cdpsm.set_band(args.band)

pmeter.update()

log_states('final states')

logging.info('done.')

