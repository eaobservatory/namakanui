#!/local/python3/bin/python3
'''
RMB 20200414
Demagnetize and deflux (via mixer heating) a receiver.
'''

import jac_sw
import sys
import os
import time
import argparse
import namakanui.cart
import namakanui.util
import logging

logging.root.setLevel(logging.INFO)
logging.root.addHandler(logging.StreamHandler())

binpath,datapath = namakanui.util.get_paths()

parser = argparse.ArgumentParser(description='''
Demagnetize and deflux a receiver.
''', formatter_class=argparse.RawTextHelpFormatter)

parser.add_argument('band', type=int, choices=[6,7])
parser.add_argument('--skip', choices=['demag', 'heat'])
args = parser.parse_args()

# setup cartridge
cart = namakanui.cart.Cart(args.band, datapath+'band%d.ini'%(args.band), time.sleep, namakanui.nop, simulate=0)
cart.log.setLevel(logging.DEBUG)  # TODO: ought to be an __init__ arg for this
cart.power(1)

if not args.skip:
    cart.demagnetize_and_deflux()
else:
    cart._set_pa([0.0]*4)
    cart._ramp_sis_bias_voltages([0.0]*4)  # harmless if not SIS mixers
    cart._ramp_sis_magnet_currents([0.0]*4)  # harmless if no SIS magnets
    if args.skip == 'demag':
        cart._mixer_heating()
    else:
        for po in range(2):
            for sb in range(2):
                cart._demagnetize(po,sb)

logging.info('done.')


        


