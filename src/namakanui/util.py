'''
RMB 20200227
Utility functions for scripts.
'''

import sys
import os
import logging
import time

def get_paths():
    '''Return binpath and datapath for this script.'''
    if sys.argv[0]:
        binpath = os.path.dirname(os.path.realpath(sys.argv[0])) + '/'
    else:
        binpath = os.path.realpath('') + '/'
    # crawl up parent directories looking for data dir
    crawl = binpath[:-1]
    while crawl:
        datapath = crawl + '/data/'
        if os.path.exists(datapath):
            break
        crawl = crawl.rpartition('/')[0]
    if not crawl:  # we don't accept /data at root
        raise RuntimeError('no data path found from bin path %s'%(binpath))
    return binpath, datapath
    

def parse_range(s, maxlen=0):
    '''
    Parse string s in "first:last:step" format and return array of values.
    The "last" and "step" are optional:
        "first" -> [first]
        "first:last" -> [first, last]
    If first > last, automatic negative step.
    '''
    s = s.split(':')
    first = float(s[0])
    if len(s) == 1:
        return [first]
    last = float(s[1])
    if len(s) == 2:
        return [first, last]
    diff = last - first
    if diff == 0.0:
        return [first]
    step = abs(float(s[2]))
    if step == 0.0:
        return [first, last]
    if diff < 0.0:
        step = -step
    alen = int(round(diff/step + 1))
    if maxlen and alen > maxlen:
        raise ValueError('step too small, array len %d > maxlen %d'%(alen,maxlen))
    arr = []
    val = first
    while (step > 0 and val < last) or (step < 0 and val > last):
        arr.append(val)
        val += step
    if abs(arr[-1] - last) < abs(step)*1e-6:
        arr[-1] = last
    else:
        arr.append(last)
    return arr


def get_dcms(rx):
    '''Given receiver name rx, return array of DCM numbers from cm_wire_file.txt'''
    dcms = []
    for line in open('/jac_sw/hlsroot/acsis_prod/wireDir/acsis/cm_wire_file.txt'):
        line = line.strip()
        if not line:
            continue
        if line.startswith('#'):
            continue
        line = line.split()
        if rx in line:
            dcms.append(int(line[0]))
    return dcms


def clip(value, minimum, maximum):
    '''Return value restricted to [minimum, maximum] range'''
    if value < minimum:
        return minimum
    if value > maximum:
        return maximum
    return value


def _try_tune(cart, lo_ghz, dbm, skip_servo_pa, log):
    '''Helper function used by tune() to catch and log exceptions.'''
    log.info('cart.tune %.3f ghz, %.2f dbm', lo_ghz, dbm)
    try:
        cart.tune(lo_ghz, 0.0, skip_servo_pa=skip_servo_pa)
    except RuntimeError as e:
        log.error('tune failed at %.3f ghz, dbm %.2f', lo_ghz, dbm)
    cart.update_all()


def _try_dbm(cart, agilent, lo_ghz, dbm, skip_servo_pa, delay_secs, sleep, log):
    '''Helper function used by tune(); set a new dbm and retune if needed.'''
    agilent.set_dbm(dbm)
    sleep(delay_secs)
    agilent.update()
    cart.update_all()
    if cart.state['pll_unlock']:
        _try_tune(cart, lo_ghz, dbm, skip_servo_pa, log)


