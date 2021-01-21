'''
namakanui/util.py   RMB 20200227

Utility functions for scripts.

This module also includes a set of DRAMA functions that are only defined
if the user has already imported drama before importing this module.


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

import sys
import os
import logging
import time
import namakanui.cart  # needed for BadLock

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
    

def parse_range(s, maxlen=0, maxstep=0):
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
    #if len(s) == 2:
    #    return [first, last]
    diff = last - first
    if diff == 0.0:
        return [first]
    if len(s) == 2:
        step = 0.0
    else:
        step = abs(float(s[2]))
    if step == 0.0 or step > abs(diff):
        step = abs(diff)
    if maxstep and step > maxstep:
        raise ValueError('step %g > maxstep %g'%(step, maxstep))
    if diff < 0.0:
        step = -step
    alen = int(round(diff/step + 1))
    if maxlen and alen > maxlen:
        raise ValueError('step %g too small, array len %d > maxlen %d'%(step,alen,maxlen))
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


def _try_tune(cart, lo_ghz, voltage, msg, skip_servo_pa, lock_only, log):
    '''Helper function used by tune() to catch and log exceptions.
       NOTE: Any error except BadLock should set power to safe levels.
    '''
    log.info('cart.tune %.3f ghz, %s', lo_ghz, msg)
    try:
        cart.tune(lo_ghz, voltage, skip_servo_pa=skip_servo_pa, lock_only=lock_only)
    except namakanui.cart.BadLock as e:
        log.error('tune failed at %.3f ghz, %s', lo_ghz, msg)
    cart.update_all()


def _try_att(cart, photonics, lo_ghz, voltage, att, skip_servo_pa, lock_only, delay_secs, sleep, log):
    '''Helper function used by tune(); set a new attenuation and retune if needed.'''
    photonics.set_attenuation(att)
    sleep(delay_secs)
    photonics.update()
    cart.update_all()
    if cart.state['pll_unlock']:
        _try_tune(cart, lo_ghz, voltage, 'att %d'%(att), skip_servo_pa, lock_only, log)


def _try_dbm(cart, agilent, lo_ghz, voltage, dbm, skip_servo_pa, lock_only, delay_secs, sleep, log):
    '''Helper function used by tune(); set a new dbm and retune if needed.'''
    agilent.set_dbm(dbm)
    sleep(delay_secs)
    agilent.update()
    cart.update_all()
    if cart.state['pll_unlock']:
        _try_tune(cart, lo_ghz, voltage, 'dbm %.2f'%(dbm), skip_servo_pa, lock_only, log)


def tune(cart, agilent, photonics,
         lo_ghz, voltage=0.0, lock_side='above', pll_range=[-.8,-2.5],
         att_ini=True, att_start=None, att_min=None,
         dbm_ini=True, dbm_start=None, dbm_max=None,
         skip_servo_pa=False, lock_only=False, sleep=time.sleep, log=logging):
    '''
    Tune the receiver and optimize PLL IF power by adjusting
    photonics attenuation and/or agilent output power.
    Returns True on success, False on failure.
    Parameters:
      cart: Cart class instance
      agilent: Agilent class instance
      photonics: Photonics (attenuator) class instance, can be None
      lo_ghz: Frequency to tune to
      voltage: Target PLL control voltage [-10, 10]; None skips FM adjustment
      lock_side: Lock PLL "below"(0) or "above"(1) ref signal; if None no change
      pll_range: [min_power, max_power].
      att_ini: If True, att_range is relative to interpolated table value.
      att_start: If None, is (att_ini ?  0 : photonics.max_att)
      att_min:   If None, is (att_ini ? -6 : 0)
      dbm_ini: If True, dbm_range is relative to interpolated table value.
        If photonics is not None, use shared photonics_dbm table (band 0).
      dbm_start: If None, is (dbm_ini ? 0 : agilent.safe_dbm)
      dbm_max:   If None, is (dbm_ini ? 3 : agilent.max_dbm)
      skip_servo_pa: If true, PA not adjusted for target mixer current.
      lock_only: If true, pa/lna/sis/magnets held at previous values.
      sleep: Sleep function
      log: logging.Logger class instance
    '''
    log.info('tuning band %d to %.3f ghz...', cart.band, lo_ghz)
    delay_secs = 0.05
    # TODO this needs to be easily accessible from cart instance.
    # presently must manually set after initialise and doesn't update state.
    lock_polarity = cart.femc.get_cartridge_lo_pll_sb_lock_polarity_select(cart.ca)
    if lock_side is not None:
        lock_side = lock_side.lower() if hasattr(lock_side, 'lower') else lock_side
        arg_lock_polarity = {0:0, 1:1, 'below':0, 'above':1}[lock_side]
        if arg_lock_polarity != lock_polarity:
            lock_polarity = arg_lock_polarity
            cart.femc.set_cartridge_lo_pll_sb_lock_polarity_select(cart.ca, lock_polarity)
    cart.state['pll_sb_lock'] = lock_polarity  # cart never updates this
    floog = agilent.floog * [1.0, -1.0][lock_polarity]  # [below, above]
    fyig = lo_ghz / (cart.cold_mult * cart.warm_mult)
    fsig = (fyig*cart.warm_mult + floog) / agilent.harmonic
    
    att_max = photonics.max_att if photonics else 255
    att_start = (0 if att_ini else att_max) if att_start is None else att_start
    att_min = (-24 if att_ini else 0) if att_min is None else att_min
    if att_ini and photonics:
        att_ini = photonics.interp_attenuation(cart.band, lo_ghz)
        att_start += att_ini
        att_min += att_ini
    att_start = int(round(clip(att_start, 0, att_max)))
    att_min = int(round(clip(att_min, 0, att_max)))
    
    dbm_min = agilent.safe_dbm
    dbm_start = (0.0 if dbm_ini else dbm_min) if dbm_start is None else dbm_start
    dbm_max = (3.0 if dbm_ini else agilent.max_dbm) if dbm_max is None else dbm_max
    if dbm_ini:
        ghz = lo_ghz
        dbm_band = cart.band
        if photonics:
            ghz = fsig
            dbm_band = 0
        dbm_ini = agilent.interp_dbm(dbm_band, ghz)
        dbm_start += dbm_ini
        dbm_max += dbm_ini
    dbm_start = clip(dbm_start, dbm_min, agilent.max_dbm)
    dbm_max = clip(dbm_max, dbm_min, agilent.max_dbm)
    
    log.info('att_start: %d, att_min: %d', att_start, att_min)
    log.info('dbm_start: %.2f, dbm_max: %.2f', dbm_start, dbm_max)
    
    # make sure pll_range signs and order are correct (must exist)
    pll_range = [-abs(pll_range[0]), -abs(pll_range[1])]
    pll_range.sort()
    pll_range.reverse()
    log.info('pll_range: [%.2f, %.2f]', pll_range[0], pll_range[1])
    
    att = att_start
    dbm = dbm_start
    hz = fsig*1e9
    log.info('agilent hz: %.1f', hz)
    
    # from here on, any uncaught exception needs to set power to safe levels
    try:
    
        # if adjusting photonics, must do so safely.
        # if increasing power output, set the frequency first.
        # if decreasing power output, set the attenuation first.
        if photonics:
            if att < photonics.state['attenuation']:
                agilent.set_hz_dbm(hz, dbm)
                photonics.set_attenuation(att)
            else:
                photonics.set_attenuation(att)
                agilent.set_hz_dbm(hz, dbm)
        else:
            agilent.set_hz_dbm(hz, dbm)
        
        sleep(delay_secs)
        agilent.update()
        photonics.update() if photonics else None
        _try_tune(cart, lo_ghz, voltage, 'att %d, dbm %.2f'%(att,dbm), skip_servo_pa, lock_only, log)
        
        
        ### PHOTONICS ATTENUATOR ADJUSTMENT ###
        
        # quickly decrease attenuation if needed
        while photonics and (cart.state['pll_unlock'] or cart.state['pll_if_power'] > pll_range[0]) and att > att_min:
            att -= 8  # 1 dB for 8-bit 31.5 dB attenuator
            if att < att_min:
                att = att_min
            log.info('unlock: %d, pll_if: %.3f; decreasing att to %d', cart.state['pll_unlock'], cart.state['pll_if_power'], att)
            _try_att(cart, photonics, lo_ghz, voltage, att, skip_servo_pa, lock_only, delay_secs, sleep, log)
        
        # increase attenuation if too strong
        while photonics and (not cart.state['pll_unlock']) and cart.state['pll_if_power'] < pll_range[1] and att < att_max:
            att += 3  # .37 dB for 8-bit 31.5 dB attenuator
            if att > att_max:
                att = att_max
            log.info('unlock: %d, pll_if: %.3f; increasing att to %d', cart.state['pll_unlock'], cart.state['pll_if_power'], att)
            _try_att(cart, photonics, lo_ghz, voltage, att, skip_servo_pa, lock_only, delay_secs, sleep, log)
        
        # slowly decrease attenuation to target (and relock if needed)
        while photonics and (cart.state['pll_unlock'] or cart.state['pll_if_power'] > pll_range[0]) and att > att_min:
            att -= 1  # .12 dB for 8-bit 31.5 dB attenuator
            if att < att_min:
                att = att_min
            log.info('unlock: %d, pll_if: %.3f; decreasing att to %d', cart.state['pll_unlock'], cart.state['pll_if_power'], att)
            _try_att(cart, photonics, lo_ghz, voltage, att, skip_servo_pa, lock_only, delay_secs, sleep, log)
        
        
        ### AGILENT OUTPUT POWER ADJUSTMENT ###
        
        # quickly increase power if needed
        while (cart.state['pll_unlock'] or cart.state['pll_if_power'] > pll_range[0]) and dbm < dbm_max:
            dbm += 1.0
            if dbm > dbm_max:
                dbm = dbm_max
            log.info('unlock: %d, pll_if: %.3f; increasing dbm to %.2f', cart.state['pll_unlock'], cart.state['pll_if_power'], dbm)
            _try_dbm(cart, agilent, lo_ghz, voltage, dbm, skip_servo_pa, lock_only, delay_secs, sleep, log)
        
        # decrease power if too strong
        while (not cart.state['pll_unlock']) and cart.state['pll_if_power'] < pll_range[1] and dbm > dbm_min:
            dbm -= 0.3
            if dbm < dbm_min:
                dbm = dbm_min
            log.info('unlock: %d, pll_if: %.3f; decreasing dbm to %.2f', cart.state['pll_unlock'], cart.state['pll_if_power'], dbm)
            _try_dbm(cart, agilent, lo_ghz, voltage, dbm, skip_servo_pa, lock_only, delay_secs, sleep, log)
        
        # slowly increase power to target (and relock if needed)
        while (cart.state['pll_unlock'] or cart.state['pll_if_power'] > pll_range[0]) and dbm < dbm_max:
            dbm += 0.1
            if dbm > dbm_max:
                dbm = dbm_max
            log.info('unlock: %d, pll_if: %.3f; increasing dbm to %.2f', cart.state['pll_unlock'], cart.state['pll_if_power'], dbm)
            _try_dbm(cart, agilent, lo_ghz, voltage, dbm, skip_servo_pa, lock_only, delay_secs, sleep, log)
        
        #log.info('unlock: %d, pll_if: %.3f; final dbm %.2f', cart.state['pll_unlock'], cart.state['pll_if_power'], dbm)
        if cart.state['pll_unlock']:
            log.error('unlocked at %.3f ghz, pll_if %.3f. setting power to safe levels.', lo_ghz, cart.state['pll_if_power'])
            agilent.set_dbm(agilent.safe_dbm)
            photonics.set_attenuation(photonics.max_att) if photonics else None
            return False
        log.info('tuned to %.3f ghz, pll_if %.3f, final att %d, dbm %.2f', lo_ghz, cart.state['pll_if_power'], att, dbm)
        return True
    
    except:
        log.exception('unhandled error tuning to %.3f ghz. setting power to safe levels.', lo_ghz)
        # nested try/finally block will attempt to set power on both devices,
        # even if one fails, while still raising any errors produced.
        try:
            agilent.set_dbm(agilent.safe_dbm)
        finally:
            photonics.set_attenuation(photonics.max_att) if photonics else None
        raise
    # tune


def setup_script(band, lock_side, sleep=time.sleep, publish=namakanui.nop):
    '''
    Perform common setup for a standalone script:
        - Create agilent and set to safe levels with output enabled.
        - Create photonics (if in namaknui.ini) and set max attenuation.
        - Create cart(band) and set given lock side.
        - Zero out pa/lna on unused bands.
        - Set ifswitch to given band.
        - Check reference (floog) power level.
    Returns cart, agilent, photonics.
    '''
    import namakanui.ini
    import namakanui.cart
    import namakanui.agilent
    import namakanui.photonics
    import namakanui.ifswitch
    
    binpath, datapath = get_paths()
    
    agilent = namakanui.agilent.Agilent(datapath+'agilent.ini', sleep, publish)
    agilent.set_dbm(agilent.safe_dbm)
    agilent.set_output(1)
    
    photonics = None
    nconfig = namakanui.ini.IncludeParser(datapath+'namakanui.ini')
    if 'photonics_ini' in nconfig['namakanui']:
        pini = nconfig['namakanui']['photonics_ini']
        photonics = namakanui.photonics.Photonics(datapath+pini, sleep, publish)
        photonics.set_attenuation(photonics.max_att)
    
    ifswitch = namakanui.ifswitch.IFSwitch(datapath+'ifswitch.ini', sleep, publish)
    ifswitch.set_band(band)
    ifswitch.close()  # done with ifswitch
    
    cart = namakanui.cart.Cart(band, datapath+'band%d.ini'%(band), sleep, publish)
    cart.power(1)
    if lock_side is not None:
        lock_side = lock_side.lower() if hasattr(lock_side, 'lower') else lock_side
        lock_side = {0:0, 1:1, 'below':0, 'above':1}[lock_side]
        cart.femc.set_cartridge_lo_pll_sb_lock_polarity_select(cart.ca, lock_side)
        cart.state['pll_sb_lock'] = lock_side  # cart never updates this
    
    # zero out unused carts
    femc = cart.femc
    for b in [3,6,7]:
        if b == band:
            continue
        ca = b-1
        if not femc.get_pd_enable(ca):
            continue
        for po in range(2):
            femc.set_cartridge_lo_pa_pol_drain_voltage_scale(ca, po, 0)
            femc.set_cartridge_lo_pa_pol_gate_voltage(ca, po, 0)
            for sb in range(2):
                femc.set_lna_enable(ca, po, sb, 0)
    
    # this mainly checks that the IF switch really has this band selected
    cart.update_all()
    rp = cart.state['pll_ref_power']
    if rp < -3.0:
        raise RuntimeError('PLL ref (FLOOG 31.5 MHz) power high (%.2fV), needs padding'%(rp))
    if rp > -0.5:
        raise RuntimeError('PLL ref (FLOOG 31.5 MHz) power low (%.2fV), check IF switch'%(rp))
    
    return cart, agilent, photonics
    # setup_script



# DRAMA functions only defined if drama was already imported.
if 'drama' in sys.modules:
    import drama
    
    def iftask_setup(adjust, bw_mhz, if_ghz, dcms):
        # LEVEL_ADJUST 0=setup_only, 1=setup_and_level, 2=level_only
        # BIT_MASK is DCMs to use: bit0=DCM0, bit1=DCM1, ... bit31=DCM31.
        setup_type = ['setup_only', 'setup_and_level', 'level_only']
        logging.info('setup IFTASK, LEVEL_ADJUST %d: %s', adjust, setup_type[adjust])
        bitmask = 0
        for dcm in dcms:
            bitmask |= 1<<dcm
        msg = drama.obey('IFTASK@if-micro', 'TEST_SETUP',
                        NASM_SET='R_CABIN', BAND_WIDTH=bw_mhz, QUAD_MODE=4,
                        IF_FREQ=if_ghz, LEVEL_ADJUST=adjust, BIT_MASK=bitmask).wait(90)
        if msg.reason != drama.REA_COMPLETE or msg.status != 0:
            if msg.status == 261456746:  # ACSISIF__ATTEN_ZERO
                logging.warning('low attenuator setting from IFTASK.TEST_SETUP')
            else:
                logging.error('bad reply from IFTASK.TEST_SETUP: %s', msg)
                return 1
        return 0


    def iftask_set_bw(bw_mhz):
        # this goes fast; probably doesn't do much.
        logging.info('set bandwidth %g MHz', bw_mhz)
        msg = drama.obey('IFTASK@if-micro', 'SET_DCM_BW', DCM=-1, MHZ=bw_mhz).wait(10)
        if msg.reason != drama.REA_COMPLETE or msg.status != 0:
            logging.error('bad reply from IFTASK.SET_DCM_BW: %s', msg)
            return 1
        return 0


    def iftask_set_lo2(lo2_mhz):
        # this can take ~20s, or ~40s if it needs to change the coax switches.
        logging.info('set lo2 freq %g MHz', lo2_mhz)
        msg = drama.obey('IFTASK@if-micro', 'SET_LO2_FREQ', LO2=-1, MHZ=lo2_mhz).wait(90)
        if msg.reason != drama.REA_COMPLETE or msg.status != 0:
            logging.error('bad reply from IFTASK.SET_LO2_FREQ: %s', msg)
            return 1
        return 0


    def iftask_get_tp2(dcms, itime=0.1):
        msg = drama.obey("IFTASK@if-micro", "WRITE_TP2", FILE="NONE", ITIME=itime).wait(5)
        if msg.reason != drama.REA_COMPLETE or msg.status != 0:
            logging.error('bad reply from IFTASK.WRITE_TP2: %s', msg)
            return None
        tps = []
        for dcm in dcms:
            tps.append(msg.arg['POWER%d'%(dcm)])
        return tps


    def iftask_get_att(dcms):
        msg = drama.obey('IFTASK@if-micro', 'GET_DCM_ATTEN', DCM=-1).wait(5)
        if msg.reason != drama.REA_COMPLETE or msg.status != 0:
            logging.error('bad reply from IFTASK.GET_DCM_ATTEN: %s', msg)
            return None
        att = []
        for dcm in dcms:
            att.append(msg.arg['ATTEN%d'%(dcm)])
        return att

