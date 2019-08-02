'''
RMB 20181219
Monitoring and control class for Namakanui load selector,
modeled on the glt_load.py script from the GLT receiver.

The load is selected by a wheel mounted above the dewar, through a
GIP-101 5-button single-axis controller from Sigma Koki (Optosigma).
The manual can be found here (on malama):
/export/smb/jcmteng/Instruments/GLTCryostat/externalManufactureDocs/GIP-101_UserManual.pdf

Communication with the controller is via RS232 serial,
so we connect through a CMS switch.

This class uses absolute positions given in the config file,
rather than any of the programmed button positions -- since there are
only five buttons, we would likely run out.

NOTE: The stage is not homed automatically.  During GLT testing there were
      wires running to the load wheel that could get twisted up during homing,
      requiring supervision.  If Namakanui is configured differently, this
      class should be altered to allow automatic homing.

TODO: Make sure wheel is stopped if actions are kicked or errors occur.

TODO: Can the motor be turned off and the wheel positioned by hand?
'''

from namakanui.ini import IncludeParser
from namakanui import sim
import socket
import time
import logging

class Load(object):
    '''Interface to the load wheel controller.'''
    
    def __init__(self, inifilename, sleep, publish, simulate=None):
        '''Arguments:
            inifilename: Path to config file.
            sleep(seconds): Function to sleep for given seconds, e.g. time.sleep, drama.wait.
            publish(name, dict): Function to output dict with given name, e.g. drama.set_param.
            simulate: Bitmask. If not None (default), overrides setting in inifilename.
        '''
        self.config = IncludeParser(inifilename)
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
        
        # NOTE: reverse lookup does not allow synonymous positions
        self.positions = {n:int(p) for n,p in self.config['positions'].items()}
        self.positions_r = {p:n for n,p in self.positions.items()}
        
        self.log.debug('__init__ %s, sim=%d', inifilename, self.simulate)
        self.initialise()
        # Load.__init__
    
    
    def initialise(self):
        '''(Re)connect to the CMS port and call update().'''
        self.log.debug('initialise')
        
        # fix simulate set
        self.simulate &= sim.SIM_LOAD
        
        if not self.simulate:
            timeout = float(self.config['load']['timeout'])
            cms = self.config['load']['cms']
            port = int(self.config['load']['port'])
            self.s = socket.socket()
            self.s.settimeout(timeout)
            self.s.connect((cms, port))
            # make sure the motor is on
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
        '''Send command string c to controller and return reply.'''
        self.log.debug('cmd: %s', c)
        self.s.sendall(c)
        r = ''
        while not '\r\n' in r:
            r += self.s.recv(64)
        self.log.debug('reply: %s', r)
        return r
        # Load.cmd
    
    
    def home(self):
        '''Home the stage and wait for completion.'''
        self.log.debug('home')
        
        if self.simulate:
            self.state['homed'] = 1
            self.update()
            return
        
        # stop whatever we're doing
        r = self.cmd('L:1\r\n')
        if r != 'OK\r\n':
            raise RuntimeError('bad reply to L: %s' % (r))
        
        # TODO: does H need to wait for ready status?
        r = self.cmd('H:1\r\n')
        if r != 'OK\r\n':
            raise RuntimeError('bad reply to H: %s' % (r))
       
        # wait 30s for completion
        timeout = time.time() + 30
        self.state['busy'] = 1
        while self.state['busy'] and time.time() < timeout:
            self.sleep(0.5)
            self.update()
        if self.state['busy']:
            raise RuntimeError('timeout waiting for home completion')
        if not self.state['homed']:
            raise RuntimeError('home failed')
        # Load.home
    
    
    def move(self, pos):
        '''Move to pos (name or counts) and wait for completion.'''
        self.log.debug('move(%s)', pos)
        
        if pos in self.positions:
            pos = self.positions[pos]
        pos = int(pos)
        if self.simulate:
            self.state['pos_counts'] = pos
            self.state['pos_name'] = self.positions_r.get(pos, 'undef')
            self.update()
            return
        if not self.state['homed']:
            raise RuntimeError('stage not homed')
        
        # stop whatever we're doing
        r = self.cmd('L:1\r\n')
        if r != 'OK\r\n':
            raise RuntimeError('bad reply to L: %s' % (r))
        
        # wait 5s for ready status
        timeout = time.time() + 5
        while self.state['busy'] and time.time() < timeout:
            self.sleep(0.5)
            self.update()
        if self.state['busy']:
            raise RuntimeError('timeout waiting for axis ready')
        
        # maybe we're already there?
        if pos == self.state['pos_counts']:
            return
        
        # send absolute position command and start move
        r = self.cmd('A:1+P%d\r\n' % (pos))
        if r != 'OK\r\n':
            raise RuntimeError('bad reply to A: %s' % (r))
        r = self.cmd('G:\r\n')
        if r != 'OK\r\n':
            raise RuntimeError('bad reply to G: %s' % (r))
        
        # wait 15s to finish
        timeout = time.time() + 15
        self.state['busy'] = 1
        while self.state['busy'] and time.time() < timeout:
            self.sleep(0.5)
            self.update()
        if self.state['busy']:
            raise RuntimeError('timeout waiting for move completion')
        end_pos = self.state['pos_counts']
        if end_pos != pos:
            raise RuntimeError('move ended at %d instead of %d' % (end_pos, pos))
        # Load.move



