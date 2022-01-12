#!/local/python3/bin/python3
'''
stsr_test.py  RMB  20220111

Test the new STSR class by switching between bands and
checking the pll_ref_power (FLOOG level) at each cartridge.

At the time of writing, communication with the FEMC is still extremely slow,
so use a plain FEMC instance instead of a full Cart classes.


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
import namakanui.instrument
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

# simulate all carts, we use femc directly.
# also simulate load (rotation stage), we don't need it here.
sim_mask = sim.SIM_B3_FEMC | sim.SIM_B6_FEMC | sim.SIM_B7_FEMC | sim.SIM_LOAD
instrument = namakanui.instrument.Instrument(simulate=sim_mask, level={'stsr':logging.DEBUG})

stsr = instrument.stsr
femc = instrument.femc

pstate = pprint.pformat(stsr.state)
logging.info('STSR initial state:\n%s', pstate)

logging.info('setting reference signal power to safe levels.')
instrument.set_safe()

bands = namakanui.util.get_bands(instrument.config, simulated=False)
logging.info('using bands %s', bands)

logging.info('powering up cartridges.')
for band in bands:
    ca = band-1
    femc.set_pd_enable(ca, 1)

# end on band 0, which sets stsr switches to ch4
stsr_bands = bands + [0]
logging.info('switching between bands %s...', stsr_bands)
for band in stsr_bands:
    logging.info('\nband %d', band)
    stsr.set_band(band)
    stsr.set_tone(band)
    pstate = pprint.pformat(stsr.state)
    logging.info('STSR band %d state:\n%s', band, pstate)
    logging.info('checking FLOOG pll_ref_power...')
    for fband in bands:
        ca = fband - 1
        p = femc.get_cartridge_lo_pll_ref_total_power(ca)
        logging.info('b%d: %.3f', fband, p)

logging.info('\ndone, leaving cartridges powered up.')





