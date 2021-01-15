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
import namakanui.femc
import namakanui.ifswitch
import namakanui.load
import namakanui.photonics
import namakanui.util


class Instrument(object):
    '''
    Class to contain instances for the whole receiver system.
    '''
    
    def __init__(self, inifile, sleep, publish, simulate=None):
        '''Arguments:
            inifile: Path to config file or IncludeParser instance.
            sleep(seconds): Function to sleep for given seconds, e.g. time.sleep, drama.wait.
            publish(name, dict): Function to output dict with given name, e.g. drama.set_param.
            simulate: Bitmask. If not None (default), overrides settings in inifiles.
        '''
        self.sleep = sleep
        self.publish = publish
        self.close_funcs = []
        self.initialise(inifile, simulate)
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
        self.update_funcs_slow = []
        self.update_funcs_cart = []
        self.update_index_slow = -1
        self.update_index_cart = -1
        self.agilent = None
        self.carts = {}
        self.femc = None
        self.ifswitch = None
        self.load = None
        self.photonics = None
        # Instrument.close
    
    
    def initialise(self, inifile, simulate=None):
        '''Create all instances.
           Arguments:
            inifile: Path to config file or IncludeParser instance.
            simulate: Bitmask. If not None (default), overrides settings in inifiles.
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
        
        self.agilent = namakanui.agilent.Agilent(inifile, sleep, publish, simulate)
        self.ifswitch = namakanui.ifswitch.IFSwitch(inifile, sleep, publish, simulate)
        self.load = namakanui.load.Load(inifile, sleep, publish, simulate)
        
        self.close_funcs = [self.agilent.close, self.ifswitch.close, self.load.close]
        self.update_funcs_slow = [self.agilent.update, self.ifswitch.update, self.load.update]
        
        # NOTE if SIM_PHOTONICS we just delete the instance --
        # if we can't control the attenuator, we need to control agilent dbm.
        # TODO have tune() check for photonics.simulate instead of None.
        self.photonics = namakanui.photonics.Photonics(inifile, sleep, publish, simulate)
        if self.photonics.simulate:
            self.photonics = None
        else:
            self.close_funcs.append(self.photonics.close)
            self.update_funcs_slow.append(self.photonics.update)
        
        # NOTE if SIM_FEMC we just delete the instance (sim unsupported)
        self.femc = namakanui.femc.FEMC(inifile, sleep, publish, simulate)
        if self.femc.simulate:
            self.femc = None
        else:
            self.close_funcs.append(self.femc.close)
            # NOTE no femc.update function
        
        for band in self.bands:
            self.carts[band] = namakanui.cart.Cart(band, self.femc, inifile, sleep, publish, simulate)
        
        # stagger the cart update functions
        self.update_funcs_cart += [cart.update_a for cart in self.carts.values()]
        self.update_funcs_cart += [cart.update_b for cart in self.carts.values()]
        self.update_funcs_cart += [cart.update_c for cart in self.carts.values()]
        
        # reconstruct full simulate bitmask from all components
        things = [self.agilent, self.ifswitch, self.load]
        things += [self.photonics] if self.photonics else []
        things += [self.femc] if self.femc else []
        things += list(self.carts.values())
        self.simulate = 0
        for thing in things:
            self.simulate |= thing.simulate
        self.state['simulate'] = self.simulate
        self.state['sim_text'] = sim.bits_to_str(self.simulate)
        
        # TODO REMOVE.  This may not be necessary if each component
        #               already does an update() in its initialise().
        self.update_all()
        # Instrument.initialise


    def update_all(self):
        '''Update and publish all instances.'''
        self.log.debug('update_all')
        self.agilent.update() if self.agilent else None
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
        '''Call a single update function and advance the index.
            Updates one of: agilent, ifswitch, load, photonics.
            Recommended 10s cycle, call delay 10.0/len(update_funcs_slow).
        '''
        self.log.debug('update_one_slow')
        if not self.update_funcs_slow:  # called after close()
            return
        self.update_index_slow = (self.update_index_slow + 1) % len(self.update_funcs_slow)
        self.update_funcs_slow[self.update_index_slow]()
        # Instrument.update_one_slow()
    
    
    def update_one_cart(self):
        '''Call a single update function and advance the index.
            Recommended 20s cycle, call delay 20.0/len(update_funcs_cart).
            NOTE: Background carts really don't need fast updates.
                  Use a separate 5s cycle to monitor the current band:
                  carts[band].update_one(); sleep(1.66)
        '''
        self.log.debug('update_one_cart')
        if not self.update_funcs_cart:  # called after close()
            return
        self.update_index_cart = (self.update_index_cart + 1) % len(self.update_funcs_cart)
        self.update_funcs_cart[self.update_index_cart]()
        # Instrument.update_one_cart()
    

# switching bands needs to set power to safe levels, so it belongs here.
# it should also cut PA/LNA power to other bands to avoid interference.
# cart should have a zero() function to ramp down without power-off.
# even "single-band" scripts will want to do this, so perhaps it's
# inappropriate not to include the other carts.  remove "band" option.

# TODO: speed up cart init by saving offsets to config file.
# if they were being logged somewhere i could verify that the offsets
# are consistent and/or use an average value.

# tuning involves multiple systems and should also switch bands if needed,
# so it belongs here too.
