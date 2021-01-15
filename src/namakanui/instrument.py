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
        self.hardware = []
        self.carts = {}
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
        self.agilent = None
        self.ifswitch = None
        self.load = None
        self.photonics = None
        self.femc = None
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
        self.photonics = namakanui.photonics.Photonics(inifile, sleep, publish, simulate)
        self.femc = namakanui.femc.FEMC(inifile, sleep, publish, simulate)
        
        self.hardware = [self.agilent, self.ifswitch, self.load, self.photonics, self.femc]
        
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
            Updates one of: agilent, ifswitch, load, photonics, femc.
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
