'''
namakanui/cdpsm.py   RMB 20220119

Controller for A11, Continuum Detector & Phase Stability Monitor.

Uses an ADAM-5000 holding the following modules:

5017 (S0):  8ch AI, monitors component voltages
5018 (S1):  7ch AI (thermocouple), monitors temperatures
5024 (S2):  4ch AO, unused
5056 (S3): 16ch DO, controls switches SW1-6

Refer to documents:

GLT_Modbus.xlsx


Copyright (C) 2022 East Asian Observatory

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
import logging
import time
import adam.adam5000


class CDPSM(object)
    '''
    Continuum Detector & Phase Stability Monitor control class.
    '''
    def __init__(self, inifile, section='cdpsm', sleep=time.sleep, publish=namakanui.nop, simulate=0, level=logging.INFO):
        '''Arguments:
            inifile: Path to config file or IncludeParser instance.
            section: Config file [section] name to use, default "cdpsm"
            sleep(seconds): Function to sleep for given seconds, e.g. time.sleep, drama.wait.
            publish(name, dict): Function to output dict with given name, e.g. drama.set_param.
            simulate: Mask, bitwise ORed with config settings.
            level: Logging level, default INFO.
        '''
        self.config = inifile
        if not hasattr(inifile, 'items'):
            self.config = IncludeParser(inifile)
        self.section = section
        cfg = self.config[section]
        self.sleep = sleep
        self.publish = publish
        self.simulate = sim.str_to_bits(cfg['simulate']) | simulate
        self.name = cfg['name']
        self.state = {'number':0}
        self.log = logging.getLogger(self.name)
        
        # adam5000.get_slot_names is unreliable, so get slots from cfg
        slots = cfg['slots'].split()
        self.slot_index = {}  # str(module):index
        for i,s in enumerate(slots):
            self.slot_index[s] = i
        
        self.adam5000 = adam.adam5000.Adam5000(cfg['ip'], int(cfg['port']),
                                               int(cfg['aa']), int(cfg['tcp']),
                                               level=level)
        
        self.log.debug('__init__ %s, sim=%d, 5000=%s:%d, aa=%s, tcp=%d',
                       self.config.inifilename, self.simulate,
                       self.adam5000.ip, self.adam5000.port,
                       self.adam5000.aa, self.adam5000.tcp)
        
        self.initialise()
        
        self.log.setLevel(level)  # set log level last to allow DEBUG output during creation
        # CDPSM.__init__
    
    
    def __del__(self):
        self.log.debug('__del__')
        self.close()
    
    
    def close(self):
        '''Close the ADAM-5000.'''
        self.log.debug('close')
        self.adam5000.close()
    
    
    def initialise(self):
        '''Open connection to ADAM-5000 and get/publish state.'''
        self.log.debug('initialise')
        
        # fix simulate set
        self.simulate &= 0
        
        self.state['simulate'] = self.simulate
        self.state['sim_text'] = sim.bits_to_str(self.simulate)
        
        self.close()
        if not self.simulate:
            self.log.debug('connecting adam5000, %s:%d', self.adam5000.ip, self.adam5000.port)
            self.adam5000.connect()
            model = self.adam5000.get_module_name()
            slotnames = self.adam5000.get_slot_names()
            self.log.debug('adam5000 model: %s, slots: %s', model, slotnames)
            if not '5000' in model:
                raise RuntimeError('CDPSM unexpected ADAM model %s'%(model))
        
        self.update()
        # CDPSM.initialise
    
    
    def update(self):
        '''Read state from ADAM-5000 and publish state.  Call every 10s.
           NOTE: The ADAM-5000 will disconnect after a while (30s?)
                 if we don't talk to it.
        '''
        self.log.debug('update')
        
        if self.simulate and not '5017' in self.state:
            self.state['5017'] = [-2.2, -2.2, 5.0, 5.9, 4.8, 0.0, 0.0, 0.2]
            self.state['5018'] = [25.0]*5
            self.state['5056'] = [0]*16
        else:
            # read full lists of channel data directly into state entries
            self.state['5017'] = self.adam5000.get_ai_data(self.slot_index['5017'])
            self.state['5018'] = self.adam5000.get_ai_data(self.slot_index['5018'])[:5]
            DO = self.adam5000.get_dio_data(self.slot_index['5056'])
            self.state['5056'] = DO
        
        # TODO additional state from DO
        
        self.state['number'] += 1
        self.publish(self.name, self.state)
        # CDPSM.update
    
    
    def set_DO(self, slot_name, DO, index=0):
        '''
        Set output of 5056 in slot_name to given DO list, which is copied
        into the current state starting at the given index (which can limit
        the change to a single switch in a bank, if desired).  Examples:
        
        TODO
        '''
        self.log.debug('set_DO(%s, %s, %s)', slot_name, DO, index)
        
        sDO = self.state[slot_name].copy()
        sDO[index:index+len(DO)] = DO
        DO = sDO[:16]
        
        if self.simulate:
            self.state[slot_name] = DO
        else:
            self.adam5000.set_do_data(self.slot_index[slot_name], DO)
        
        # double-check digital outputs
        self.update()
        rDO = self.state[slot_name]
        if DO != rDO:
            raise RuntimeError('failed to set %s: tried %s, but status is %s'%(slot_name, DO, rDO))
        
        # CDPSM.set_DO
    
    
    def set_sw12(self, sw, src):
        '''
        Set SW1 (LHC source) or SW2 (RHC source) to given src:
         - 0 == "LSB" == "EHT2"
         - 1 == "USB" == "EHT1"
        '''
        self.log.debug('set_sw12(%s, %s)', sw, src)
        
        if sw not in [1,2]:
            raise ValueError('sw %s not in range [1,2]'%(sw))
        
        if hasattr(src, 'upper'):
            src = src.upper()
        else:
            src = int(src)
        src = {0:0, '0':0, 'LSB':0, 'EHT2':0,
               1:1, '1':1, 'USB':1, 'EHT1':1}[src]
        
        self.set_DO('5056', [src], sw-1)
        # CDPSM.set_sw12
    
    
    def set_sw3(self, pol):
        '''
        Set SW3 (polarization selector) to given pol:
         - 0 == "POL0" == "LHC"
         - 1 == "POL1" == "RHC"
        '''
        self.log.debug('set_sw3(%s)', pol)
        
        if hasattr(src, 'upper'):
            src = src.upper()
        else:
            src = int(src)
        src = {0:0, '0':0, 'POL0':0, 'LHC':0,
               1:1, '1':1, 'POL1':1, 'RHC':1}[src]
        
        self.set_DO('5056', [src], 2)
        # CDPSM.set_sw3
    
    
    def set_sw456(self, band):
        '''
        Set SW4-6 to positions for given band:
         - 3 == 86
         - 6 == 7 == 230 == 345
        '''
        self.log.debug('set_sw456(%s)', band)
        
        band = int(band)
        band = {3:3, 6:6, 7:6, 86:3, 230:6, 345:6}[band]
        DO = {3:[1,0,0], 6:[0,1,1]}[band]
        
        self.set_DO('5056', DO, 3)
        # CDPSM.set_sw456
        
        
    ##### alias functions: #####
    
    def set_LHC_source(self, src):
        '''
        Set SW1 to given src:
         - 0 == "LSB" == "EHT2"
         - 1 == "USB" == "EHT1"
        '''
        self.set_sw12(1, src)
        
    def set_RHC_source(self, src):
        '''
        Set SW2 to given src:
         - 0 == "LSB" == "EHT2"
         - 1 == "USB" == "EHT1"
        '''
        self.set_sw12(2, src)
    
    def set_polarization(self, pol):
        '''
        Set SW3 to given pol:
         - 0 == "POL0" == "LHC"
         - 1 == "POL1" == "RHC"
        '''
        self.set_sw3(pol)
    
    def set_band(self, band):
        '''
        Set SW4-6 to analysis signal positions for given band:
         - 3 == 86
         - 6 == 7 == 230 == 345
        '''
        self.set_sw456(band)

