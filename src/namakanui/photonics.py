'''
namakanui/photonics.py  RMB 20191120

The photonics system transmits the reference signal from the
Agilent/Keysight signal generator to the IF switch in the cabin
over an optical fiber.

This class interfaces with an ADAM module that monitors the
lock status and controls the power attenuator on the output amplifier.

TODO: Lock status


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
import socket
import select
import logging
import os

import adam.adam6050


class Photonics(object):
    '''
    Class to monitor and control the photonics system.
    '''
    
    def __init__(self, inifile, sleep, publish, simulate=0, level=logging.INFO):
        '''Arguments:
            inifile: Path to config file or IncludeParser instance.
            sleep(seconds): Function to sleep for given seconds, e.g. time.sleep, drama.wait.
            publish(name, dict): Function to output dict with given name, e.g. drama.set_param.
            simulate: Mask, bitwise ORed with config settings.
        '''
        self.config = inifile
        if not hasattr(inifile, 'items'):
            self.config = IncludeParser(inifile)
        pconfig = self.config['photonics']
        self.sleep = sleep
        self.publish = publish
        self.simulate = sim.str_to_bits(pconfig['simulate']) | simulate
        self.name = pconfig['name']
        self.log = logging.getLogger(self.name)
        self.nbits = int(pconfig['nbits'])
        self.counts_per_db = float(pconfig['counts_per_db'])
        self.max_att = (1 << self.nbits) - 1
        self.state = {'number':0}
        self.adam_bits = 6
        self.state['DO'] = [0]*self.adam_bits  # needs to match ADAM type, not nbits
        # ADAM address
        self.ip = pconfig['ip']
        self.port = int(pconfig['port'])
        
        # init only saves ip/port, so this is fine even if simulating
        self.adam = adam.adam6050.Adam6050(self.ip, self.port)
        
        datapath = os.path.dirname(self.config.inifilename) + '/'
        self.att_tables = {}  # indexed by band
        for b in [3,6,7]:
            self.att_tables[b] = read_ascii(datapath + pconfig['b%d_att'%(b)])
        
        self.log.debug('__init__ %s, sim=%d, %s:%d',
                       self.config.inifilename, self.simulate, self.ip, self.port)
        
        self.initialise()
        
        self.log.setLevel(level)  # set log level last to allow DEBUG output during creation
        # Photonics.__init__
    
    
    def __del__(self):
        self.log.debug('__del__')
        self.close()
    
    
    def close(self):
        '''Close the connection to the ADAM'''
        self.log.debug('close')
        self.adam.close()
    
    
    def initialise(self):
        '''Open the connections to the ADAM and get/publish state.'''
        self.log.debug('initialise')
        
        # fix simulate set
        self.simulate &= sim.SIM_PHOTONICS
        
        self.state['simulate'] = self.simulate
        self.state['sim_text'] = sim.bits_to_str(self.simulate)
        
        self.close()
        if not self.simulate & sim.SIM_PHOTONICS:
            self.log.debug('connecting ADAM, %s:%d', self.ip, self.port)
            self.adam.connect()
            modname = self.adam.get_module_name()
            self.log.debug('ADAM module name: %s', modname)
        
        self.update()
        # Photonics.initialise
    
    
    def update(self, do_publish=True):
        '''Update and publish state.  Call every 10s.
           NOTE: The ADAM might time out and disconnect if we don't
                 talk to it every 30s or so.
        '''
        self.log.debug('update(%s)', do_publish)
        
        if not self.simulate & sim.SIM_PHOTONICS:
            DO = self.adam.get_DO_status()
            self.state['DO'] = DO
            # TODO lock status
        
        att = 0
        for i,b in enumerate(self.state['DO']):
            # TODO account for if len(DO) > self.nbits?
            att |= (b << i)
        self.state['attenuation'] = att
        
        if do_publish:
            self.state['number'] += 1
            self.publish(self.name, self.state)
        # Photonics.update


    def set_attenuation(self, counts):
        '''Set attenuator to given counts.'''
        self.log.debug('set_attenuation(%s)', counts)
        
        att = int(round(counts))
        if att < 0:
            att = 0
        if att > self.max_att:
            att = self.max_att
        
        # TODO sense, order of bits
        DO = [0]*self.adam_bits
        for i in range(len(DO)):
            DO[i] = (att >> i) & 1
        
        if self.simulate & sim.SIM_PHOTONICS:
            self.state['DO'] = DO
            self.state['attenuation'] = att
            self.update()
            return
        
        self.adam.set_DO(DO)
        
        # assume that the update() will cause sufficient delay
        # and thus no sleep is required before returning control
        self.update()
        
        # might as well double-check
        if self.state['DO'] != DO:
            raise RuntimeError('failed to set DO: tried %s, but status is %s' % (DO, self.state['DO']))
        if self.state['attenuation'] != att:
            raise RuntimeError('attenuation mismatch, expected %d but got %d for DO %s' % (att, self.state['attenuation'], DO))
        
        # Photonics.set_attenuation


    def interp_attenuation(self, band, lo_ghz):
        '''Get interpolated attenuation for this band and frequency.'''
        return interp_table(self.att_tables[band], lo_ghz).att



