'''
namakanui/rfsma.py   RMB 20220113

Controller for RF Switch Matrix Assembly.
This module holds an array of switches to direct inputs
to a set of power meters and a spectrum analyzer.

The RFSMA is actually two separate units, labeled A14 and A17
on the system block diagram.  An instance of this class only
controls one unit, handling either of:

A14: EHT#1, USB
A17: EHT#2, LSB

Uses an ADAM-5000 holding the following modules:

5017 (S0):  8ch AI, monitors component voltages
5018 (S1):  7ch AI (thermocouple), monitors temperatures
5056 (S2): 16ch DO, controls  S1-16 (2-position)
5056 (S3): 16ch DO, controls S17-20 (4-position)
5056 (S4): 16ch DO, controls S21-24 (4-position)
5056 (S5): 16ch DO, controls S25-27 (4-position)

Refer to documents:

GLT-CAB-A14.pdf
RF switch control logic_2022_update.xlsx


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


class RFSMA(object)
    '''
    RF Switch Matrix Assembly control class.
    '''
    def __init__(self, inifile, section, sleep=time.sleep, publish=namakanui.nop, simulate=0, level=logging.INFO):
        '''Arguments:
            inifile: Path to config file or IncludeParser instance.
            section: Config file [section] name to use, e.g. "rfsma_a14"
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
        # RFSMA.__init__
    
    
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
        self.simulate &= sim.SIM_STSR
        
        self.state['simulate'] = self.simulate
        self.state['sim_text'] = sim.bits_to_str(self.simulate)
        
        self.close()
        if not self.simulate & sim.SIM_STSR:
            self.log.debug('connecting adam5000, %s:%d', self.adam5000.ip, self.adam5000.port)
            self.adam5000.connect()
            model = self.adam5000.get_module_name()
            slotnames = self.adam5000.get_slot_names()
            self.log.debug('adam5000 model: %s, slots: %s', model, slotnames)
            if not '5000' in model:
                raise RuntimeError('RFSMA unexpected ADAM model %s'%(model))
        
        self.update()
        # RFSMA.initialise
    
    
    def update(self):
        '''Read state from ADAM-5000 and publish state.  Call every 10s.
           NOTE: The ADAM-5000 will disconnect after a while (30s?)
                 if we don't talk to it.
        '''
        self.log.debug('update')
        
        if self.simulate and not '5017' in self.state:
            self.state['5017'] = [0.0, 0.0, 9.6, 4.8]
            self.state['5018'] = [25.0]*4
            for i in range(2,6):
                DO = [0]*16
                self.state['5056_s%d'%(i)] = DO
        else:
            # read full lists of channel data directly into state entries
            self.state['5017'] = self.adam5000.get_ai_data(self.slot_index['5017'])[:4]
            self.state['5018'] = self.adam5000.get_ai_data(self.slot_index['5018'])[:4]
            for i in range(2,6):
                slot_name = '5056_s%d'%(i)
                DO = self.adam5000.get_dio_data(self.slot_index[slot_name])
                self.state[slot_name] = DO
        
        self.state['number'] += 1
        self.publish(self.name, self.state)
        # RFSMA.update
    
    
    def set_DO(self, slot_name, DO, index=0):
        '''
        Set output of 5056 in slot_name to given DO list, which is copied
        into the current state starting at the given index (which can limit
        the change to a single switch in a bank, if desired).  Examples:
        
        set_DO('5056_s2', [0]*16)  # set S1-16 to spectrum analyzer outputs
        set_DO('5056_s2', [1]*16)  # set S1-16 to power meter outputs
        set_DO('5056_s3', [1,0,0,0]*2)  # set S17-18 to IF 4-9 GHz
        set_DO('5056_s5', [1,0]*2, 4)  # set S26-27 to send J18 to spectr
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
        
        # RFSMA.set_DO
    
    
    def set_pmeter_49(self):
        '''
        Send J1/J5 (P0/P1 IF 4-9 GHz) to power meter #1 ch A/B.
        Only sets S1, S5, S17, S18, leaving all others unchanged.
        '''
        self.log.debug('set_pmeter_49')
        self.set_DO('5056_s2', [1], 0)  # S1
        self.set_DO('5056_s2', [1], 4)  # S5
        self.set_DO('5056_s3', [1,0,0,0]*2)  # S17-18
    
    
