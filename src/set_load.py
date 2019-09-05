#!/local/python3/bin/python3
'''
set_load.py
RMB 20190905

Move the load wheel to the given position.
'''

import jac_sw
import namakanui.load
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

binpath = os.path.dirname(os.path.realpath(sys.argv[0])) + '/'
# HACK, should crawl up
if 'install' in binpath:
    datapath = os.path.realpath(binpath + '../../data') + '/'
else:
    datapath = os.path.realpath(binpath + '../data') + '/'

def mypub(n,s):
    pass

load = namakanui.load.Load(datapath+'load.ini', time.sleep, mypub, simulate=0)

pos = args.pos.strip()
if pos.lower() == 'home':
    logging.info('homing load controller...')
    load.home()
else:
    logging.info('moving to %s...', pos)
    load.move(pos)

load.update()
logging.info('done, load at %d: %s', load.state['pos_counts'], load.state['pos_name'])


