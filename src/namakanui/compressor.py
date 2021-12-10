'''
namakanui/compressor.py  RMB 20211210

This class monitors the Sumitomo CNA-61D coldhead compressor
via an ADAM-6060 6-channel DI / 6-channel DO (relay) unit.

ADAM-6060 DI reads:
    dry: 0 = close to ground
         1 = open
    wet: 0 =  0~3  Vdc
         1 = 10~30 Vdc


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

import adam.adam6060


class Compressor(object):
    '''
    Class to monitor the Sumitomo CNA-61D coldhead compressor.
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
        cconfig = self.config['compressor']
        self.sleep = sleep
        self.publish = publish
        self.simulate = sim.str_to_bits(cconfig['simulate']) | simulate
        self.name = cconfig['name']
        self.log = logging.getLogger(self.name)
        self.state = {'number':0}
        self.state['DI'] = [0]*6
        self.state['DO'] = [0]*6
        # ADAM address
        self.ip = cconfig['ip']
        self.port = int(cconfig['port'])
        
        # DO channels (0-based)
        self.remote_reset_ch = 0
        self.remote_drive_ch = 1
        
        # init only saves ip/port, so this is fine even if simulating
        self.adam = adam.adam6060.Adam6060(self.ip, self.port)
        
        self.log.debug('__init__ %s, sim=%d, %s:%d',
                       self.config.inifilename, self.simulate, self.ip, self.port)
        
        self.initialise()
        
        self.log.setLevel(level)  # set log level last to allow DEBUG output during creation
        # Compressor.__init__
    
    
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
        self.simulate &= sim.SIM_COMPRESSOR
        
        self.state['simulate'] = self.simulate
        self.state['sim_text'] = sim.bits_to_str(self.simulate)
        
        self.close()
        if not self.simulate & sim.SIM_COMPRESSOR:
            self.log.debug('connecting ADAM, %s:%d', self.ip, self.port)
            self.adam.connect()
            modname = self.adam.get_module_name()
            self.log.debug('ADAM module name: %s', modname)
        
        self.update()
        # Compressor.initialise
    
    
    def update(self, do_publish=True):
        '''Update and publish state.  Call every 10s.
           NOTE: The ADAM might time out and disconnect if we don't
                 talk to it every 30s or so.
        '''
        self.log.debug('update(%s)', do_publish)
        
        if self.simulate:
            DI = [0,0,1,1,0,0]
            DO = self.state['DO']
        else:
            DI = self.adam.get_DI_status()
            DO = self.adam.get_DO_status()
        
        self.state['DI'] = DI
        self.state['DO'] = DO
            
        # DI state
        # pressure alarm pins 1,2: normal=close (0), alarm=open (1)
        self.state['pressure_alarm'] = DI[0]
        # temperature alarm pins 3,4: normal=close (0), alarm=open (1)
        self.state['temp_alarm'] = DI[1]
        # drive indication pins 6,7: stop=0Vdc (0), operate=24Vdc (1)
        self.state['drive_operating'] = DI[2]
        # control voltage pins 7,13: off=0Vdc (0), on=24Vdc (1)
        self.state['main_power_sw'] = DI[3]
        
        # DO state
        # remote reset pins 12,14: pulsed 24Vdc for 1s
        self.state['remote_reset'] = DO[self.remote_reset_ch]
        # remote drive pins 8,15: stop=open (0), drive=close (1)
        self.state['remote_drive'] = DO[self.remote_drive_ch]
        
        if do_publish:
            self.state['number'] += 1
            self.publish(self.name, self.state)
        # Compressor.update
    
    
    def remote_reset(self):
        '''Pulse the remote reset pins 12,14 for 1s.'''
        self.log.info('remote_reset')
        DO = self.state['DO']
        DO[self.remote_reset_ch] = 1
        if self.simulate:
            self.state['DO'] = DO
        else:
            self.adam.set_DO(DO)
        self.update()
        self.sleep(1)
        self.update()  # state might have changed while we slept
        DO = self.state['DO']
        DO[self.remote_reset_ch] = 0
        if self.simulate:
            self.state['DO'] = DO
        else:
            self.adam.set_DO(DO)
        self.update()
        # Compressor.remote_reset
    
    
    def remote_drive(self, setting):
        '''Set remote drive output.  Argument:
            setting: 0=stop, 1=drive
        '''
        self.log.info('remote_drive(%s)', setting)
        setting = int(bool(setting))  # 0/1
        DO = self.state['DO']
        DO[self.remote_drive_ch] = setting
        if self.simulate:
            self.state['DO'] = DO
        else:
            self.adam.set_DO(DO)
        self.update()
        # Compressor.remote_drive
    
    
