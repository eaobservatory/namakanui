#!/local/python3/bin/python3
'''
namakanui_deflux.py   RMB 20200414

Deflux a receiver by demagnetizing and heating.


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
import time
import logging
import argparse
import namakanui.femc
import namakanui.cart
import namakanui.util
import namakanui.ini


log = logging.getLogger(__name__)
skip_valid = ['demag', 'heat']


def deflux(instrument, band, skip=None):
    '''Deflux a receiver by demagnetizing and heating.
       Arguments:
        instrument: Created if None
        band: Band to deflux
        skip: If not None, which step ["demag", "heat"] to skip over
    '''
    if instrument:
        bands = instrument.bands
    else:
        config = namakanui.util.get_config()
        bands = namakanui.util.get_bands(config)
    
    band = int(band)
    if band not in bands:
        raise ValueError(f'band {band} not in {bands}')
    
    # TODO check if this band can actually be defluxed
    
    if skip and skip not in skip_valid:
        raise ValueError(f'skip {skip} not in {skip_valid}')
    
    log.info('deflux band %d, skip %s', band, skip)
    
    if instrument:
        cart = instrument.carts[band]
    else:
        femc = namakanui.femc.FEMC(config, time.sleep, namakanui.nop)
        cart = namakanui.cart.Cart(band, femc, config, time.sleep, namakanui.nop)
        cart.log.setLevel(logging.DEBUG)
    
    cart.power(1)
    if not skip:
        cart.demagnetize_and_deflux(heat=True)
    else:
        cart.zero()
        if skip == 'demag':
            cart._mixer_heating()
        else:
            for po in range(2):
                for sb in range(2):
                    cart._demagnetize(po,sb)
    cart.update_all()
    log.info('deflux done.')
    # deflux
        

if __name__ == '__main__':
    
    namakanui.util.setup_logging(logging.DEBUG)
    
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawTextHelpFormatter,
        description=namakanui.util.get_description(__doc__)
        )
    parser.add_argument('band', type=int)
    parser.add_argument('--skip', choices=skip_valid)
    args = parser.parse_args()
    
    try:
        deflux(None, **vars(args))
    except ValueError as e:
        parser.error(e)  # calls sys.exit

