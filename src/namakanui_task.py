#!/local/python3/bin/python3
'''
20181016 RMB

 86 GHz: Ala'ihi
230 GHz: U'u
345 GHz: Aweoweo

Supervisor for the three cartridge tasks.
Controls the cartridges via DRAMA commands,
but controls other hardware (load, cryostat) directly.

This is an engineering control task, and is expect to run most of the time.
The frontend tasks for ACSIS will remain separate.


'''

import jac_sw
import drama
import time
from namakanui.includeparser import IncludeParser
import namakanui.cryo
import namakanui.load
# NOTE the reference signal generator interface should be more generic.
import namakanui.agilent

import argparse
parser = argparse.ArgumentParser()
parser.add_argument('taskname')
parser.add_argument('inifile')
args = parser.parse_args()

import drama.log
drama.log.setup()  # no taskname, so no /jac_logs file output
import logging
log = logging.getLogger(args.taskname)

class Namakanui(object):
    def __init__(self):
        self.INITIALISE(

config = None
ctasks = {}
# and many other global vars.  agilent, load, cryo.
# probably this task should be classified.

def INITIALISE(msg):
    global config, ctasks
    config = IncludeParser(args.inifile)
    ctasks[3] = config['namakanui']['b3_taskname']
    ctasks[6] = config['namakanui']['b6_taskname']
    ctasks[7] = config['namakanui']['b7_taskname']
    # restart ctasks...

def UPDATE(msg):
    pass


try:
    drama.init(args.taskname, actions=[UPDATE, INITIALISE])
    drama.blind_obey(args.taskname, 'INITIALISE')
    drama.blind_obey(args.taskname, 'UPDATE')
    drama.run()
finally:
    drama.stop()

