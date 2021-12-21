#!/local/python3/bin/python3
'''
namakanui_temp_mon.py     RMB 20190827

Simple temperature monitor for Namakanui cartridges.
Uses direct FEMC communication instead of Cart class.
Logs to /jac_logs/namakanui_temp.log.

RMB 20211213: Updates for the GLT.  Since we're not using
EPICS/engarchive anymore, this script also directly monitors the
Sumitomo coldhead compressor status, Lakeshore cryostat temperatures,
and Pfeiffer vacuum gauge.  This is still not a DRAMA task;
instead, all data is published to the Redis database.


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
import namakanui.femc
import namakanui.compressor
import namakanui.lakeshore
import namakanui.pfeiffer
import namakanui.util
import redis
import json
import time
from datetime import datetime as dt
import logging
import sys

# if running in a terminal, be verbose
if sys.stdout.isatty():
    namakanui.util.setup_logging()

config = namakanui.util.get_config('temp_mon.ini')

# TODO: do we still even want this file output?
#       should it also include other hw status?
filename = '/jac_logs/namakanui_temp.log'
logfile = open(filename, 'a')
logging.info('logging to file %s', filename)

# connect to redis database
rconfig = config['redis']
redis_client = redis.Redis(host=rconfig['host'], port=int(rconfig['port']),
                           db=int(rconfig['db']), decode_responses=True)
redis_prefix = rconfig['prefix']

def publish(name, value):
    '''
    Update Redis database.  Add value to zset with score=utcnow,
    and publish on channel with the same name to alert any subscribers.
    '''
    score = float(dt.utcnow().timestamp())
    # insert score into value to ensure uniqueness
    value['utc_stamp'] = score
    redis_client.zadd(redis_prefix + name, {json.dumps(value): score})
    redis_client.publish(redis_prefix + name, score)
    
# create hardware instances
compressor = namakanui.compressor.Compressor(config, time.sleep, publish)
lakeshore = namakanui.lakeshore.Lakeshore(config, time.sleep, publish)
vacuum = namakanui.pfeiffer.Pfeiffer(config, time.sleep, publish)

femc = namakanui.femc.FEMC(config, time.sleep, namakanui.nop)

# power up the cartridges.
# TODO get bands from config
if femc.simulate:
    logging.info('femc simulated, skipping cartridge power-up.')
else:
    logging.info('enabling (powering up) cartridges...')
    for ca in [2,5,6]:
        if not femc.get_pd_enable(ca):
            logging.info('enabling band %d...'%(ca+1))
            femc.set_pd_enable(ca, 1)
            time.sleep(1)  # still not sure exactly how long we need to sleep here

# 20200103: added this sleep to avoid -5 errors from b7 CC.
logging.info('sleeping 2s...')
time.sleep(2)

logfile.write('#utc ')
logfile.write('b3_pll b3_110k b3_p01 b3_15k b3_wca ')
logfile.write('b6_pll b6_4k b6_110k b6_p0 b6_15k b6_p1 ')
logfile.write('b7_pll b7_4k b7_110k b7_p0 b7_15k b7_p1\n')
logfile.flush()

while True:
    d = dt.utcnow()
    logstr = '%s '%(d.isoformat(timespec='seconds'))
    logging.info('')
    logging.info(d)
    tdict = {}
    for ca in [2,5,6]:
        if femc.simulate:
            pll = 0.0
        else:
            pll = femc.get_cartridge_lo_pll_assembly_temp(ca)
        pll += 273.15
        logstr += '%.3f '%(pll)
        recname = 'b%d_pll'%(ca+1)
        tdict[recname] = pll
        logging.info('')
        logging.info('%-7s: %7.3f K' % (recname, pll))
        # RMB 20211220: B6 readout order is different at GLT
        tnames = ['4k', '110k', 'spare', 'p0', '15k', 'p1']
        if ca == 2:
            tnames = ['spare', '110k', 'p01', 'spare', '15k', 'wca']
        for i,tname in enumerate(tnames):
            if tname == 'spare':
                continue
            if femc.simulate:
                t = 0.0
            else:
                t = femc.get_cartridge_lo_cartridge_temp(ca, i)
            logstr += '%.3f '%(t)
            recname = 'b%d_%s'%(ca+1,tname)
            tdict[recname] = t
            logging.info('%-7s: %7.3f K' % (recname, t))
    logstr += '\n'
    logfile.write(logstr)
    logfile.flush()
    logging.info('')
    publish('BANDTEMPS', tdict)
    
    compressor.update()
    lakeshore.update()
    vacuum.update()
    
    time.sleep(60.0)




