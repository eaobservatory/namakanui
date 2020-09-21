#!/local/python3/bin/python3
'''
power_down.py   RMB 20190827

Set Agilent to a safe level, then power down all cartridges.
Uses the Cart class to properly disable the amplifiers
and ramp voltages and currents to 0.


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
import namakanui.agilent
import namakanui.cart
import namakanui.util
import socket
import time
import os
import sys

import logging
logging.root.addHandler(logging.StreamHandler())
logging.root.setLevel(logging.INFO)

binpath, datapath = namakanui.util.get_paths()

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
    cart = namakanui.cart.Cart(band, datapath+'band%d.ini'%(band), time.sleep, mypub)
    cart.power(0)
    

logging.info('\nall cartridges powered down.')
