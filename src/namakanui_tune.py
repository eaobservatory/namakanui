#!/usr/bin/python3
'''
namakanui_tune.py   RMB 20210118

Tune a receiver band using the given parameters.


Copyright (C) 2021 East Asian Observatory

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

import logging
import argparse
import namakanui.util


def tune_args(config, band, lo_ghz, voltage=0.0,
              lock_side=None, lock_only=False, pll_if='-.8:-2.5'):
    '''Check tune args and return an argparse.Namespace object.'''
    args = argparse.Namespace()
    
    args.band = int(band)
    bands = sorted([int(b) for b in config['bands']])
    if args.band not in bands:
        raise ValueError(f'band {args.band} not in {bands}')
    
    args.lo_ghz = float(lo_ghz)
    b = str(args.band)
    cc = config[config[b]['cold']]
    wc = config[config[b]['warm']]
    mult = int(cc['Mult']) * int(wc['Mult'])
    floyig = float(wc['FLOYIG'])
    fhiyig = float(wc['FHIYIG'])
    lo_ghz_valid = namakanui.util.interval(floyig*mult, fhiyig*mult)
    if args.lo_ghz not in lo_ghz_valid:
        raise ValueError(f'lo_ghz {args.lo_ghz} not in range {lo_ghz_valid}')
    
    args.voltage = float(voltage)
    voltage_valid = namakanui.util.interval(-10, 10)
    if args.voltage not in voltage_valid:
        raise ValueError(f'voltage {args.voltage} not in range {voltage_valid}')
    
    if lock_side is not None:
        lock_side = lock_side.lower() if hasattr(lock_side, 'lower') else lock_side
        if lock_side not in {0,1,'0','1','below','above'}:
            raise ValueError(f'lock_side {lock_side} not in [0,1,below,above]')
    args.lock_side = lock_side
    
    args.lock_only = bool(lock_only)
    
    if pll_if.count(':') > 1:
        raise ValueError(f'pll_if {pll_if} range step not allowed')
    pll_if_range = namakanui.util.parse_range(pll_if, maxlen=2)
    if len(pll_if_range) < 2:
        pll_if_range.append(pll_if_range[0])
    pll_if_valid = namakanui.util.interval(-0.5, -3.0)
    if pll_if_range[0] not in pll_if_valid or pll_if_range[1] not in pll_if_valid:
        raise ValueError(f'pll_if {pll_if_range} not in range {pll_if_valid}')
    args.pll_if_range = pll_if_range
    
    return args
    # tune_args


if __name__ == '__main__':
    import namakanui.ini
    binpath, datapath = namakanui.util.get_paths()
    config = namakanui.ini.IncludeParser(datapath+'instrument.ini')
    bands = sorted([int(b) for b in config['bands']])
    
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawTextHelpFormatter,
        description = __doc__[__doc__.find('Tune'):__doc__.find('Copyright')]
        )
    parser.add_argument('band', type=int)
    parser.add_argument('lo_ghz', type=float)
    parser.add_argument('--lock_only', help='do not adjust mixer params after locking',
                        action='store_true')
    parser.add_argument('--lock_side', help='lock LO {%(choices)s} reference signal',
                        nargs='?', choices=['below','above'], metavar='side')
    parser.add_argument('--pll_if', help='target PLL IF power (default %(default)s)',
                        nargs='?', default='-.8:-2.5', metavar='range')
    parser.add_argument('--voltage', help='target PLL control voltage (default %(default)s)',
                        type=float, nargs='?', default=0.0, metavar='volts',
                        choices=namakanui.util.interval(-10,10))
    args = parser.parse_args()
    
    try:
        args = tune_args(config, **vars(args))
    except ValueError as e:
        parser.error(e)  # calls sys.exit
    
    namakanui.util.setup_logging()
    logging.root.setLevel(logging.DEBUG)
    
    logging.debug('args: %s', args)
    
    import namakanui.instrument
    instrument = namakanui.instrument.Instrument(config)
    instrument.tune(**vars(args))

