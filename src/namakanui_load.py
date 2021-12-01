#!/local/python3/bin/python3
'''
namakanui_load.py     RMB 20190905

Control the load stage.

Examples:
    namakanui_load.py -v home  # home the stage with debug output
    namakanui_load.py b6_hot   # move ambient load over band 6 window
    namakanui_load.py 2950000  # ditto


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
import namakanui.load
import namakanui.util
import time
import os
import sys
import logging

import argparse
parser = argparse.ArgumentParser(
    formatter_class=argparse.RawTextHelpFormatter,
    description=namakanui.util.get_description(__doc__)
    )
parser.add_argument('-v', '--verbose', action='store_true', help='print additional debug output')
parser.add_argument('-l', '--list', action='store_true', help='list named positions and exit')
pos_required = '-l' not in sys.argv and '--list' not in sys.argv
pos_nargs = {True:None, False:'?'}[pos_required]
parser.add_argument('position', nargs=pos_nargs, help='"home", counts, or a named position from load.ini')
args = parser.parse_args()

level = logging.INFO
if args.verbose:
    level = logging.DEBUG
    logging.debug('verbose: log level set to DEBUG')

namakanui.util.setup_logging(level)

binpath, datapath = namakanui.util.get_paths()
load = namakanui.load.Load(datapath+'load.ini', time.sleep, namakanui.nop)
load.log.setLevel(level)

if args.list:
    import pprint
    print('named positions:')
    pprint.pprint(load.positions)
    sys.exit(0)

position = args.position.strip()
if position.lower() == 'home':
    logging.info('homing load controller...')
    load.home()
else:
    logging.info('moving to %s...', position)
    load.move(position)

load.update()
logging.info('done, load at %d: %s', load.state['pos_counts'], load.state['pos_name'])


