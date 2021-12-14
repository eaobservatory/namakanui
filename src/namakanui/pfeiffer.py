'''
namakanui/pfeiffer.py  RMB 20211213

Class to monitor vacuum pressure using Pfeiffer TPG 252A + PKR 251.

NOTE: I could not find any documentation for 252A serial communication.
      This class implements the protocol for the TPG 262,
      which I hope is basically the same.


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
import time
import logging
import os


# flow control chars, strip()-safe.
etx = b'\x03'
enq = b'\x05'
ack = b'\x06'
nak = b'\x15'


class Pfeiffer(object):
    '''
    Class to monitor vacuum pressure from a Pfeiffer gauge.
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
        myconfig = self.config['vacuum']  # generic config
        self.sleep = sleep
        self.publish = publish
        self.simulate = sim.str_to_bits(myconfig['simulate']) | simulate
        self.name = myconfig['name']
        self.log = logging.getLogger(self.name)
        self.state = {'number':0}
        
        self.ip = myconfig['ip']
        self.port = int(myconfig['port'])
        self.timeout = float(myconfig['timeout'])  # seconds
        
        # create socket here so close() always works
        self.s = socket.socket()
        
        self.log.debug('__init__ %s, sim=%d, %s:%d',
                       self.config.inifilename, self.simulate, self.ip, self.port)
        
        self.initialise()
        
        self.log.setLevel(level)  # set log level last to allow DEBUG output during creation
        # Pfeiffer.__init__
    
    
    def __del__(self):
        self.log.debug('__del__')
        self.close()
    
    
    def close(self):
        '''Close the connection'''
        self.log.debug('close')
        self.s.close()
    
    
    def initialise(self):
        '''Open the connections to the Pfeiffer and get/publish state.'''
        self.log.debug('initialise')
        
        # fix simulate set
        self.simulate &= sim.SIM_VACUUM
        
        self.state['simulate'] = self.simulate
        self.state['sim_text'] = sim.bits_to_str(self.simulate)
        
        self.close()
        if not self.simulate & sim.SIM_VACUUM:
            self.log.debug('connecting Pfeiffer, %s:%d', self.ip, self.port)
            self.s = socket.socket()
            self.s.settimeout(self.timeout)
            self.s.connect((self.ip, self.port))
            # clear input buffer
            self.cmd(etx)
            # clear the error word, if set
            err = self.cmd('ERR?')
            # get transmitter (gauge) id
            tid = self.cmd('TID?')
            self.log.debug('Pfeiffer TID: %s', tid)
            
        self.update()
        # Pfeiffer.initialise
    
    
    def update(self):
        '''Update and publish state.'''
        self.log.debug('update')
        
        if self.simulate:
            self.state['unit'] = 'mbar'
            self.state['status'] = 'okay'
            self.state['err'] = '0000'
            self.state['s1'] = '1e-9'
            self.state['p1'] = float(self.state['s1'])
        else:
            unit = self.cmd('UNI?')
            self.state['unit'] = {0:'mbar/bar', 1:'torr', 2:'pa'}[unit]
            code,pr1 = self.cmd('PR1?').split(',')
            code = int(code)
            self.state['status'] = {0:'okay',
                                    1:'underrange',
                                    2:'overrange',
                                    3:'sensor error',
                                    4:'sensor off',
                                    5:'no sensor',
                                    6:'id error'}[code]
            self.state['s1'] = pr1
            self.state['p1'] = float(self.state['s1'])
        
        self.state['number'] += 1
        self.publish(self.name, self.state)
        # Pfeiffer.update
    
    
    def reply(self):
        '''Read and return bytes reply from socket.'''
        r = b''
        while b'\r\n' not in r:
            r += self.s.recv(64)
        return r.strip()
        
    
    def cmd(self, c):
        '''Clear socket, send cmd c, and recv reply if "?" in c.'''
        self.log.debug('cmd(%s)', c)
        c = c.strip()
        if hasattr(c, 'encode'):
            c = c.encode()  # convert to bytes
        query = b'?' in c
        c = c.replace(b'?', b'')
        
        # clear socket buffer and send cmd
        while select.select([self.s],[],[],0.0)[0]:
            self.s.recv(64)
        self.s.sendall(c + b'\r\n')  # \n optional in cmds
        
        # get ack/nak
        r = self.reply()
        if r == ack:
            pass
        elif r == nak:
            # request the error code
            self.s.sendall(enq)  # no terminator needed
            r = self.reply()
            self.state['err'] = r
            self.log.error('NAK from cmd %s, err %s', c, r)
            return
        else:
            raise IOError('expected ACK/NAK from cmd %s, got %s'%(c,r))
        
        if query:
            # request value
            self.s.sendall(enq)  # no terminator needed
            r = self.reply()
            return r.decode()
        
        return
        # Pfeiffer.cmd
        

