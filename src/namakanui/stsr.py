'''
namakanui/stsr.py   RMB 20220105

Controller for the GLT Signal Test Source Reference,
which switches the FLOOG and Reference signals
(but not the receiver output IF signals)
between the different receiver cartridges.

Uses an ADAM-5000 holding the following modules:

5017 (S0):  8ch AI, monitors component voltages
5018 (S1):  7ch AI (thermocouple), monitors temperatures
5024 (S2):  4ch AO, unused, originally provided 0-10V to VGA
5056 (S3): 16ch DO, controls 5 switches, SW1-SW5.

Refer to document "GLT CAB-A1 report_20190925.pdf".


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
import adam.adam5000


class STSR(object)
    '''
    Signal Test Source Reference control class.
    '''
    def __init__(self, inifile, sleep, publish, simulate=0, level=logging.INFO):
        '''Arguments:
            inifile: Path to config file or IncludeParser instance.
            sleep(seconds): Function to sleep for given seconds, e.g. time.sleep, drama.wait.
            publish(name, dict): Function to output dict with given name, e.g. drama.set_param.
            simulate: Mask, bitwise ORed with config settings.
            level: Logging level, default INFO.
        '''
        self.config = inifile
        if not hasattr(inifile, 'items'):
            self.config = IncludeParser(inifile)
        cfg = self.config['stsr']
        self.sleep = sleep
        self.publish = publish
        self.simulate = sim.str_to_bits(cfg['simulate']) | simulate
        self.name = cfg['name']
        self.state = {'number':0}
        self.log = logging.getLogger(self.name)
        
        # TODO init other state
        
        self.adam5000 = adam.adam5000.Adam5000(cfg['ip'], int(cfg['port']),
                                               int(cfg['aa']), int(cfg['tcp']))
        
        self.log.debug('__init__ %s, sim=%d, 5000=%s:%d, aa=%s, tcp=%d',
                       self.config.inifilename, self.simulate,
                       self.adam5000.ip, self.adam5000.port,
                       self.adam5000.aa, self.adam5000.tcp)
        
        self.initialise()
        
        self.log.setLevel(level)  # set log level last to allow DEBUG output during creation
        # STSR.__init__
    
    
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
                raise RuntimeError('STSR unexpected ADAM model %s'%(model))
            # save slot indices, don't rely on docs for this
            self.slot_index = {}  # str(module):index
            for module in ['5017', '5018', '5056']:  # 5024 unused, skip it
                count = slotnames.count(module)
                if count != 1:
                    raise RuntimeError('STSR found %d %s modules'%(count, module))
                self.slot_index[module] = slotnames.index(module)
        
        self.update()
        # STSR.initialise
    
    
    def update(self):
        '''Read state from ADAM-5000 and publish state.  Call every 10s.
           NOTE: The ADAM-5000 will disconnect after a while (30s?)
                 if we don't talk to it.
        '''
        self.log.debug('update')
        
        if self.simulate and not '5017' in self.state:
            self.state['5017'] = [4.8, 3.2, 9.6, 4.8, 2.0, -2.0, 0.0, 0.0]
            self.state['5018'] = [25.0]*7
            DO = [0]*16
            self.state['5056'] = DO
        else:
            # read full lists of channel data directly into state entries
            self.state['5017'] = self.adam5000.get_ai_data(self.slot_index['5017'])
            self.state['5018'] = self.adam5000.get_ai_data(self.slot_index['5018'])
            DO = self.adam5000.get_dio_data(self.slot_index['5056'])
            self.state['5056'] = DO
        
        # determine state of switches; refer to table on page 11.
        # 5056 uses open-collector outputs, which I think means 0=H, 1=L.
        # if I've got this backward, reverse this list.
        ch = ['ch1', 'ch2', 'ch3', 'ch4']
        for swindex in range(4):
            offset = swindex*2
            chindex = DO[offset+1]*2 + DO[offset]
            self.state['sw%d'%(swindex+1)] = ch[chindex]
        # for sw5, L=230/345, H=86
        self.state['sw5'] = ['86', '230/345'][DO[8]]
        # determine band; for tuning, only sw1/sw2 matter.
        # if inconsistent, set band=0.
        # sw1: Reference to rx
        # sw2: FLOOG to rx
        # sw3: FLOOG to rx signal test source assy
        # sw4: Reference+LO2 mixer RF to rx signal test source assy
        # sw5: LO2 1.5GHz (86) or 0.5GHz (230/345)
        band = 0
        if self.state['sw1'] != 'ch4' \
            and self.state['sw1'] == self.state['sw2']:
            band = {'ch1':3, 'ch2':6, 'ch3':7}[self.state['sw1']]
        self.state['band'] = band
        
        self.state['number'] += 1
        self.publish(self.name, self.state)
        # STSR.update
    
    
    def set_5056(self, DO):
        '''Set 5056 output to given DO list.'''
        self.log.debug('set_5056(%s)', DO)
        
        if self.simulate:
            self.state['5056'] = DO
        else:
            self.adam5000.set_do_data(self.slot_index('5056'), DO)
        
        # double-check digital outputs
        self.update()
        rDO = self.state['5056']
        if DO != rDO:
            raise RuntimeError('failed to set 5056: tried %s, but status is %s'%(DO, rDO))
        
        # STSR.set_5056
    
    
    def set_band(self, band):
        '''Set 5056 DO so that sw1-sw3 are set to given band in [0,3,6,7].
           If band==0, set switches to ch4.
        '''
        self.log.debug('set_band(%s)', band)
        band = int(band)
        DO = self.state['5056']
        if band == 0:  # ch4, N/A, LL = 11
            DO = [1,1]*3 + DO[6:]
        elif band == 3:  # ch1, 86, HH = 00
            DO = [0,0]*3 + DO[6:]
        elif band == 6:  # ch2, 230, LH = 10
            DO = [1,0]*3 + DO[6:]
        elif band == 7:  # ch3, 345, HL = 01
            DO = [0,1]*3 + DO[6:]
        else:
            raise ValueError('band %d not one of [0,3,6,7]'%(band))
        
        self.set_5056(DO)
         
        # check FLOOG (31.5 MHz, LO1) lock status, expect ~4.8V
        floog_lock_v = self.state['5017'][0]
        if floog_lock_v < 4.0:
            raise RuntimeError('31.5 MHz oscillator unlocked, voltage %g'%(floog_lock_v))
        
        # STSR.set_band
        
        
    def set_tone(self, band):
        '''Set 5056 DO so that sw4 is set to given band in [0,3,6,7]
           and sw5 matches proper LO2.  If band==0, set sw4 to ch4.
        '''
        self.log.debug('set_tone(%s)', band)
        band = int(band)
        DO = self.state['5056']
        if band == 0:  # ch4, N/A, LL = 11
            DO = DO[:6] + [1,1] + DO[8:]
        elif band == 3:  # ch1, 86, HH = 00
            DO = DO[:6] + [0,0,0] + DO[9:]
        elif band == 6:  # ch2, 230, LH = 10
            DO = DO[:6] + [1,0,1] + DO[9:]
        elif band == 7:  # ch3, 345, HL = 01
            DO = DO[:6] + [0,1,1] + DO[9:]
        else:
            raise ValueError('band %d not one of [0,3,6,7]'%(band))
        
        self.set_5056(DO)
        # STSR.set_tone
    
