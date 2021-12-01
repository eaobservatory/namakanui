#!/local/python3/bin/python3
'''
temp_mon.py     RMB 20190827

Simple temperature monitor for Namakanui cartridges.
Uses direct FEMC communication instead of Cart class.
Logs to /jac_logs/namakanui_temp.log.


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
import namakanui.util
import epics
import time
import datetime
import logging
import sys

# if running in a terminal, be verbose
if sys.stdout.isatty():
    namakanui.util.setup_logging()

binpath, datapath = namakanui.util.get_paths()
femc = namakanui.femc.FEMC(datapath+'femc.ini', time.sleep, namakanui.nop)
filename = '/jac_logs/namakanui_temp.log'
logfile = open(filename, 'a')
logging.info('logging to file %s', filename)

# power up the cartridges.
# note this will skip demag/deflux by a later Cart instance.
# TODO get bands from config
logging.info('enabling (powering up) cartridges...')
for ca in [2,5,6]:
    if not femc.get_pd_enable(ca):
        print('enabling band %d...'%(ca+1))
        femc.set_pd_enable(ca, 1)
        time.sleep(1)  # still not sure exactly how long we need to sleep here

# 20200103: added this sleep to avoid -5 errors from b7 CC.
logging.info('sleeping 2s...')
time.sleep(2)

logfile.write('#hst ')
logfile.write('b3_pll b3_110k b3_p01 b3_15k b3_wca ')
logfile.write('b6_pll b6_4k b6_110k b6_p0 b6_15k b6_p1 ')
logfile.write('b7_pll b7_4k b7_110k b7_p0 b7_15k b7_p1\n')
logfile.flush()

# NOTE 20200228: In our version of pyepics,
# caput doesn't return a value or raise errors on failure.  best effort only
epics_timeout = 1.0

while True:
    d = datetime.datetime.now()
    logstr = '%s '%(d.isoformat(timespec='seconds'))
    logging.info('')
    logging.info(d)
    for ca in [2,5,6]:
        pll = femc.get_cartridge_lo_pll_assembly_temp(ca)
        pll += 273.15
        logstr += '%.3f '%(pll)
        recname = 'b%d_pll'%(ca+1)
        logging.info('')
        logging.info('%-7s: %7.3f K' % (recname, pll))
        epics.caput('nmnCryo:'+recname+'.VAL', pll, timeout=epics_timeout)
        tnames = ['4k', '110k', 'p0', 'spare', '15k', 'p1']
        if ca == 2:
            tnames = ['spare', '110k', 'p01', 'spare', '15k', 'wca']
        for i,tname in enumerate(tnames):
            if tname == 'spare':
                continue
            t = femc.get_cartridge_lo_cartridge_temp(ca, i)
            logstr += '%.3f '%(t)
            recname = 'b%d_%s'%(ca+1,tname)
            logging.info('%-7s: %7.3f K' % (recname, t))
            epics.caput('nmnCryo:'+recname+'.VAL', t, timeout=epics_timeout)
    logstr += '\n'
    logfile.write(logstr)
    logfile.flush()
    logging.info('')
    time.sleep(60.0)




