#!/local/python3/bin/python3
'''
temp_mon.py
RMB 20190827

Simple temperature monitor for Namakanui cartridges.
Uses direct FEMC communication instead of Cart class.
Logs to /jac_logs/namakanui_temp.log.
'''

import jac_sw
import namakanui.femc
import time
import datetime

femc = namakanui.femc.FEMC()
filename = '/jac_logs/namakanui_temp.log'
log = open(filename, 'a')
print('logging to file', filename)

# power up the cartridges.
# note this will skip demag/deflux by a later Cart instance.
print('enabling (powering up) cartridges...')
for ca in [2,5,6]:
    if not femc.get_pd_enable(ca):
        print('enabling band %d...'%(ca+1))
        femc.set_pd_enable(ca, 1)
        time.sleep(1)  # still not sure exactly how long we need to sleep here

# 20200103: added this sleep to avoid -5 errors from b7 CC.
print('sleeping 2s...')
time.sleep(2)

log.write('#hst ')
log.write('b3_pll b3_110k b3_p01 b3_15k b3_wca ')
log.write('b6_pll b6_4k b6_110k b6_p0 b6_15k b6_p1 ')
log.write('b7_pll b7_4k b7_110k b7_p0 b7_15k b7_p1\n')
log.flush()

while True:
    d = datetime.datetime.now()
    log.write('%s '%(d.isoformat(timespec='seconds')))
    print('')
    print(d)
    for ca in [2,5,6]:
        pll = femc.get_cartridge_lo_pll_assembly_temp(ca)
        pll += 273.15
        log.write('%.3f '%(pll))
        print('')
        print('%-7s: %7.3f K' % ('b%d_pll'%(ca+1), pll))
        tnames = ['4k', '110k', 'p0', 'spare', '15k', 'p1']
        if ca == 2:
            tnames = ['spare', '110k', 'p01', 'spare', '15k', 'wca']
        for i,tname in enumerate(tnames):
            if tname == 'spare':
                continue
            t = femc.get_cartridge_lo_cartridge_temp(ca, i)
            log.write('%.3f '%(t))
            print('%-7s: %7.3f K' % ('b%d_%s'%(ca+1,tname), t))
    log.write('\n')
    log.flush()
    print('')
    time.sleep(60.0)




