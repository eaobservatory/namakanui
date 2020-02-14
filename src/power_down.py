#!/local/python3/bin/python3
'''
power_down.py
RMB 20190827

Set Agilent to a safe level, then power down all cartridges.
Uses the Cart class to properly disable the amplifiers
and ramp voltages and currents to 0.
'''

import jac_sw
import namakanui.agilent
import namakanui.cart
import socket
import time
import os
import sys

import logging
logging.root.addHandler(logging.StreamHandler())
logging.root.setLevel(logging.INFO)

binpath = os.path.dirname(os.path.realpath(sys.argv[0])) + '/'
# HACK, should crawl up
if 'install' in binpath:
    datapath = os.path.realpath(binpath + '../../data') + '/'
else:
    datapath = os.path.realpath(binpath + '../data') + '/'

def mypub(n,s):
    pass

logging.info('\ndisabling agilent output')
try:
    agilent = namakanui.agilent.Agilent(datapath+'agilent.ini', time.sleep, namakanui.nop)
    agilent.set_dbm(agilent.safe_dbm)
    agilent.set_output(0)
except socket.timeout as e:
    logging.warning('*** WARNING: socket.timeout, skipping agilent. ***')


for band in [3,6,7]:
    logging.info('\nband %d:', band)
    cart = namakanui.cart.Cart(band, datapath+'band%d.ini'%(band), time.sleep, mypub, simulate=0)
    cart.power(0)
    

logging.info('\nall cartridges powered down.')