def tune(cart, agilent, lo_ghz,
         use_ini=True, dbm_range=None, pll_range=[-.8,-2.5],
         skip_servo_pa=False, sleep=time.sleep, log=logging):
    '''
    Tune the receiver and optimize PLL IF power by adjusting agilent output power.
    Returns True on success, False on failure.
    Parameters:
      cart: Cart class instance
      agilent: Agilent class instance
      lo_ghz: Frequency to tune to
      use_ini: If True, dbm_range is relative to interpolated table value
      dbm_range: [start_dbm, max_dbm].  List or either value can be None:
        start_dbm: If None, is (use_ini ? 0 : agilent.safe_dbm)
        max_dbm: If None, is (use_ini ? 3 : agilent.max_dbm)
      pll_range: [min_power, max_power].
      skip_servo_pa: If true, PA not adjusted for target mixer current.
      sleep: Sleep function
      log: logging.Logger class instance
    '''
    log.info('tuning to %.3f ghz...', lo_ghz)
    delay_secs = 0.05
    # TODO this needs to be easily accessible from cart instance.
    # presently must manually set after initialise and doesn't update state.
    lock_polarity = cart.femc.get_cartridge_lo_pll_sb_lock_polarity_select(cart.ca)
    floog = agilent.floog * [1.0, -1.0][lock_polarity]  # [below, above]
    fyig = lo_ghz / (cart.cold_mult * cart.warm_mult)
    fsig = (fyig*cart.warm_mult + floog) / agilent.harmonic
    if use_ini:
        start_dbm = agilent.interp_dbm(cart.band, lo_ghz)
        max_dbm = start_dbm + 3.0
        if dbm_range:
            if dbm_range[1] is not None:
                max_dbm = start_dbm + dbm_range[1]
            if dbm_range[0] is not None:
                start_dbm += dbm_range[0]
    else:
        start_dbm = agilent.safe_dbm
        max_dbm = agilent.max_dbm
        if dbm_range:
            if dbm_range[0] is not None:
                start_dbm = dbm_range[0]
            if dbm_range[1] is not None:
                max_dbm = dbm_range[1]
    # restrict start/max dbm to valid range
    start_dbm = clip(start_dbm, agilent.safe_dbm, agilent.max_dbm)
    max_dbm = clip(max_dbm, agilent.safe_dbm, agilent.max_dbm)
    log.info('start_dbm: %.2f, max_dbm: %.2f', start_dbm, max_dbm)
    # make sure pll_range signs and order are correct (must exist)
    pll_range = [-abs(pll_range[0]), -abs(pll_range[1])]
    pll_range.sort()
    pll_range.reverse()
    log.info('pll_range: [%.2f, %.2f]', pll_range[0], pll_range[1])
    dbm = start_dbm
    hz = fsig*1e9
    #log.info('start dbm: %.2f', dbm)
    log.info('agilent hz: %.1f', hz)
    agilent.set_hz_dbm(hz, dbm)  # sets hz/dbm in proper order for safety
    sleep(delay_secs)
    agilent.update()
    _try_tune(cart, lo_ghz, dbm, skip_servo_pa, log)
    # quickly increase power if needed
    while (cart.state['pll_unlock'] or cart.state['pll_if_power'] > pll_range[0]) and dbm < max_dbm:
        dbm += 1.0
        if dbm > max_dbm:
            dbm = max_dbm
        log.info('unlock: %d, pll_if: %.3f; increasing dbm to %.2f', cart.state['pll_unlock'], cart.state['pll_if_power'], dbm)
        _try_dbm(cart, agilent, lo_ghz, dbm, skip_servo_pa, delay_secs, sleep, log)
    # decrease power if too strong
    while (not cart.state['pll_unlock']) and cart.state['pll_if_power'] < pll_range[1] and dbm > agilent.safe_dbm:
        dbm -= 0.3
        if dbm < agilent.safe_dbm:
            dbm = agilent.safe_dbm
        log.info('unlock: %d, pll_if: %.3f; decreasing dbm to %.2f', cart.state['pll_unlock'], cart.state['pll_if_power'], dbm)
        _try_dbm(cart, agilent, lo_ghz, dbm, skip_servo_pa, delay_secs, sleep, log)
    # slowly increase power to target
    while (not cart.state['pll_unlock']) and cart.state['pll_if_power'] > pll_range[0] and dbm < max_dbm:
        dbm += 0.1
        if dbm > max_dbm:
            dbm = max_dbm
        log.info('unlock: %d, pll_if: %.3f; increasing dbm to %.2f', cart.state['pll_unlock'], cart.state['pll_if_power'], dbm)
        _try_dbm(cart, agilent, lo_ghz, dbm, skip_servo_pa, delay_secs, sleep, log)
    #log.info('unlock: %d, pll_if: %.3f; final dbm %.2f', cart.state['pll_unlock'], cart.state['pll_if_power'], dbm)
    if cart.state['pll_unlock']:
        log.error('unlocked at %.3f ghz, setting to safe dbm.', lo_ghz)
        agilent.set_dbm(agilent.safe_dbm)
        return False
    log.info('tuned to %.3f ghz, pll_if %.3f, final dbm %.2f', lo_ghz, cart.state['pll_if_power'], dbm)
    return True
    # tune
    
