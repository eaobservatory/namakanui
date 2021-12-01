'''
namakanui/pmeter.py  RMB 20210209

Class to control an N1913A power meter.


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
import logging


class PMeter(object):
    '''
    Class to control an N1913A power meter.
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
        pconfig = self.config['pmeter']
        self.sleep = sleep
        self.publish = publish
        self.simulate = sim.str_to_bits(pconfig['simulate']) | simulate
        self.name = pconfig['name']
        self.log = logging.getLogger(self.name)
        
        self.state = {'number':0}
       
        self.ip = pconfig['ip']
        self.port = int(pconfig['port'])
        self.timeout = float(pconfig['timeout'])
        
        self.s = socket.socket()  # declare for close()
        
        self.log.debug('__init__ %s, sim=%d, %s:%d',
                       self.config.inifilename, self.simulate, self.ip, self.port)
        
        self.initialise()
        
        self.log.setLevel(level)  # set log level last to allow DEBUG output during creation
        # PMeter.__init__
    
    
    def __del__(self):
        self.log.debug('__del__')
        self.close()
    
    
    def close(self):
        '''Close the connection to the power meter'''
        self.log.debug('close')
        self.s.close()
    
    
    def initialise(self):
        '''Open the connection to the power meter and get/publish state.'''
        self.log.debug('initialise')
        
        # fix simulate set  (NOTE simulate not supported for this class)
        self.simulate &= 0
        self.state['simulate'] = self.simulate
        self.state['sim_text'] = sim.bits_to_str(self.simulate)
        
        self.state['power'] = 0.0
        self.state['ghz'] = 0.0
        
        self.close()
        try:
            self.log.debug('connecting power meter, %s:%d', self.ip, self.port)
            self.s = socket.socket()
            self.s.settimeout(self.timeout)
            self.s.connect((self.ip, self.port))
            self.s.send(b'*idn?\n')
            idn = self.s.recv(256)
            if b'N1913A' not in idn:
                raise RuntimeError(f'expected power meter model N1913A, but got {idn}')
            # TODO control setup via config
            self.s.send(b'*cls\n')  # clear errors
            self.s.send(b'unit:power dbm\n')  # dBm readings
            self.s.send(b'init:cont on\n')  # free run mode
            self.s.send(b'mrate normal\n')  # 20 reads/sec
            self.s.send(b'calc:hold:stat off\n')  # no min/max stuff
            self.s.send(b'aver:count:auto on\n')  # auto filter settings
            self.s.send(b'syst:err?\n')
            err = self.s.recv(256)
            if not err.startswith(b'+0,"No error"'):
                raise RuntimeError(f'power meter N1913A setup failure: {err}')
        except:
            self.close()
            raise
        self.update()
        # PMeter.initialise


    def update(self, do_publish=True):
        '''Update and publish state.  Call every 10s.
           NOTE: The ADAM might time out and disconnect if we don't
                 talk to it every 30s or so.
        '''
        self.log.debug('update(%s)', do_publish)
        
        self.state['power'] = self.read_power()
        
        if do_publish:
            self.state['number'] += 1
            self.publish(self.name, self.state)
        # PMeter.update


    def read_power(self):
        '''Return power reading in dBm.  TODO use self.sleep()'''
        self.s.send(b'fetch?\n')
        return float(self.s.recv(256))


    def set_ghz(self, ghz):
        '''Set frequency for power sensor calibration tables'''
        ghz = float(ghz)
        self.s.send(b'freq %gGHz\n'%(ghz))
        self.state['ghz'] = ghz
        
