#!/local/python3/bin/python3
'''
trx_fast.py    20220324 RMB

Faster Trx script.  The original script wastes a great deal of time
moving the load back and forth at each tested frequency.
This version first saves all the hot powers + PA values to a separate file.
It then does all the cold powers, restoring PA settings at each freq.

File names are generated automatically using the given tag argument,
usually the start time.  This allows the script to pick up where it left off
if interrupted for some reason (e.g. by reference socket.timeout errors).

The output filename is also automatically generated,
so it is not necessary to redirect the stdout from this script.
Files are created in the current working directory, named like
    b<band>_hot_<tag>.txt
    b<band>_trx_<tag>.txt

Example:

$ trx_fast.py 6 220:265:.1 20220219.1120
$ ls *20220219.1120*
b6_hot_20220219.1120.txt
b6_trx_20220219.1120.txt


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


taskname = 'TRXF_%d'%(os.getpid())

namakanui.util.setup_logging()

binpath, datapath = namakanui.util.get_paths()

config = namakanui.util.get_config()
bands = namakanui.util.get_bands(config, simulated=False)

parser = argparse.ArgumentParser(
    formatter_class=argparse.RawTextHelpFormatter,
    description=namakanui.util.get_description(__doc__)
    )
parser.add_argument('band', type=int, choices=bands)
parser.add_argument('lo_ghz', help='LO GHz range, first:last:step')
parser.add_argument('tag', help='filename tag')
parser.add_argument('--lock_side', nargs='?', choices=['below','above'], default='above')
parser.add_argument('--level_only', action='store_true')
parser.add_argument('--note', nargs='?', default='', help='note for output file')
args = parser.parse_args()

band = args.band
los = namakanui.util.parse_range(args.lo_ghz, maxlen=100e3)

# check files, we might be done already.
hot_filename = f'b{band}_hot_{args.tag}.txt'
trx_filename = f'b{band}_trx_{args.tag}.txt'
hot_lines = []
trx_lines = []
try:
    hot_lines = open(hot_filename).readlines()
    trx_lines = open(trx_filename).readlines()
except:
    pass

def get_last_entry(lines):
    '''Return last lo_ghz in given lines, skipping comments.'''
    for line in reversed(lines):
        line = line.strip()
        if line and not line.startswith('#'):
            return float(line.split()[0])
    return None

last_hot_entry = get_last_entry(hot_lines)
last_trx_entry = get_last_entry(trx_lines)

# compare strings since file values might be truncated slightly
last_hot_str = '%g'%(last_hot_entry or 0)
last_trx_str = '%g'%(last_trx_entry or 0)
last_arg_str = '%g'%(los[-1])
if last_trx_str == last_arg_str:
    logging.info('already done, files: %s %s', hot_filename, trx_filename)
    sys.exit(0)
else:
    logging.info('%s: %s', hot_filename, last_hot_str)
    logging.info('%s: %s', trx_filename, last_trx_str)

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

# a guess for LN2 brightness temp.  TODO might be frequency-dependent.
coldk = 80.0

# number of mixer current readings to take per PA (per load)
# TODO might be able to increase this without impacting runtime due to ITIME,
# but it depends on the actual value of ppcomm_time.
ua_n = 10

# which file to finally append timestamp to
active_file = sys.stdout


def hot_loop():
    '''Write hot load PAs, DCM attens, and TPD2 readings to hot_filename.'''
    global active_file
    logging.info('hot_loop: %s', hot_filename)
    if last_hot_str == last_arg_str:
        logging.info('hot already done, skipping.')
        return
    active_file = open(hot_filename, 'a')
    f = active_file
    f.write(time.strftime('# %Y%m%d %H:%M:%S HST\n', time.localtime()))
    # pick up just past where we left off in the hot file
    if last_hot_entry:
        lo_start = ['%g'%x for x in los].index('%g'%(last_hot_entry[0])) + 1
    else:
        lo_start = 0
        if_start = 0
        bw_start = 0
        # write full file header since no entries yet
        f.write('# %s\n'%(sys.argv))
        f.write('# hot load\n')
        f.write('# NOTE ua values are actually abs(ua)\n')
        f.write('#\n')
        f.write('#lo_ghz pa0 pa1 hotk')
        mixers = ['01', '02', '11', '12']
        powers = []
        powers += ['B%d_U0'%(band)]
        powers += ['B%d_U1'%(band)]
        powers += ['B%d_L0'%(band)]
        powers += ['B%d_L1'%(band)]
        f.write(' ' + ' '.join('ua_avg_'+m for m in mixers))
        f.write(' ' + ' '.join('ua_dev_'+m for m in mixers))
        f.write(' ' + ' '.join('hot_mw_'+p for p in powers))
        f.write('\n')
        f.flush()

    # output column starting indices
    pa_index = 0
    ua_avg_index = 4
    ua_dev_index = 8
    hot_p_index = 12
    
    load.move('b%d_hot'%(band))
    
    # open a redis client to get hotk updates from LAKESHORE
    rconfig = namakanui.util.get_config('redis.ini')['redis']
    redis_prefix = rconfig['prefix']
    redis_client = redis.Redis(host=rconfig['host'], port=int(rconfig['port']),
                               db=int(rconfig['db']), decode_responses=True)
            
    for lo_ghz in los[lo_start:]:
        ua_avg = [0.0]*4
        ua_dev = [0.0]*4
        
        # HOT
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
        # fetch pmeter results
        hotp = [p for m in pmeters for p in m.read_fetch()]
        
        # collect values into a row
        pa_drain_s = cart.state['pa_drain_s']
        r = [0.0]*(hot_p_index+len(powers))
        r[0] = lo_ghz
        r[1] = pa_drain_s[0]
        r[2] = pa_drain_s[1]
        r[3] = hotk
        n = ua_n
        for j in range(4):
            # calculate mixer current avg/dev.
            # iv just saves sum(x) and sum(x^2);
            # remember stddev is sqrt(E(x^2) - E(x)^2)
            avg = ua_avg[j] / n
            dev = (ua_dev[j]/n - avg**2)**.5
            r[ua_avg_index + j] = avg
            r[ua_dev_index + j] = dev
            # convert dBm to mW
            mw = 10.0**(hotp[j]*0.1)
            r[hot_p_index + j] = mw
                
        # write out the row and update hot_lines for trx_loop
        line = ' '.join('%g'%x for x in r) + '\n'
        hot_lines.append(line)
        f.write(line)
        f.flush()
    
    f.write(time.strftime('# %Y%m%d %H:%M:%S HST\n', time.localtime()))
    redis_client.close()
    logging.info('hot_loop done: %s', hot_filename)
    # hot_loop


def trx_loop():
    '''Get hot load PAs and power readings from hot_filename;
       Reapply settings after tuning receiver,
       Read power on cold load, and save calculated Trx to trx_filename.
    '''
    global active_file
    logging.info('trx_loop: %s', trx_filename)
    active_file = open(trx_filename, 'a')
    f = active_file
    f.write(time.strftime('# %Y%m%d %H:%M:%S HST\n', time.localtime()))
    # we need these regardless of whether we write a full header or not
    mixers = ['01', '02', '11', '12']
    powers = []
    powers += ['B%d_U0'%(band)]
    powers += ['B%d_U1'%(band)]
    powers += ['B%d_L0'%(band)]
    powers += ['B%d_L1'%(band)]
    # pick up just past where we left off in the trx file
    if last_trx_entry:
        lo_start = ['%g'%x for x in los].index('%g'%(last_trx_entry)) + 1
    else:
        lo_start = 0
        # write full file header since no entries yet
        f.write('# %s\n'%(sys.argv))
        f.write('# coldk = %.3f\n'%(coldk))
        f.write('# NOTE ua values are actually abs(ua)\n')
        f.write('#\n')
        f.write('#lo_ghz pa0 pa1 hotk')
        f.write(' ' + ' '.join('ua_avg_'+m for m in mixers))
        f.write(' ' + ' '.join('ua_dev_'+m for m in mixers))
        f.write(' ' + ' '.join('hot_mw_'+p for p in powers))
        f.write(' ' + ' '.join('sky_mw_'+p for p in powers))
        f.write(' ' + ' '.join('trx_'+p for p in powers))
        f.write('\n')
        f.flush()

    # output column starting indices
    pa_index = 0
    ua_avg_index = 4
    ua_dev_index = 8
    hot_p_index = 12
    sky_p_index = hot_p_index + len(powers)
    trx_index = sky_p_index + len(powers)
    
    # index into hot_lines
    hot_index = 0
    
    load.move('b%d_sky'%(band))
    
    for lo_ghz in los[lo_start:]:
        ua_avg = [0.0]*4
        ua_dev = [0.0]*4
        
        # HOT
        # find corresponding hot entry and read values
        lo_ghz_g = float('%g'%(lo_ghz))
        hot_ghz_g = 1e9
        while hot_index < len(hot_lines):
            line = hot_lines[hot_index].strip()
            if not line or line.startswith('#'):
                hot_index += 1
                continue
            hot_ghz_g = float(line.split()[0])
            if hot_ghz_g < lo_ghz_g:
                hot_index += 1
                continue
            break
        if hot_ghz_g > lo_ghz_g:  # missing hot line (hot tune failure)
            continue
        hot_values = [float(x) for x in hot_lines[hot_index].split()]
        #lo_ghz pa0 pa1 hotk
        pa_drain_s = hot_values[1:3]
        hotk = hot_values[3]
        hotp = hot_values[hot_p_index:]
        
        # COLD
        # tune band, skipping PA since we set it ourselves
        if not tune(instrument, band, lo_ghz, skip_servo_pa=True):
            logging.error('failed to tune to %.3f ghz', lo_ghz)
            continue
        
        # set PA values from hot entries
        cart._set_pa(pa_drain_s)
        
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
        
        # fetch pmeter results and convert to mW
        coldp = [p for m in pmeters for p in m.read_fetch()]
        coldp = [10.0**(0.1*p) for p in coldp]
        
        # collect values into a row
        pa_drain_s = cart.state['pa_drain_s']
        r = [0.0]*(trx_index+len(powers))
        r[0] = lo_ghz
        r[1] = pa_drain_s[0]
        r[2] = pa_drain_s[1]
        r[3] = hotk
        n = ua_n
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
        f.write(' '.join('%g'%x for x in r) + '\n')
        f.flush()
    
    logging.info('trx_loop done: %s', trx_filename)
    # trx_loop



try:
    hot_loop()
    trx_loop()
finally:
    # final timestamp
    active_file.write(time.strftime('# %Y%m%d %H:%M:%S HST\n', time.localtime()))
    active_file.flush()
    logging.info('done')

