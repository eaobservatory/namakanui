#!/local/python3/bin/python3
'''
trx_slow.py    20220324 RMB

Tune to a range of frequencies and calculate Trx at each one.
Unfortunately this script will spend most of its time just moving
the load around; see trx_fast.py for a quicker method.

TODO: b3 support, may require skipping mixer ua.


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
import redis
import sys
import os
import time
import logging
import argparse
import namakanui.instrument
import namakanui.util
from namakanui_tune import tune


taskname = 'TRXS_%d'%(os.getpid())

namakanui.util.setup_logging()

binpath, datapath = namakanui.util.get_paths()

config = namakanui.util.get_config()
bands = namakanui.util.get_bands(config, simulated=False)#, has_sis_mixers=True)

parser = argparse.ArgumentParser(
    formatter_class=argparse.RawTextHelpFormatter,
    description=namakanui.util.get_description(__doc__)
    )
parser.add_argument('band', type=int, choices=bands)
parser.add_argument('lo_ghz', help='LO GHz range, first:last:step')
parser.add_argument('lock_side', nargs='?', choices=['below','above'], default='above')
parser.add_argument('--level_only', action='store_true')
parser.add_argument('--note', nargs='?', default='', help='note for output file')
args = parser.parse_args()

band = args.band
los = namakanui.util.parse_range(args.lo_ghz, maxlen=100e3)

instrument = namakanui.instrument.Instrument(config)
instrument.set_safe()
instrument.set_band(args.band)
instrument.load.move('b%d_hot'%(args.band))
cart = instrument.carts[band]
cart.power(1)
cart.set_lock_side(args.lock_side)

# tune to a central frequency as a first test
lo_ghz = los[len(los)//2]
if not tune(instrument, band, lo_ghz):
    logging.error('failed to tune to %.3f ghz', lo_ghz)
    sys.exit(1)

load = instrument.load  # shorten name

pmeters = namakanui.util.init_rfsma_pmeters_49()

rconfig = namakanui.util.get_config('redis.ini')['redis']
redis_prefix = rconfig['prefix']
redis_client = redis.Redis(host=rconfig['host'], port=int(rconfig['port']),
                            db=int(rconfig['db']), decode_responses=True)

# a guess for LN2 brightness temp.  TODO might be frequency-dependent.
coldk = 80.0

# write out a header for our output file
sys.stdout.write(time.strftime('# %Y%m%d %H:%M:%S HST\n', time.localtime()))
sys.stdout.write('# %s\n'%(sys.argv))
sys.stdout.write('# coldk = %.3f\n'%(coldk))
sys.stdout.write('# NOTE ua values are actually abs(ua)\n')
sys.stdout.write('#\n')
sys.stdout.write('#lo_ghz pa0 pa1 hotk')
mixers = ['01', '02', '11', '12']
powers = []
powers += ['B%d_U0'%(band)]
powers += ['B%d_U1'%(band)]
powers += ['B%d_L0'%(band)]
powers += ['B%d_L1'%(band)]
sys.stdout.write(' ' + ' '.join('ua_avg_'+m for m in mixers))
sys.stdout.write(' ' + ' '.join('ua_dev_'+m for m in mixers))
sys.stdout.write(' ' + ' '.join('hot_mw_'+p for p in powers))
sys.stdout.write(' ' + ' '.join('sky_mw_'+p for p in powers))
sys.stdout.write(' ' + ' '.join('trx_'+p for p in powers))
sys.stdout.write('\n')
sys.stdout.flush()

# output column starting indices
pa_index = 0
ua_avg_index = 4
ua_dev_index = 8
hot_p_index = 12
sky_p_index = hot_p_index + len(powers)
trx_index = sky_p_index + len(powers)

# number of mixer current readings to take per PA (per load)
# TODO might be able to increase this without impacting runtime due to ITIME,
# but it depends on the actual value of ppcomm_time.
ua_n = 10


def main_loop():
    for lo_ghz in los:
        ua_avg = [0.0]*4
        ua_dev = [0.0]*4
        
        # HOT
        load.move('b%d_hot'%(band))
        if not tune(instrument, band, lo_ghz):
            logging.error('failed to tune to %.3f ghz', lo_ghz)
            continue
        # start pmeter reads
        for m in pmeters:
            m.read_init()
        # collect mixer current readings
        for j in range(ua_n):
            for po in range(2):
                for sb in range(2):
                    ua = cart.femc.get_sis_current(cart.ca,po,sb)*1e3
                    ua_avg[po*2 + sb] += abs(ua)  # for band 6
                    ua_dev[po*2 + sb] += ua*ua
        # get hot load temperature from last redis LAKESHORE entry
        s = redis_client.zrange(redis_prefix + 'LAKESHORE', -1, -1)[0]
        hotk = json.loads(s)['temp'][4]
        # fetch pmeter results and convert dBm to mW
        hotp = [p for m in pmeters for p in m.read_fetch()]
        hotp = [10.0**(0.1*p) for p in hotp]
        
        # COLD
        load.move('b%d_sky'%(band))
        # start pmeter reads
        for m in pmeters:
            m.read_init()
        # collect mixer current readings
        for j in range(ua_n):
            for po in range(2):
                for sb in range(2):
                    ua = cart.femc.get_sis_current(cart.ca,po,sb)*1e3
                    ua_avg[po*2 + sb] += abs(ua)  # for band 6
                    ua_dev[po*2 + sb] += ua*ua
        # fetch pmeter results and convert dBm to mW
        coldp = [p for m in pmeters for p in m.read_fetch()]
        coldp = [10.0**(0.1*p) for p in coldp]
        
        # collect values into a row
        pa_drain_s = cart.state['pa_drain_s']
        r = [0.0]*(trx_index+len(powers))
        r[0] = lo_ghz
        r[1] = pa_drain_s[0]
        r[2] = pa_drain_s[1]
        r[3] = hotk
        n = ua_n*2
        for j in range(4):
            # calculate mixer current avg/dev.
            # iv just saves sum(x) and sum(x^2);
            # remember stddev is sqrt(E(x^2) - E(x)^2)
            avg = ua_avg[j] / n
            dev = (ua_dev[j]/n - avg**2)**.5
            r[ua_avg_index + j] = avg
            r[ua_dev_index + j] = dev
        for j in range(len(powers)):
            # calc Trx.
            r[hot_p_index + j] = hotp[j]
            r[sky_p_index + j] = coldp[j]
            y = hotp[j]/coldp[j]
            r[trx_index + j] = y*(hotk - coldk)/(y-1) - hotk
                
        # write out the row
        sys.stdout.write(' '.join('%g'%x for x in r) + '\n')
        sys.stdout.flush()
    
    # main_loop


try:
    main_loop()
finally:
    # final timestamp
    sys.stdout.write(time.strftime('# %Y%m%d %H:%M:%S HST\n', time.localtime()))
    sys.stdout.flush()
    logging.info('done')

