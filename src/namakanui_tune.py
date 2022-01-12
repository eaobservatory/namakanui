#!/local/python3/bin/python3
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

import jac_sw
import logging
import argparse
import namakanui.cart
import namakanui.util
import namakanui.ini
import namakanui.sim


log = logging.getLogger(__name__)
voltage_valid = namakanui.util.interval(-10, 10)
pll_if_valid = namakanui.util.interval(-0.5, -3.0)


def try_tune(cart, lo_ghz, voltage, msg, skip_servo_pa, lock_only):
    '''Helper function used by tune(): catch and log BadLock exceptions.'''
    skipstr = ['', ', skip_servo_pa'][skip_servo_pa]
    lockstr = ['', ', lock_only'][lock_only]
    log.info('cart.tune %.3f ghz, %.1fv, %s%s%s', lo_ghz, voltage, msg, skipstr, lockstr)
    try:
        cart.tune(lo_ghz, voltage, skip_servo_pa=skip_servo_pa, lock_only=lock_only)
    except namakanui.cart.BadLock as e:
        log.error('tune failed at %.3f ghz, %s', lo_ghz, msg)
    cart.update_all()
    # try_tune

def try_att(cart, photonics, lo_ghz, voltage, att, skip_servo_pa, lock_only, delay_secs):
    '''Helper function used by tune(): set new attenuation, retune if needed.'''
    photonics.set_attenuation(att)
    cart.sleep(delay_secs)
    photonics.update()
    cart.update_all()
    if cart.state['pll_unlock']:
        try_tune(cart, lo_ghz, voltage, 'att %d'%(att), skip_servo_pa, lock_only)
    # try_att

def try_dbm(cart, reference, lo_ghz, voltage, dbm, skip_servo_pa, lock_only, delay_secs):
    '''Helper function used by tune(): set a new dbm, retune if needed.'''
    reference.set_dbm(dbm)
    cart.sleep(delay_secs)
    reference.update()
    cart.update_all()
    if cart.state['pll_unlock']:
        try_tune(cart, lo_ghz, voltage, 'dbm %.2f'%(dbm), skip_servo_pa, lock_only)
    # try_dbm


