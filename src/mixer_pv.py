#!/local/python3/bin/python3
'''
mixer_pv.py     RMB 20220412

Generate pumped and unpumped IV and PV curves for the given band and frequency.
By default, the hot load is moved into the beam during the test.
Results are written to stdout, and also plotted (with matplotlib) if --plot.


Copyright (C) 2022 East Asian Observatory

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
import logging
import argparse
import namakanui.instrument
import namakanui.util
from namakanui_tune import tune

taskname = 'NPV_%d'%(os.getpid())

namakanui.util.setup_logging()

config = namakanui.util.get_config()
bands = namakanui.util.get_bands(config, simulated=False, has_sis_mixers=True)

parser = argparse.ArgumentParser(
    formatter_class=argparse.RawTextHelpFormatter,
    description=namakanui.util.get_description(__doc__)
    )
parser.add_argument('band', type=int, choices=bands)
parser.add_argument('lo_ghz', type=float)
parser.add_argument('--mv', nargs='?', default='-5:5:.05', help='bias voltage range in mV, min:max:step, default %(default)s')
parser.add_argument('--n', type=int, nargs='?', default=10, help='uA avg samples, default %(default)s')
parser.add_argument('--plot', action='store_true', help='show matplotlib plot')
parser.add_argument('--mw', action='store_true', help='convert dBm to mW')
parser.add_argument('--load', nargs='?', default='hot', help='load in beam, default %(default)s')
parser.add_argument('--lock_side', nargs='?', choices=['below','above'], default='above', help='PLL lock %(choices)s reference signal, default %(default)s')
parser.add_argument('--note', nargs='?', default='', help='note for file header')
args = parser.parse_args()

lo_range = namakanui.util.get_band_lo_range(args.band, config)
if args.lo_ghz not in lo_range:
    parser.error('lo_ghz %g not in range %s'%(args.lo_ghz, lo_range))  # calls sys.exit

mv_range = namakanui.util.parse_range(args.mv)
mv_step = abs(mv_range[-1] - mv_range[0])
if len(args.mv) > 1:
    mv_step = abs(mv_range[1] - mv_range[0])
mv_step_limit = 0.05
mv_ramp = mv_step > mv_step_limit
if mv_ramp:
    logging.warning(f'mv step {mv_step} > {mv_step_limit}, ramping between steps may be slow')

if args.load == 'hot' or args.load == 'sky':
    args.load = 'b%d_'%(args.band) + args.load

pmeters = namakanui.util.init_rfsma_pmeters_49()

instrument = namakanui.instrument.Instrument(config)
instrument.set_safe()
instrument.set_band(args.band)
instrument.load.move(args.load)
cart = instrument.carts[args.band]
cart.power(1)
cart.set_lock_side(args.lock_side)

if not tune(instrument, args.band, args.lo_ghz):
    raise RuntimeError('failed to tune band %d to lo_ghz %g'%(args.band, args.lo_ghz))

# write out a header for our output file
sys.stdout.write(time.strftime('# %Y%m%d %H:%M:%S HST\n', time.localtime()))
sys.stdout.write('# %s\n'%(args))
sys.stdout.write('# pa_drain_s: %s\n'%(cart.state['pa_drain_s']))
sys.stdout.write('# "on" = pumped LO, "off" = unpumped LO\n')
sys.stdout.write('#\n')
sys.stdout.write('#mv')
mixers = ['01', '02', '11', '12']
powers = []
powers += ['B%d_U0'%(args.band)]
powers += ['B%d_U1'%(args.band)]
powers += ['B%d_L0'%(args.band)]
powers += ['B%d_L1'%(args.band)]
plabel = 'dbm'
if args.mw:
    plabel = 'mw'
sys.stdout.write(' ' + ' '.join('on_mv_'+m for m in mixers))
sys.stdout.write(' ' + ' '.join('on_ua_'+m for m in mixers))
#sys.stdout.write(' ' + ' '.join('ua_dev_'+m for m in mixers))
sys.stdout.write(' ' + ' '.join(f'on_{plabel}_'+p for p in powers))
sys.stdout.write(' ' + ' '.join('off_mv_'+m for m in mixers))
sys.stdout.write(' ' + ' '.join('off_ua_'+m for m in mixers))
#sys.stdout.write(' ' + ' '.join('ua_dev_'+m for m in mixers))
sys.stdout.write(' ' + ' '.join(f'off_{plabel}_'+p for p in powers))
sys.stdout.write('\n')
sys.stdout.flush()

# for plotting, also save columns
on_mv = [[] for m in mixers]
on_ua = [[] for m in mixers]
on_p = [[] for p in powers]
off_mv = [[] for m in mixers]
off_ua = [[] for m in mixers]
off_p = [[] for p in powers]




def mv_sweep(which):
    '''Sweep across mv_range, returning list of rows with (V, I, Idev, P)'''
    ptime = time.time()
    rows = []
    logging.info('mv_sweep: %s', which)
    logging.info('ramping bias voltages to %g mv', mv_range[0])
    cart._ramp_sis_bias_voltages([mv_range[0]]*4)
    for mv in mv_range:
        ua_avg = [0.0]*4
        ua_dev = [0.0]*4
        p = [0.0]*len(dcms)
        
        t = time.time()
        if t - ptime > 2.0:
            ptime = t
            logging.info('progress: mv %g', mv)
        
        # set mv, ramping only if necessary
        if mv_ramp:
            cart._ramp_sis_bias_voltages([mv]*4)
        else:
            for i in range(4):
                cart.femc.set_sis_voltage(cart.ca, i//2, i%2, mv - cart.bias_error[i])
            for i in range(4):
                cart.state['sis_v'][i] = cart.femc.get_sis_voltage(cart.ca, i//2, i%2)
        
        # start pmeter reads
        for m in pmeters:
            m.read_init()
        
        # collect mixer current readings
        for j in range(args.n):
            for po in range(2):
                for sb in range(2):
                    ua = cart.femc.get_sis_current(cart.ca,po,sb)*1e3
                    ua_avg[po*2 + sb] += ua
                    ua_dev[po*2 + sb] += ua*ua
        
        # fetch pmeter results and convert dBm to mW
        p = [x for m in pmeters for x in m.read_fetch()]
        if args.mw:
            p = [10.0**(0.1*x) for x in p]
        
        # calculate mixer current avg/dev.
        # iv just saves sum(x) and sum(x^2);
        # remember stddev is sqrt(E(x^2) - E(x)^2)
        n = args.n
        for j in range(4):
            avg = ua_avg[j] / n
            dev = (ua_dev[j]/n - avg**2)**.5
            ua_avg[j] = avg
            ua_dev[j] = dev
        
        # update plotting columns
        if which == 'on':
            mv_cols = on_mv
            ua_cols = on_ua
            p_cols = on_p
        else:
            mv_cols = off_mv
            ua_cols = off_ua
            p_cols = off_p
        for i in range(4):
            mv_cols[i].append(cart.state['sis_v'][i])
            ua_cols[i].append(ua_avg[i])
        for i,v in enumerate(p):
            p_cols[i].append(v)
        
        # assemble and append a row string
        r = ''#f'{mv:g}'
        r += ' ' + ' '.join(['%g'%(x) for x in cart.state['sis_v']])
        r += ' ' + ' '.join(['%g'%(x) for x in ua_avg])
        r += ' ' + ' '.join(['%g'%(x) for x in p])
        rows.append(r)
    
    logging.info('ramping bias voltages to 0 mv')
    cart._ramp_sis_bias_voltages([0.0]*4)
    return rows
    # mv_sweep



try:
    # do sweeps
    on_rows = mv_sweep('on')
    cart._set_pa([0.0]*4)
    off_rows = mv_sweep('off')
    # write to stdout
    for i,mv in enumerate(mv_range):
        sys.stdout.write('%g'%(mv))
        sys.stdout.write(on_rows[i])
        sys.stdout.write(off_rows[i])
        sys.stdout.write('\n')
finally:
    # final timestamp
    sys.stdout.write(time.strftime('# %Y%m%d %H:%M:%S HST\n', time.localtime()))
    sys.stdout.flush()
    logging.info('sweeps done.')


if not args.plot:
    logging.info('done.')
    sys.exit(0)

from pylab import *
for i in range(4):
    plot(mv_range, on_ua[i], label='on_ua_'+mixers[i])
for i in range(4):
    plot(mv_range, off_ua[i], label='off_ua_'+mixers[i])
for i,p in enumerate(on_p):
    plot(mv_range, p, label='on_p_'+powers[i])
for i,p in enumerate(off_p):
    plot(mv_range, p, label='off_p_'+powers[i])
xlabel('mv')
ylabel('ua / '+plabel)
grid()
legend()
show()

logging.info('done.')

