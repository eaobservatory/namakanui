#!/local/python3/bin/python3
'''
namakanui_deflux.py   RMB 20200414

Demagnetize and deflux (via mixer heating) a receiver.


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
import sys
import os
import time
import argparse
import namakanui.cart
import namakanui.util
import logging

namakanui.util.setup_logging()

binpath,datapath = namakanui.util.get_paths()

parser = argparse.ArgumentParser(
    formatter_class=argparse.RawTextHelpFormatter,
    description=namakanui.util.get_description(__doc__)
    )
parser.add_argument('band', type=int, choices=[6,7])  # TODO choices from config
parser.add_argument('--skip', choices=['demag', 'heat'])
args = parser.parse_args()

# setup cartridge
cart = namakanui.cart.Cart(args.band, datapath+'band%d.ini'%(args.band), time.sleep, namakanui.nop)
cart.log.setLevel(logging.DEBUG)  # TODO: ought to be an __init__ arg for this
cart.power(1)

if not args.skip:
    cart.demagnetize_and_deflux(heat=True)
else:
    cart.zero()
    if args.skip == 'demag':
        cart._mixer_heating()
    else:
        for po in range(2):
            for sb in range(2):
                cart._demagnetize(po,sb)

cart.update_all()
logging.info('done.')


        


