'''
namakanui/pmeter2.py  RMB 20220118

Class to control a two-channel N1914A power meter.


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


class PMeter2(object):
    '''
    Class to control an N1914A power meter.
    '''
    
    def __init__(self, inifile, section, sleep=time.sleep, publish=namakanui.nop, simulate=0, level=logging.INFO):
        '''Arguments:
            inifile: Path to config file or IncludeParser instance.
            section: Config file [section] name to use, e.g. "rfsma_p1"
            sleep(seconds): Function to sleep for given seconds, e.g. time.sleep, drama.wait.
            publish(name, dict): Function to output dict with given name, e.g. drama.set_param.
            simulate: Mask, bitwise ORed with config settings.
            level: Logging level, default INFO
        '''
        self.config = inifile
        if not hasattr(inifile, 'items'):
            self.config = IncludeParser(inifile)
        self.section = section
        pconfig = self.config[section]
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
        # PMeter2.__init__
    
    
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
        
        self.state['power'] = [0.0]*2
        self.state['ghz'] = [0.0]*2
        
        self.close()
        try:
            self.log.debug('connecting power meter, %s:%d', self.ip, self.port)
            self.s = socket.socket()
            self.s.settimeout(self.timeout)
            self.s.connect((self.ip, self.port))
            
            self.s.send(b'*idn?\n')
            self.idn = self.s.recv(256).decode().strip()
            if 'N1914' not in self.idn:
                raise RuntimeError(f'expected power meter model N1914A, but got {self.idn}')
            
            self.s.send(b'*cls\n')  # clear errors
            self.s.send(b'*rst\n')  # reset
            for i in [1,2]:
                # configure channel i:
                # default range, 3 significant digits,
                # continuous mode off, trigger source immediate,
                # auto trigger delay, auto averaging.
                self.s.send(b'conf%d DEF,3,(@%d)\n'%(i,i))
                self.s.send(b'unit%d:power dbm\n'%(i))  # dBm readings
                self.s.send(b'sens%d:mrate normal\n')  # 20 reads/sec
            
            self.s.send(b'syst:err?\n')
            err = self.s.recv(256)
            if not err.startswith(b'+0,"No error"'):
                raise RuntimeError(f'power meter N1914A setup failure: {err}')
        except:
            self.close()
            raise
        self.update()
        # PMeter2.initialise
    
    
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
        # PMeter2.update
    
    
    def get_channel_list(self, ch=None):
        '''
        Helper function, return int list of channels to use.
        If ch==None, returns [1,2].
        Otherwise ch can be a value in 1,2 or A,B.
        '''
        if ch is None:
            return [1,2]
        else:
            if hasattr(ch, 'lower'):
                ch = ch.lower()
                ch = {'a':1, 'b':2}[ch]
            ch = int(ch)
            if not 1 <= ch <= 2:
                raise ValueError('ch %d not in range [1,2]'%(ch))
            return [ch]
        # PMeter2.get_ch_list
    
    
    def read_init(self, ch=None):
        '''
        Send abort+init commands for given ch to start a reading.
        This command should be followed by read_fetch to get the value(s).
        The optional ch argument can be in 1,2 or A,B.
        If ch not given, init reading for both channels.
        '''
        self.log.debug('read_init(%s)', ch)
        ch = self.get_channel_list(ch)
        for i in ch:
            self.s.send(b'abort%d\n'%(%i))
            self.s.send(b'init%d\n'%(%i))
        # PMeter2.read_init
    
    
    def read_fetch(self, ch=None):
        '''
        Send fetch comamnd for given ch to retrieve a reading value.
        This command should follow a call to read_init.
        The optional ch argument can be in 1,2 or A,B.
        If ch not given, get reading for both channels and return as list.
        '''
        self.log.debug('read_init(%s)', ch)
        ch = self.get_channel_list(ch)
        p = [0.0, 0.0]
        for i in ch:
            self.s.send(b'fetch%d?\n'%(i))
            p[i-1] = float(self.s.recv(256))
        if len(ch) > 1:
            return p
        else:
            return p[ch[0]-1]
        # PMeter2.read_fetch
    
    
    def read_power(self, ch=None):
        '''
        Read and return power for given ch (read_init + read_fetch).
        The optional ch argument can be in 1,2 or A,B.
        If ch not given, read both channels and return as list.
        '''
        self.log.debug('read_power(%s)', ch)
        self.read_init(ch)
        return self.read_fetch(ch)
        # PMeter2.read_power
    
    
    def set_ghz(self, ghz, ch=None):
        '''
        Set frequency for power sensor calibration tables.
        The optional ch argument can be in 1,2 or A,B.
        If ch not given, set freq for both channels.
        '''
        self.log.debug('set_ghz(%s, %s)', ghz, ch)
        
        ghz = float(ghz)
        ch = self.get_channel_list(ch)
        
        for i in ch:
            self.s.send(b'sens%d:freq %gGHz\n'%(i, ghz))
            self.state['ghz'][i-1] = ghz
        
        # PMeter2.set_ghz