def tune(instrument, band, lo_ghz, voltage=0.0,
         lock_side='above', pll_if=[-.8,-2.5],
         att_ini=True, att_start=None, att_min=None,
         dbm_ini=True, dbm_start=None, dbm_max=None,
         skip_servo_pa=False, lock_only=False):
    '''Tune the receiver and optimize PLL IF power by adjusting
       photonics attenuation and/or reference output power.
       Returns True on success, False on failure.  (TODO throw on failure?)
       Arguments:
        instrument: Created if None
        band: Band to tune
        lo_ghz: Frequency to tune to, GHz
        voltage: Target PLL control voltage [-10, 10]; None skips FM adjustment
        lock_side: Lock PLL "below"(0) or "above"(1) ref signal; if None no change
        pll_if: [min_power, max_power], can be str "min:max".
        att_ini: If True, att_range is relative to interpolated table value.
        att_start: If None, is (att_ini ?  0 : photonics.max_att)
        att_min:   If None, is (att_ini ? -6 : 0)
        dbm_ini: If True, dbm_range is relative to interpolated table value.
           NOTE: If not photonics.simulate, use shared photonics_dbm table (band 0).
        dbm_start: If None, is (dbm_ini ? 0 : reference.safe_dbm)
        dbm_max:   If None, is (dbm_ini ? 3 : reference.max_dbm)
        skip_servo_pa: If true, PA not adjusted for target mixer current.
        lock_only: If true, pa/lna/sis/magnets held at previous values.
    '''
    if instrument:
        config = instrument.config
        bands = instrument.bands
    else:
        config = namakanui.util.get_config()
        bands = namakanui.util.get_bands(config)
    
    band = int(band)
    if band not in bands:
        raise ValueError(f'band {band} not in {bands}')
    
    lo_ghz = float(lo_ghz)
    b = str(band)
    cc = config[config[b]['cold']]
    wc = config[config[b]['warm']]
    mult = int(cc['Mult']) * int(wc['Mult'])
    floyig = float(wc['FLOYIG'])
    fhiyig = float(wc['FHIYIG'])
    lo_ghz_valid = namakanui.util.interval(floyig*mult, fhiyig*mult)
    if lo_ghz not in lo_ghz_valid:
        raise ValueError(f'lo_ghz {lo_ghz} not in range {lo_ghz_valid}')
    
    voltage = float(voltage)
    if voltage not in voltage_valid:
        raise ValueError(f'voltage {voltage} not in range {voltage_valid}')
    
    if lock_side is not None:
        lock_side = lock_side.lower() if hasattr(lock_side, 'lower') else lock_side
        if lock_side not in {0,1,'0','1','below','above'}:
            raise ValueError(f'lock_side {lock_side} not in [0,1,below,above]')
    
    if hasattr(pll_if, 'lower'):
        if pll_if.count(':') > 1:
            raise ValueError(f'pll_if {pll_if} range step not allowed')
        pll_if = namakanui.util.parse_range(pll_if, maxlen=2)
    if len(pll_if) < 2:
        pll_if.append(pll_if[0])
    if pll_if[0] not in pll_if_valid or pll_if[1] not in pll_if_valid:
        raise ValueError(f'pll_if {pll_if} not in range {pll_if_valid}')    
    
    skip_servo_pa = bool(skip_servo_pa)
    lock_only = bool(lock_only)
    
    log.info('tuning band %d to %g ghz...', band, lo_ghz)
    
    if not instrument:
        from namakanui.instrument import Instrument
        instrument = Instrument(config, simulate=namakanui.sim.SIM_LOAD, level={'instrument':logging.DEBUG, f'band{band}':logging.DEBUG})
    
    # TODO: band 7 may require a longer delay
    delay_secs = 0.05
    
    # make sure pll_if signs and order are correct
    pll_range = [-abs(pll_if[0]), -abs(pll_if[1])]
    pll_range.sort()
    pll_range.reverse()
    log.info('pll_if: [%.2f, %.2f]', pll_range[0], pll_range[1])
    
    # set STSR; will raise if band is invalid
    instrument.set_band(band)
    
    cart = instrument.carts[band]
    cart.power(1)
    
    reference = instrument.reference
    photonics = instrument.photonics
    
    # set PLL lock side and compute frequencies
    cart.set_lock_side(lock_side)
    lock_side = cart.state['pll_sb_lock']  # 0 or 1
    floog = reference.floog * [1.0, -1.0][lock_side]  # [below, above]
    fyig = lo_ghz / (cart.cold_mult * cart.warm_mult)
    fsig = (fyig*cart.warm_mult + floog) / reference.harmonic
    
    # function alias
    clip = namakanui.util.clip
    
    # photonics attenuation search range
    
    att_max = photonics.max_att
    att_start = (0 if att_ini else att_max) if att_start is None else att_start
    att_min = (-3*photonics.counts_per_db if att_ini else 0) if att_min is None else att_min
    if att_ini:
        att_ini = photonics.interp_attenuation(cart.band, lo_ghz)
        att_start += att_ini
        att_min += att_ini
    # int+round because user may have passed floats for att_start/min
    att_start = int(round(clip(att_start, 0, att_max)))
    att_min = int(round(clip(att_min, 0, att_max)))
    
    # reference output power search range
    dbm_min = reference.safe_dbm
    dbm_start = (0.0 if dbm_ini else dbm_min) if dbm_start is None else dbm_start
    dbm_max = (3.0 if dbm_ini else reference.max_dbm) if dbm_max is None else dbm_max
    if dbm_ini:
        ghz = lo_ghz
        dbm_band = cart.band
        if not photonics.simulate:
            # use the shared photonics_dbm power table
            ghz = fsig
            dbm_band = 0
        dbm_ini = reference.interp_dbm(dbm_band, ghz)
        dbm_start += dbm_ini
        dbm_max += dbm_ini
    dbm_start = clip(dbm_start, dbm_min, reference.max_dbm)
    dbm_max = clip(dbm_max, dbm_min, reference.max_dbm)
    
    log.info('att_start: %d, att_min: %d', att_start, att_min)
    log.info('dbm_start: %.2f, dbm_max: %.2f', dbm_start, dbm_max)
    
    att = att_start
    dbm = dbm_start
    hz = fsig*1e9
    log.info('reference hz: %.1f', hz)
    
    # from here on, any uncaught exception needs to set power to safe levels
    try:
        instrument.set_reference(hz, dbm, att)
        instrument.sleep(delay_secs)
        try_tune(cart, lo_ghz, voltage, 'att %d, dbm %.2f'%(att,dbm), skip_servo_pa, lock_only)
        
        ### PHOTONICS ATTENUATOR ADJUSTMENT
        if not photonics.simulate:
            # quickly decrease attenuation (raise power) if needed
            datt = max(3, int(round(photonics.counts_per_db)))
            while (cart.state['pll_unlock'] or cart.state['pll_if_power'] > pll_range[0]) and att > att_min:
                att -= datt
                if att < att_min:
                    att = att_min
                log.info('unlock: %d, pll_if: %.3f; decreasing att to %d', cart.state['pll_unlock'], cart.state['pll_if_power'], att)
                try_att(cart, photonics, lo_ghz, voltage, att, skip_servo_pa, lock_only, delay_secs)
            # increase attenuation (decrease power) if too strong
            datt = max(2, int(round(photonics.counts_per_db/3)))
            while (not cart.state['pll_unlock']) and cart.state['pll_if_power'] < pll_range[1] and att < att_max:
                att += datt
                if att > att_max:
                    att = att_max
                log.info('unlock: %d, pll_if: %.3f; increasing att to %d', cart.state['pll_unlock'], cart.state['pll_if_power'], att)
                try_att(cart, photonics, lo_ghz, voltage, att, skip_servo_pa, lock_only, delay_secs)
            # slowly decrease attenuation to target (and relock if needed)
            datt = max(1, int(round(photonics.counts_per_db/9)))
            while (cart.state['pll_unlock'] or cart.state['pll_if_power'] > pll_range[0]) and att > att_min:
                att -= datt
                if att < att_min:
                    att = att_min
                log.info('unlock: %d, pll_if: %.3f; decreasing att to %d', cart.state['pll_unlock'], cart.state['pll_if_power'], att)
                try_att(cart, photonics, lo_ghz, voltage, att, skip_servo_pa, lock_only, delay_secs)
        
        ### REFERENCE OUTPUT POWER ADJUSTMENT
        if not reference.simulate:
            # quickly increase power if needed
            while (cart.state['pll_unlock'] or cart.state['pll_if_power'] > pll_range[0]) and dbm < dbm_max:
                dbm += 1.0
                if dbm > dbm_max:
                    dbm = dbm_max
                log.info('unlock: %d, pll_if: %.3f; increasing dbm to %.2f', cart.state['pll_unlock'], cart.state['pll_if_power'], dbm)
                try_dbm(cart, reference, lo_ghz, voltage, dbm, skip_servo_pa, lock_only, delay_secs)
            # decrease power if too strong
            while (not cart.state['pll_unlock']) and cart.state['pll_if_power'] < pll_range[1] and dbm > dbm_min:
                dbm -= 0.3
                if dbm < dbm_min:
                    dbm = dbm_min
                log.info('unlock: %d, pll_if: %.3f; decreasing dbm to %.2f', cart.state['pll_unlock'], cart.state['pll_if_power'], dbm)
                try_dbm(cart, reference, lo_ghz, voltage, dbm, skip_servo_pa, lock_only, delay_secs)
            # slowly increase power to target (and relock if needed)
            while (cart.state['pll_unlock'] or cart.state['pll_if_power'] > pll_range[0]) and dbm < dbm_max:
                dbm += 0.1
                if dbm > dbm_max:
                    dbm = dbm_max
                log.info('unlock: %d, pll_if: %.3f; increasing dbm to %.2f', cart.state['pll_unlock'], cart.state['pll_if_power'], dbm)
                try_dbm(cart, reference, lo_ghz, voltage, dbm, skip_servo_pa, lock_only, delay_secs)
        
        if cart.state['pll_unlock']:
            log.error('unlocked at %.3f ghz, pll_if %.3f, final att %d, dbm %.2f. setting power to safe levels.', lo_ghz, cart.state['pll_if_power'], att, dbm)
            instrument.set_safe()
            return False
        
        log.info('tuned to %.3f ghz, pll_if %.3f, final att %d, dbm %.2f', lo_ghz, cart.state['pll_if_power'], att, dbm)
        return True
    
    except:
        log.exception('unhandled error tuning to %.3f ghz. setting power to safe levels.', lo_ghz)
        instrument.set_safe()
        raise
    # tune


if __name__ == '__main__':
    
    namakanui.util.setup_logging(logging.DEBUG)
    
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawTextHelpFormatter,
        description=namakanui.util.get_description(__doc__)
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
                        choices=voltage_valid)
    args = parser.parse_args()
    
    try:
        tune(None, **vars(args))
    except ValueError as e:
        parser.error(e)  # calls sys.exit

