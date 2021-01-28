'''
namakanui/instrument.py   RMB 20210113

Instrument class to contain instances for the whole receiver system.


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

from namakanui.ini import *
from namakanui import sim
import logging
import time

import namakanui.reference
import namakanui.cart
import namakanui.femc
import namakanui.ifswitch
import namakanui.load
import namakanui.photonics
import namakanui.util


class Instrument(object):
    '''
    Class to contain instances for the whole receiver system.
    '''
    
    def __init__(self, inifile=None, sleep=time.sleep, publish=namakanui.nop, simulate=0):
        '''Arguments:
            inifile: Path to config file (instrument.ini if None) or IncludeParser instance.
            sleep(seconds): Function to sleep for given seconds, e.g. time.sleep, drama.wait.
            publish(name, dict): Function to output dict with given name, e.g. drama.set_param.
            simulate: Mask, bitwise ORed with config settings.
        '''
        self.sleep = sleep
        self.publish = publish
        self.hardware = []
        self.carts = {}
        if inifile is None:
            binpath, datapath = namakanui.util.get_paths()
            inifile = datapath + 'instrument.ini'
        self.initialise(inifile, simulate)
        # Instrument.__init__


    def __del__(self):
        self.log.debug('__del__')
        self.close()
        # Instrument.__del__
    
    
    def close(self):
        '''Close all instances and set to None'''
        self.log.debug('close')
        for thing in self.hardware:
            try:
                thing.close()
            except:
                pass
        self.hardware = []
        self.carts = {}
        self.update_index_hw = -1
        self.update_index_cart = -1
        self.reference = None
        self.ifswitch = None
        self.load = None
        self.photonics = None
        self.femc = None
        # Instrument.close
    
    
    def initialise(self, inifile, simulate=0):
        '''Create all instances.
           Arguments:
            inifile: Path to config file or IncludeParser instance.
            simulate: Mask, bitwise ORed with config settings.
        '''
        self.log.debug('initialise')
        
        if not hasattr(inifile, 'items'):
            inifile = IncludeParser(inifile)
        self.config = inifile
        cfg = self.config['instrument']
        
        self.name = cfg['pubname']
        self.logname = cfg['logname']
        self.log = logging.getLogger(self.logname)
        self.state = {'number':0}
        
        # each included bandX.ini file adds itself to the [bands] config entry
        self.bands = [int(x) for x in self.config['bands']]
        
        # simulate param in [instrument] would cause confusion;
        # we only check simulate in each individual config section.
        if 'simulate' in cfg:
            self.log.warn('ignoring "simulate" parameter in %s', self.config.inifilename)
        
        sleep = self.sleep
        publish = self.publish
        
        self.close()
        
        self.reference = namakanui.reference.Reference(inifile, sleep, publish, simulate)
        self.ifswitch = namakanui.ifswitch.IFSwitch(inifile, sleep, publish, simulate)
        self.load = namakanui.load.Load(inifile, sleep, publish, simulate)
        self.photonics = namakanui.photonics.Photonics(inifile, sleep, publish, simulate)
        self.femc = namakanui.femc.FEMC(inifile, sleep, publish, simulate)
        
        self.hardware = [self.reference, self.ifswitch, self.load, self.photonics, self.femc]
        
        # build up simulate bitmask from individual components
        self.simulate = 0
        for thing in self.hardware:
            self.simulate |= thing.simulate
        
        for band in self.bands:
            cart = namakanui.cart.Cart(band, self.femc, inifile, sleep, publish, simulate)
            self.carts[band] = cart
            self.simulate |= cart.simulate
        
        self.state['simulate'] = self.simulate
        self.state['sim_text'] = sim.bits_to_str(self.simulate)
        self.state['bands'] = self.bands
        
        # NOTE each component already does an update() in its initialise().
        self.update()
        # Instrument.initialise


    def update(self):
        '''Publish self.state only.'''
        self.log.debug('update')
        self.state['number'] += 1
        self.publish(self.name, self.state)
        # Instrument.update

    def update_all(self):
        '''Update and publish all instances.'''
        self.log.debug('update_all')
        for thing in self.hardware:
            thing.update()
        for cart in self.carts.values():
            cart.update_all()
        self.update()
        # Instrument.update_all
    
    def update_one_hw(self):
        '''Call a single hardware update function and advance the index.
            Updates one of: reference, ifswitch, load, photonics, femc.
            Recommended 10s cycle, call delay 10.0/len(hardware).
        '''
        self.log.debug('update_one_hw')
        if not self.hardware:  # called after close()
            return
        self.update_index_hw = (self.update_index_hw + 1) % len(self.hardware)
        self.hardware[update_index_hw].update()
        # Instrument.update_one_hw
    
    def update_one_cart(self):
        '''Call a single update_one function and advance the cart index.
            Recommended 20s cycle, call delay 20.0/(len(carts)*3).
            NOTE: Background carts really don't need fast updates.
                  Use a separate 5s cycle to monitor the current band:
                  carts[band].update_one(); sleep(1.66)
        '''
        self.log.debug('update_one_cart')
        if not self.carts:  # called after close()
            return
        self.update_index_cart = (self.update_index_cart + 1) % len(self.carts)
        cart = list(self.carts.values())[self.update_index_cart]
        cart.update_one()
        # Instrument.update_one_cart
    
    
    def set_band(self, band):
        '''Switch to given band, if not already selected.'''
        self.log.debug('set_band(%s)', band)
        band = int(band)
        if band not in self.bands:
            raise ValueError('band %d not in %s'%(band, self.bands))
        if band == self.ifswitch.get_band():
            self.log.debug('ifswitch already at band %d', band)
            return
        self.log.info('switching to band %d', band)
        # reduce reference signal power to minimum levels
        self.set_safe()
        # zero bias/amps/magnets on all carts to reduce interference
        for cart in self.carts.values():
            cart.zero()
            cart.update_all()
        self.ifswitch.set_band(band)
        # Instrument.set_band
    
    
    def set_reference(self, hz, dbm, att):
        '''Set reference signal to desired parameters,
           in the proper order to avoid power spikes.
           Arguments:
            hz: reference output frequency, Hz
            dbm: reference output power, dBm
            att: photonics attenuation, counts
        '''
        self.log.debug('set_reference(%g, %g, %d)', hz, dbm, att)
        
        # if increasing power output, set the frequency first.
        # if decreasing power output, set the attenuation first.
        if att < self.photonics.state['attenuation']:
            self.reference.set_hz_dbm(hz, dbm)
            self.photonics.set_attenuation(att)
        else:
            self.photonics.set_attenuation(att)
            self.reference.set_hz_dbm(hz, dbm)
        
        if not self.reference.state['output']:
            self.reference.set_output(1)
        
        # reference set funcs don't call update (but set_attenuation does)
        self.reference.update()
        # Instrument.set_reference
    
    
    def set_safe(self):
        '''Set reference power to minimum and attenuation to maximum.'''
        self.log.debug('set_safe')
        # ensure we try to set both, even if one fails
        try:
            self.photonics.set_attenuation(self.photonics.max_att)
        finally:
            self.reference.set_dbm(self.reference.safe_dbm)
            self.reference.update(publish_only=True)
        # Instrument.set_safe
    
    
    def _try_tune(self, cart, lo_ghz, voltage, msg, skip_servo_pa, lock_only):
        '''Helper function used by tune(): catch and log BadLock exceptions.'''
        self.log.info('cart.tune %.3f ghz, %s', lo_ghz, msg)
        try:
            cart.tune(lo_ghz, voltage, skip_servo_pa=skip_servo_pa, lock_only=lock_only)
        except namakanui.cart.BadLock as e:
            self.log.error('tune failed at %.3f ghz, %s', lo_ghz, msg)
        cart.update_all()
        # Instrument._try_tune

    def _try_att(self, cart, lo_ghz, voltage, att, skip_servo_pa, lock_only, delay_secs):
        '''Helper function used by tune(): set new attenuation, retune if needed.'''
        self.photonics.set_attenuation(att)
        self.sleep(delay_secs)
        self.photonics.update()
        cart.update_all()
        if cart.state['pll_unlock']:
            self._try_tune(cart, lo_ghz, voltage, 'att %d'%(att), skip_servo_pa, lock_only)
        # Instrument._try_att

    def _try_dbm(self, cart, lo_ghz, voltage, dbm, skip_servo_pa, lock_only, delay_secs):
        '''Helper function used by tune(): set a new dbm, retune if needed.'''
        self.reference.set_dbm(dbm)
        self.sleep(delay_secs)
        self.reference.update()
        cart.update_all()
        if cart.state['pll_unlock']:
            self._try_tune(cart, lo_ghz, voltage, 'dbm %.2f'%(dbm), skip_servo_pa, lock_only)
        # Instrument._try_dbm
    
    
    def tune(self, band, lo_ghz, voltage=0.0,
             lock_side='above', pll_if=[-.8,-2.5],
             att_ini=True, att_start=None, att_min=None,
             dbm_ini=True, dbm_start=None, dbm_max=None,
             skip_servo_pa=False, lock_only=False):
        '''Tune the receiver and optimize PLL IF power by adjusting
           photonics attenuation and/or reference output power.
           Returns True on success, False on failure.  (TODO throw on failure?)
           Arguments:
            band: Band to tune
            lo_ghz: Frequency to tune to, GHz
            voltage: Target PLL control voltage [-10, 10]; None skips FM adjustment
            lock_side: Lock PLL "below"(0) or "above"(1) ref signal; if None no change
            pll_if: [min_power, max_power].
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
        band = int(band)
        lo_ghz = float(lo_ghz)
        self.log.info('tuning band %d to %g ghz...', band, lo_ghz)
        
        # TODO: band 7 may require a longer delay
        delay_secs = 0.05
        
        # make sure pll_if signs and order are correct (must exist)
        pll_range = [-abs(pll_if[0]), -abs(pll_if[1])]
        pll_range.sort()
        pll_range.reverse()
        pmin = -0.5
        pmax = -3.0
        if pll_range[0] > pmin or pll_range[1] < pmax:
            raise ValueError(f'pll_if {pll_range} outside [{pmin},{pmax}]')
        self.log.info('pll_if: [%.2f, %.2f]', pll_range[0], pll_range[1])
        
        # set ifswitch; will raise if band is invalid
        self.set_band(band)
        
        cart = self.carts[band]
        cart.power(1)
        
        # set PLL lock side and compute frequencies
        cart.set_lock_side(lock_side)
        lock_side = cart.state['pll_sb_lock']  # 0 or 1
        floog = self.reference.floog * [1.0, -1.0][lock_side]  # [below, above]
        fyig = lo_ghz / (cart.cold_mult * cart.warm_mult)
        fsig = (fyig*cart.warm_mult + floog) / self.reference.harmonic
        
        # function alias
        clip = namakanui.util.clip
        
        # photonics attenuation search range
        att_max = self.photonics.max_att
        att_start = (0 if att_ini else att_max) if att_start is None else att_start
        att_min = (-6 if att_ini else 0) if att_min is None else att_min
        if att_ini:
            att_ini = self.photonics.interp_att(cart.band, lo_ghz)
            att_start += att_ini
            att_min += att_ini
        # int+round because user may have passed floats for att_start/min
        att_start = int(round(clip(att_start, 0, att_max)))
        att_min = int(round(clip(att_min, 0, att_max)))
        
        # reference output power search range
        dbm_min = self.reference.safe_dbm
        dbm_start = (0.0 if dbm_ini else dbm_min) if dbm_start is None else dbm_start
        dbm_max = (3.0 if dbm_ini else reference.max_dbm) if dbm_max is None else dbm_max
        if dbm_ini:
            ghz = lo_ghz
            dbm_band = cart.band
            if not self.photonics.simulate:
                # use the shared photonics_dbm power table
                ghz = fsig
                dbm_band = 0
            dbm_ini = self.reference.interp_dbm(dbm_band, ghz)
            dbm_start += dbm_ini
            dbm_max += dbm_ini
        dbm_start = clip(dbm_start, dbm_min, self.reference.max_dbm)
        dbm_max = clip(dbm_max, dbm_min, self.reference.max_dbm)
        
        self.log.info('att_start: %d, att_min: %d', att_start, att_min)
        self.log.info('dbm_start: %.2f, dbm_max: %.2f', dbm_start, dbm_max)
        
        att = att_start
        dbm = dbm_start
        hz = fsig*1e9
        self.log.info('reference hz: %.1f', hz)
        
        # from here on, any uncaught exception needs to set power to safe levels
        try:
            self.set_reference(hz, dbm, att)
            self.sleep(delay_secs)
            self._try_tune(cart, lo_ghz, voltage, 'att %d, dbm %.2f'%(att,dbm), skip_servo_pa, lock_only)
            
            ### PHOTONICS ATTENUATOR ADJUSTMENT
            if not self.photonics.simulate:
                # quickly decrease attenuation (raise power) if needed
                datt = max(4, int(round(photonics.counts_per_db)))
                while (cart.state['pll_unlock'] or cart.state['pll_if_power'] > pll_range[0]) and att > att_min:
                    att -= datt
                    if att < att_min:
                        att = att_min
                    self.log.info('unlock: %d, pll_if: %.3f; decreasing att to %d', cart.state['pll_unlock'], cart.state['pll_if_power'], att)
                    self._try_att(cart, lo_ghz, voltage, att, skip_servo_pa, lock_only, delay_secs)
                # increase attenuation (decrease power) if too strong
                datt = max(2, int(round(photonics.counts_per_db/3)))
                while (not cart.state['pll_unlock']) and cart.state['pll_if_power'] < pll_range[1] and att < att_max:
                    att += datt
                    if att > att_max:
                        att = att_max
                    self.log.info('unlock: %d, pll_if: %.3f; increasing att to %d', cart.state['pll_unlock'], cart.state['pll_if_power'], att)
                    self._try_att(cart, lo_ghz, voltage, att, skip_servo_pa, lock_only, delay_secs)
                # slowly decrease attenuation to target (and relock if needed)
                datt = max(1, int(round(photonics.counts_per_db/9)))
                while (cart.state['pll_unlock'] or cart.state['pll_if_power'] > pll_range[0]) and att > att_min:
                    att -= datt
                    if att < att_min:
                        att = att_min
                    self.log.info('unlock: %d, pll_if: %.3f; decreasing att to %d', cart.state['pll_unlock'], cart.state['pll_if_power'], att)
                    self._try_att(cart, lo_ghz, voltage, att, skip_servo_pa, lock_only, delay_secs)
            
            ### REFERENCE OUTPUT POWER ADJUSTMENT
            if not self.reference.simulate:
                # quickly increase power if needed
                while (cart.state['pll_unlock'] or cart.state['pll_if_power'] > pll_range[0]) and dbm < dbm_max:
                    dbm += 1.0
                    if dbm > dbm_max:
                        dbm = dbm_max
                    self.log.info('unlock: %d, pll_if: %.3f; increasing dbm to %.2f', cart.state['pll_unlock'], cart.state['pll_if_power'], dbm)
                    self._try_dbm(cart, lo_ghz, voltage, dbm, skip_servo_pa, lock_only, delay_secs)
                # decrease power if too strong
                while (not cart.state['pll_unlock']) and cart.state['pll_if_power'] < pll_range[1] and dbm > dbm_min:
                    dbm -= 0.3
                    if dbm < dbm_min:
                        dbm = dbm_min
                    self.log.info('unlock: %d, pll_if: %.3f; decreasing dbm to %.2f', cart.state['pll_unlock'], cart.state['pll_if_power'], dbm)
                    self._try_dbm(cart, lo_ghz, voltage, dbm, skip_servo_pa, lock_only, delay_secs)
                # slowly increase power to target (and relock if needed)
                while (cart.state['pll_unlock'] or cart.state['pll_if_power'] > pll_range[0]) and dbm < dbm_max:
                    dbm += 0.1
                    if dbm > dbm_max:
                        dbm = dbm_max
                    self.log.info('unlock: %d, pll_if: %.3f; increasing dbm to %.2f', cart.state['pll_unlock'], cart.state['pll_if_power'], dbm)
                    self._try_dbm(cart, lo_ghz, voltage, dbm, skip_servo_pa, lock_only, delay_secs)
            
            if cart.state['pll_unlock']:
                self.log.error('unlocked at %.3f ghz, pll_if %.3f, final att %d, dbm %.2f. setting power to safe levels.', lo_ghz, cart.state['pll_if_power'], att, dbm)
                self.set_safe()
                return False
            
            log.info('tuned to %.3f ghz, pll_if %.3f, final att %d, dbm %.2f', lo_ghz, cart.state['pll_if_power'], att, dbm)
            return True
        
        except:
            log.exception('unhandled error tuning to %.3f ghz. setting power to safe levels.', lo_ghz)
            self.set_safe()
            raise
        # Instrument.tune



# TODO: speed up cart init by saving offsets to config file.
# if they were being logged somewhere i could verify that the offsets
# are consistent and/or use an average value.

