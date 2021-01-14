'''
namakanui/instrument.py   RMB 20210113

Instrument class to contain instances for the whole receiver system.


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

from namakanui.ini import *
from namakanui import sim
import logging

import namakanui.agilent
import namakanui.cart
import namakanui.cryo
import namakanui.femc
import namakanui.ifswitch
import namakanui.load
import namakanui.photonics
import namakanui.util


class Instrument(object):
    '''
    Class to contain instances for the whole receiver system.
    '''
    
    def __init__(self, inifile, sleep, publish, simulate=None, band=0):
        '''Arguments:
            inifile: Path to config file or IncludeParser instance.
            sleep(seconds): Function to sleep for given seconds, e.g. time.sleep, drama.wait.
            publish(name, dict): Function to output dict with given name, e.g. drama.set_param.
            simulate: Bitmask. If not None (default), overrides settings in inifiles.
            band: If not 0 (default), only create a Cart for given band.
        '''
        self.config = inifile
        if not hasattr(inifile, 'items'):
            self.config = IncludeParser(inifile)
        cfg = self.config['instrument']
        self.sleep = sleep
        self.publish = publish
        self.sim_arg = simulate
        # TODO REMOVE? We don't really want config to override subconfigs,
        # and there are no Instrument-specific sim bits
        if simulate is not None:
            self.simulate = simulate
        else:
            self.simulate = sim.str_to_bits(cfg['simulate'])
        self.name = cfg['pubname']
        self.logname = cfg['logname']
        self.log = logging.getLogger(self.logname)
        self.state = {'number':0}
        
        # each included bandX.ini file adds itself to the [bands] config entry
        self.band = band
        self.bands = [int(x) for x in self.config['bands']]
        if self.band and self.band not in self.bands:
            raise ValueError('band %d not in %s'%(self.band, self.bands))
        
        self.close_funcs = []
        
        self.log.debug('__init__ %s, sim=%d, band=%s',
                       self.config.inifilename, self.simulate, self.band)
        
        self.initialise()
        # Instrument.__init__


    def __del__(self):
        self.log.debug('__del__')
        self.close()
        # Instrument.__del__
    
    
    def close(self):
        '''Close all instances and set to None'''
        self.log.debug('close')
        for f in self.close_funcs:
            try:
                f()
            except:
                pass
        self.close_funcs = []
        self.update_slow_funcs = []
        self.update_cart_funcs = []
        self.agilent = None
        self.carts = {}
        self.cryo = None
        self.femc = None
        self.ifswitch = None
        self.load = None
        self.photonics = None
        # Instrument.close
    
    
    def initialise(self):
        '''Create all instances.'''
        self.log.debug('initialise')
        
        # TODO: reread config file?
        
        self.state['simulate'] = self.simulate
        self.state['sim_text'] = sim.bits_to_str(self.simulate)
        self.state['band'] = self.band
        
        self.close()
        
        self.update_slow_index = -1
        self.update_cart_index = -1
        
        self.agilent = namakanui.agilent.Agilent(self.config, self.sleep, self.publish, self.sim_arg)
        self.cryo = namakanui.cryo.Cryo(self.config, self.sleep, self.publish, self.sim_arg)
        self.ifswitch = namakanui.ifswitch.IFSwitch(self.config, self.sleep, self.publish, self.sim_arg)
        self.load = namakanui.load.Load(self.config, self.sleep, self.publish, self.sim_arg)
        
        self.close_funcs = [self.agilent.close, self.ifswitch.close, self.load.close]
        self.update_slow_funcs = [self.agilent.update, self.cryo.update,
                                  self.ifswitch.update, self.load.update]
        
        # NOTE if SIM_PHOTONICS we just delete the instance --
        # if we can't control the attenuator, we need to control agilent dbm.
        # TODO have tune() check for photonics.simulate instead of None.
        self.photonics = namakanui.photonics.Photonics(self.config, self.sleep, self.publish, self.sim_arg)
        if self.photonics.simulate:
            self.photonics = None
        else:
            self.close_funcs.append(self.photonics.close)
            self.update_slow_funcs.append(self.photonics.update)
        
        # NOTE if SIM_FEMC we just delete the instance (unsupported)
        self.femc = namakanui.femc.FEMC(self.config, self.sleep, self.publish, self.sim_arg)
        if self.femc.simulate:
            self.femc = None
        else:
            self.close_funcs.append(self.femc.close)
            # NOTE no femc.update function
        
        bands = [self.band] if self.band else self.bands
        for band in bands:
            self.carts[band] = namakanui.cart.Cart(band, self.femc, self.config, self.sleep, self.publish, self.sim_arg)
        
        # stagger the cart update functions
        self.update_cart_funcs += [cart.update_a for cart in self.carts.values()]
        self.update_cart_funcs += [cart.update_b for cart in self.carts.values()]
        self.update_cart_funcs += [cart.update_c for cart in self.carts.values()]
        
        self.update_all()
        # Instrument.initialise


    def update_all(self):
        '''Update and publish all instances.'''
        self.log.debug('update_all')
        self.agilent.update() if self.agilent else None
        self.cryo.update() if self.cryo else None
        self.ifswitch.update() if self.ifswitch else None
        self.load.update() if self.load else None
        self.photonics.update() if self.photonics else None
        # NOTE no femc.update function
        for cart in self.carts.values():
            cart.update_all()
        self.state['number'] += 1
        self.publish(self.name, self.state)
        # Instrument.update_all()
    
    
    def update_one_slow(self):
        '''Call a single update function and advance the index.'''
        self.log.debug('update_one_slow')
        if not self.update_slow_funcs:  # called after close()
            return
        self.update_slow_index = (self.update_slow_index + 1) % len(self.update_slow_funcs)
        self.update_slow_funcs[self.update_slow_index]()
        # Instrument.update_one_slow()
    
    
    def update_one_cart(self):
        '''Call a single update function and advance the index.'''
        self.log.debug('update_one_cart')
        if not self.update_cart_funcs:  # called after close()
            return
        self.update_cart_index = (self.update_cart_index + 1) % len(self.update_cart_funcs)
        self.update_cart_funcs[self.update_cart_index]()
        # Instrument.update_one()
    

# switching bands needs to set power to safe levels, so it belongs here.

# tuning involves multiple systems and should also switch bands if needed,
# so it belongs here too.
