#!/local/python3/bin/python3
'''
rfsma_test.py  RMB  20220119

Test the new RFSMA and PMeter2 classes.


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
import namakanui.rfsma
import namakanui.pmeter2
import namakanui.util
import namakanui.sim as sim
import time
import argparse
import pprint

import logging
namakanui.util.setup_logging(level=logging.DEBUG)

# just for the sake of a -h message
parser = argparse.ArgumentParser(
    formatter_class=argparse.RawTextHelpFormatter,
    description=namakanui.util.get_description(__doc__)
    )
args = parser.parse_args()

config = namakanui.util.get_config('rfsma.ini')  # holds pmeter config also
rfsma_a14 = namakanui.rfsma.RFSMA(config, 'rfsma_a14', level=logging.DEBUG)
rfsma_a17 = namakanui.rfsma.RFSMA(config, 'rfsma_a17', level=logging.DEBUG)
pmeters = []
for i in range(1,5):
    pmeters.append(namakanui.pmeter2.PMeter2(config, 'rfsma_p%d'%(i), level=logging.DEBUG))

def log_states(msg):
    logging.info('%s:', msg)
    logging.info('\n%s', pprint.pformat(rfsma_a14.state))
    logging.info('\n%s', pprint.pformat(rfsma_a17.state))
    for p in pmeters:
        logging.info('\n%s', pprint.pformat(p.state))

log_states('initial states')

logging.info('reading power for IF 4-9 GHz + FLOOG.')

rfsma_a14.set_pmeter_49()
rfsma_a17.set_pmeter_49()

# floog setting, read J15 on rfsma_p2.chB
rfsma_a14.set_DO('5056_s2', [1], 14)  # S15
rfsma_a14.set_DO('5056_s3', [0,0,1,0], 12)  # S20

p[0].set_ghz(6.5)
p[1].set_ghz(0.0315, ch=2)
p[2].set_ghz(6.5)

# test parallel power reads, might be slightly faster
for p in pmeters:
    p.read_init()

for p in pmeters:
    plist = p.read_fetch()
    p.state['power'] = plist  # for log_states

logging.info('')
log_states('IF 4-9 GHz + FLOOG states')

# TODO: test additional switch settings and power readings

logging.info('done.')

