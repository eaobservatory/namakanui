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
    
    def __init__(self, inifile=None, sleep=time.sleep, publish=namakanui.nop, simulate=0, level=logging.INFO):
        '''Arguments:
            inifile: Path to config file (instrument.ini if None) or IncludeParser instance.
            sleep(seconds): Function to sleep for given seconds, e.g. time.sleep, drama.wait.
            publish(name, dict): Function to output dict with given name, e.g. drama.set_param.
            simulate: Mask, bitwise ORed with config settings.
            level: Logging level, passed on to component instances.
                   Can also be a dict with the following keys:
                        default, instrument, reference, photonics, ifswitch, load, femc, bandX
        '''
        self.sleep = sleep
        self.publish = publish
        self.hardware = []
        self.carts = {}
        if inifile is None:
            binpath, datapath = namakanui.util.get_paths()
            inifile = datapath + 'instrument.ini'
        self.initialise(inifile, simulate, level)
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
    
    
    def initialise(self, inifile, simulate=0, level=logging.INFO):
        '''Create all instances.
           Arguments:
            inifile: Path to config file or IncludeParser instance.
            simulate: Mask, bitwise ORed with config settings.
        '''
        if not hasattr(inifile, 'items'):
            inifile = IncludeParser(inifile)
        self.config = inifile
        cfg = self.config['instrument']
        
        self.name = cfg['name']
        self.log = logging.getLogger(self.name)
        self.state = {'number':0}
        
        self.log.debug('initialise')
        
        # each included bandX.ini file adds itself to the [bands] config entry
        self.bands = [int(x) for x in self.config['bands']]
        
        # simulate param in [instrument] would cause confusion;
        # we only check simulate in each individual config section.
        if 'simulate' in cfg:
            self.log.warn('ignoring "simulate" parameter in %s', self.config.inifilename)
        
        sleep = self.sleep
        publish = self.publish
        
        self.close()

        if not hasattr(level, 'keys'):
            level = {'default': level}
        if not 'default' in level:
            level['default'] = logging.INFO
        default = level['default']
        
        self.reference = namakanui.reference.Reference(inifile, sleep, publish, simulate, level.get('reference', default))
        self.ifswitch = namakanui.ifswitch.IFSwitch(inifile, sleep, publish, simulate, level.get('ifswitch', default))
        self.load = namakanui.load.Load(inifile, sleep, publish, simulate, level.get('load', default))
        self.photonics = namakanui.photonics.Photonics(inifile, sleep, publish, simulate, level.get('photonics', default))
        self.femc = namakanui.femc.FEMC(inifile, sleep, publish, simulate, level.get('femc', default))
        
        self.hardware = [self.reference, self.ifswitch, self.load, self.photonics, self.femc]
        
        # build up simulate bitmask from individual components
        self.simulate = 0
        for thing in self.hardware:
            self.simulate |= thing.simulate
        
        for band in self.bands:
            cart = namakanui.cart.Cart(band, self.femc, inifile, sleep, publish, simulate, level.get(f'band{band}', default))
            self.carts[band] = cart
            self.simulate |= cart.simulate
        
        self.state['simulate'] = self.simulate
        self.state['sim_text'] = sim.bits_to_str(self.simulate)
        self.state['bands'] = self.bands
        
        # NOTE each component already does an update() in its initialise().
        self.update()

        self.log.setLevel(level.get('instrument', default))  # set log level last to allow DEBUG output during creation
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
        self.hardware[self.update_index_hw].update()
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
        self.ifswitch.set_band(band)
        # zero bias/amps/magnets on all carts to reduce interference
        for cart in self.carts.values():
            cart.zero()
            cart.update_all()
        # enable cart power for the FLOOG check below
        cart = self.carts[band]
        cart.power(1)
        # check FLOOG power to make sure band is really selected
        if cart.state['pd_enable'] and not cart.sim_warm:
            rp = cart.state['pll_ref_power']
            if rp < -3.0:
                raise RuntimeError(f'PLL ref power {rp:.2f}V (FLOOG 31.5 MHz): too strong, please attenuate.')
            if rp > -0.5:
                raise RuntimeError(f'PLL ref power {rp:.2f}V (FLOOG 31.5 MHz): too weak, IF switch may have failed to select band {band}')
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
        # ensure we try to set both, even if one raises an error
        try:
            self.photonics.set_attenuation(self.photonics.max_att)
        finally:
            self.reference.set_dbm(self.reference.safe_dbm)
            self.reference.set_output(0)
            self.reference.update(publish_only=True)
        # Instrument.set_safe
    


# TODO: speed up cart init by saving offsets to config file.
# if they were being logged somewhere i could verify that the offsets
# are consistent and/or use an average value.

