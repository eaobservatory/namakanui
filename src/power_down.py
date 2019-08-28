#!/local/python3/bin/python3
'''
power_down.py
RMB 20190827

Power down all cartridges.  Uses the Cart class to properly
disable the amplifiers and ramp voltages and currents to 0.
'''

import jac_sw
import namakanui.cart
import time
import os
import sys

import logging
logging.root.addHandler(logging.StreamHandler())
logging.root.setLevel(logging.INFO)

binpath = os.path.dirname(os.path.realpath(sys.argv[0])) + '/'
datapath = os.path.realpath(binpath + '../../data') + '/'

def mypub(n,s):
    pass

for band in [3,6,7]:
    cart = namakanui.cart.Cart(band, datapath+'band%d.ini'%(band), time.sleep, mypub, simulate=0)
    cart.power(0)

logging.info('all cartridges powered down.')
