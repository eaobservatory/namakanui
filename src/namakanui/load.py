'''
namakanui/load.py   RMB 20181219

Monitoring and control class for Namakanui load selector,
modeled on the glt_load.py script from the GLT receiver.

The load is selected by a wheel mounted above the dewar, through a
GIP-101 5-button single-axis controller from Sigma Koki (Optosigma).
The manual can be found here (on malama):
/export/smb/jcmteng/Instruments/GLTCryostat/externalManufactureDocs/GIP-101_UserManual.pdf

Communication with the controller is via RS232 serial,
so we connect through a CMS switch.  Default config is 9600b, 8N1.

This class uses absolute positions given in the config file,
rather than any of the programmed button positions -- since there are
only five buttons, we would likely run out.

NOTE: The stage is not homed automatically.  During GLT testing there were
      wires running to the load wheel that could get twisted up during homing,
      requiring supervision.  If Namakanui is configured differently, this
      class should be altered to allow automatic homing.

NOTE: The motor can be turned off and the load positioned by hand:
      send cmd 'C:10' and spin the small wheel on the gear drive.
      However, the controller loses its 'homed' status
      and will no longer update the position count.

TODO: Command cheat sheet.


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

from namakanui.ini import IncludeParser
from namakanui import sim
import socket
import select
import time
import logging

class Load(object):
    '''Interface to the load wheel controller.'''
    
    def __init__(self, inifile, sleep, publish, simulate=None):
        '''Arguments:
            inifile: Path to config file or dict-like, e.g ConfigParser.
            sleep(seconds): Function to sleep for given seconds, e.g. time.sleep, drama.wait.
            publish(name, dict): Function to output dict with given name, e.g. drama.set_param.
            simulate: Bitmask. If not None (default), overrides setting in inifilename.
        '''
        self.config = inifile
        if not hasattr(inifile, 'items'):
            self.config = IncludeParser(inifile)
        self.sleep = sleep
        self.publish = publish
        if simulate is not None:
            self.simulate = simulate
        else:
            self.simulate = sim.str_to_bits(self.config['load']['simulate'])
        self.name = self.config['load']['pubname']
        self.state = {'number':0}
        self.logname = self.config['load']['logname']
        self.log = logging.getLogger(self.logname)
        
        # I would query the controller for this if I could
        self.speed = float(self.config['load']['speed'])
        
        # can query controller for this; do so in initialise
        self.wrap = int(self.config['load']['wrap'])
        
        # NOTE: reverse lookup does not allow synonymous positions
        self.positions = {n:int(p) for n,p in self.config['positions'].items()}
        self.positions_r = {p:n for n,p in self.positions.items()}
        
        self.log.debug('__init__ %s, sim=%d', inifilename, self.simulate)
        self.initialise()
        # Load.__init__


    def __del__(self):
        self.log.debug('__del__')
        self.close()

    
    def close(self):
        self.log.debug('close')
        if hasattr(self, 's'):
            self.s.close()
            del self.s
        
    
    def initialise(self):
        '''(Re)connect to the CMS port and call update().'''
        self.log.debug('initialise')
        
        # fix simulate set
        self.simulate &= sim.SIM_LOAD
        
        if not self.simulate:
            self.close()
            timeout = float(self.config['load']['timeout'])
            cms = self.config['load']['cms']
            port = int(self.config['load']['port'])
            # the cms doesn't like to reconnect, so try a few times
            self.log.debug('connecting to %s:%d', cms, port)
            attempt = 0
            max_attempts = 3
            while attempt < max_attempts:
                try:
                    self.s = socket.socket()
                    self.s.settimeout(timeout)
                    self.s.connect((cms, port))
                    break
                except socket.error as e:
                    attempt += 1
                    if attempt >= max_attempts:
                        self.log.error('giving up, error connecting to %s:%d: %s', cms, port, e)
                        raise
                    self.log.error('retrying after error connecting to %s:%d: %s', cms, port, e)
                    self.sleep(0.5)
            if attempt:
                self.log.info('connected to %s:%d after %d attempts', cms, port, attempt+1)
            # double-check the number of counts per full rotation
            wrap = int(self.cmd('?:R\r\n')[1:])  # skip '+'
            if wrap != self.wrap:
                self.log.warning('wrap was set to %d, but controller reports %d', self.wrap, wrap)
                self.wrap = wrap  # trust the controller
            # make sure the motor is on.
            r = self.cmd('C:11\r\n')
            if r != 'OK\r\n':
                raise RuntimeError('bad reply to C: %s' % (r))
        elif hasattr(self, 's'):
            del self.s
        
        self.state['simulate'] = self.simulate
        self.state['sim_text'] = sim.bits_to_str(self.simulate)
        
        # init these state fields so simulate can pretend properly
        self.state['pos_counts'] = 0
        self.state['pos_name'] = self.positions_r.get(0, 'undef')
        
        self.update()
        # Load.initialise
        
    
    def update(self):
        '''Call at ~0.1 Hz.'''
        self.log.debug('update')
        
        if not self.simulate:
            r = self.cmd('Q:\r\n')
            pos,a1,a2,a3 = [s.strip() for s in r[1:].split(',')]
            pos = int(pos)
            if r[0] == '-':
                pos = -pos
            self.state['pos_counts'] = pos
            self.state['pos_name'] = self.positions_r.get(pos, 'undef')
            self.state['busy'] = int(a3 == 'B')
            if a1 != 'K' or a2 != 'K':
                raise RuntimeError('bad reply to Q: %s' % (r))
            # hopefully we can use ? even when busy -- TODO TEST
            r = self.cmd('?:ORG\r\n')
            self.state['homed'] = int(r)
        else:
            # pretended pos_counts and pos_name held from last move()
            self.state['busy'] = 0
            self.state['homed'] = 1
        
        self.state['number'] += 1
        self.publish(self.name, self.state)
        # Load.update
    
    
    def cmd(self, c):
        '''Send command string c to controller and return reply.
           TODO: pass in bytes everywhere, avoid encode/decode.
        '''
        # clear out any leftover junk on the socket before sending
        while select.select([self.s],[],[],0.0)[0]:
            self.s.recv(64)
        c = c.encode()  # needs to be bytes
        self.log.debug('cmd: %s', c)
        self.s.sendall(c)
        r = b''
        while not b'\r\n' in r:
            r += self.s.recv(64)
        # if the controller is power-cycled, we get a 0xff byte.
        # remove any such bytes from the reply string.
        r = r.replace(b'\xff', b'')
        self.log.debug('reply: %s', r)
        return r.decode()
        # Load.cmd
    
    
    def stop(self):
        '''Decelerate and stop the motor.  Wait for ready status.'''
        self.log.debug('stop')
        
        if self.simulate:
            self.update()  # sets busy=0
            return
            
        r = self.cmd('L:1\r\n')
        if r != 'OK\r\n':
            raise RuntimeError('bad reply to L: %s' % (r))
        
        # a foolish consistency
        try:
            # wait 3s for ready status
            self.update()
            timeout = time.time() + 3.0
            while self.state['busy'] and time.time() < timeout:
                self.sleep(0.5)
                self.update()
            if self.state['busy']:
                raise RuntimeError('timeout waiting for axis ready')
        finally:
            self.cmd('L:1\r\n')  # why not
        
        # Load.stop
    
    
    def home(self):
        '''Home the stage and wait for completion.'''
        self.log.info('home')
        
        if self.simulate:
            self.update()  # sets homed=1
            return
        
        # stop whatever we're doing and wait for ready status
        self.stop()
        
        # be careful to stop the motor on any error
        try:
            # send the homing command
            r = self.cmd('H:1\r\n')
            if r != 'OK\r\n':
                raise RuntimeError('bad reply to H: %s' % (r))
           
            # wait 30s for completion
            timeout = time.time() + 30.0
            self.state['busy'] = 1
            while self.state['busy'] and time.time() < timeout:
                self.sleep(0.5)
                self.update()
            if self.state['busy']:
                raise RuntimeError('timeout waiting for home completion')
            if not self.state['homed']:
                raise RuntimeError('home failed')
        finally:
            self.cmd('L:1\r\n')  # make sure motor stops moving
        
        # Load.home
    
    
    def move(self, pos):
        '''Move to pos (name or counts) and wait for completion.'''
        self.log.info('move(%s)', pos)
        
        if pos in self.positions:
            pos = self.positions[pos]
        pos = int(pos)
        pos = pos % self.wrap  # prevent windup
        
        if self.simulate:
            self.state['pos_counts'] = pos
            self.state['pos_name'] = self.positions_r.get(pos, 'undef')
            self.update()
            return
        
        if not self.state['homed']:
            raise RuntimeError('stage not homed')
        
        # stop whatever we're doing and wait for ready status
        self.stop()
        
        # maybe we're already in position?
        if pos == self.state['pos_counts']:
            return
        
        # send absolute position command
        r = self.cmd('A:1+P%d\r\n' % (pos))
        if r != 'OK\r\n':
            raise RuntimeError('bad reply to A: %s' % (r))
        
        # from now on we must be careful to stop on error
        try:
            # start the move
            r = self.cmd('G:\r\n')
            if r != 'OK\r\n':
                raise RuntimeError('bad reply to G: %s' % (r))
            
            # wait for move to finish
            dist = pos - self.state['pos_counts']
            timeout = abs(dist) / self.speed + 3.0
            self.log.debug('moving from %d to %d: distance %d counts, timeout %.2fs',
                            self.state['pos_counts'], pos, dist, timeout)
            timeout = time.time() + timeout  # wall time
            self.state['busy'] = 1
            while self.state['busy'] and time.time() < timeout:
                self.sleep(0.5)
                self.update()
            if self.state['busy']:
                raise RuntimeError('timeout waiting for move completion')
            
            # make sure we ended up in the right place
            end_pos = self.state['pos_counts']
            if end_pos != pos:
                raise RuntimeError('move ended at %d instead of %d' % (end_pos, pos))
        finally:
            self.cmd('L:1\r\n')  # make sure motor stops moving
        
        # Load.move



