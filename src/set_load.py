#!/local/python3/bin/python3
'''
set_load.py     RMB 20190905

Move the load wheel to the given position.



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
logging.root.addHandler(logging.StreamHandler())
logging.root.setLevel(logging.INFO)

import argparse
parser = argparse.ArgumentParser(description='''Control the load wheel.
Examples:
  set_load.py -v home
  set_load.py b3_tone
  set_load.py 2705000''', formatter_class=argparse.RawTextHelpFormatter)
parser.add_argument('-v', '--verbose', action='store_true', help='print additional debug output')
parser.add_argument('pos', help='"home", counts, or a named position from load.ini')
args = parser.parse_args()

if args.verbose:
    logging.root.setLevel(logging.DEBUG)
    logging.debug('verbose: log level set to DEBUG')

binpath, datapath = namakanui.util.get_paths()

def mypub(n,s):
    pass

load = namakanui.load.Load(datapath+'load.ini', time.sleep, mypub)

pos = args.pos.strip()
if pos.lower() == 'home':
    logging.info('homing load controller...')
    load.home()
else:
    logging.info('moving to %s...', pos)
    load.move(pos)

load.update()
logging.info('done, load at %d: %s', load.state['pos_counts'], load.state['pos_name'])


