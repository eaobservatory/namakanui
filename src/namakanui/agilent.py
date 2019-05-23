'''
Ryan Berthold 20181010

TCP/IP socket interface to the Agilent N5173B signal generator,
using SCPI command language.

20181030 NOTE: The design board shows an Agilent 8257D.
Is its command set substantially the same?  Or will I need to create
a separate class?  Also if ASIAA uses a different signal generator
for the GLT, need to develop a new control class (with same interface).
'''

from namakanui.includeparser import IncludeParser
from namakanui import sim
import socket
import logging


class Agilent(object):
    
    def __init__(self, inifilename, sleep, publish, simulate=None):
        self.config = IncludeParser(inifilename)
        agconfig = self.config['agilent']
        self.sleep = sleep
        self.publish = publish
        if simulate is not None:
            self.simulate = simulate
        else:
            self.simulate = sim.str_to_bits(agconfig['simulate'])
        self.name = agconfig['pubname']
        self.state = {'number':0}
        self.logname = agconfig['logname']
        self.log = logging.getLogger(self.logname)
        self.ip = agconfig['ip']
        self.port = int(agconfig['port'])
        self.dbm = float(agconfig['dbm'])
        self.harmonic = int(agconfig['harmonic'])
        self.floog = float(agconfig['floog'])
        self.initialise()
    
    def __del__(self):
        self.close()
    
    def close(self):
        if hasattr(self, 's'):
            self.log.debug('closing socket')
            self.s.close()
        del self.s
    
    def initialise(self):
        # fix simulate set
        self.simulate &= sim.SIM_AGILENT
        
        self.state['simulate'] = self.simulate
        self.state['sim_text'] = sim.bits_to_str(self.simulate)
        
        self.close()
        if not self.simulate:
            self.log.debug('connecting socket to %s:%d', self.ip, self.port)
            self.s = socket.socket()
            self.s.settimeout(1)
            self.s.connect((self.ip, self.port))
            self.state['hz'] = self.get_hz()
            self.state['dbm'] = self.get_dbm()
            self.state['output'] = self.get_output()
        else:
            self.state['hz'] = 0.0
            self.state['dbm'] = self.dbm
            self.state['output'] = 0
        self.update(publish_only=True)
    
    def update(self, publish_only=False):
        '''
        Update agilent parameters.  If publish_only, do not query params first.
        Call at ~0.1Hz.
        '''
        if not publish_only:
            self.state['hz'] = self.get_hz()
            self.state['dbm'] = self.get_dbm()
            self.state['output'] = self.get_output()
        
        self.state['number'] += 1
        self.publish(self.name, self.state)
    
    def cmd(self, cmd):
        '''Send SCPI cmd.  If cmd ends in ?, return reply.
           The reply will be same type as cmd (bytes or str).'''
        convert = not isinstance(cmd, bytes)
        if convert:
            cmd = cmd.encode()  # convert to bytes
        cmd = cmd.strip()
        self.log.debug('> %s', cmd)
        reply = cmd.endswith(b'?')
        cmd += b'\n'
        # packets are small, never expect this to fail -- be lazy.
        b = self.s.send(cmd)
        assert b == len(cmd)
        if reply:
            reply = self.s.recv(256)  # will replies ever be longer?
            reply = reply.strip()  # remove trailing newline
            self.log.debug('< %s', reply)
            if convert:
                reply = reply.decode()  # convert to string
            return reply

    def get_errors(self):
        '''Clear the error message queue and return as list of strings.'''
        e = []
        while True:
            e.append(self.cmd(':syst:err?'))
            if not e[-1]:
                raise RuntimeError('Agilent bad reply to error query, queue so far %s' % (e))
            if e[-1].startswith('+0,'):
                break
        return e
    
    def set_cmd(self, param, value, fmt):
        '''Set param to value, first stringifying using fmt (e.g. "%.3f").
           The param is then queried; if reply does not match cmd, raise RuntimeError.'''
        if self.simulate:
            return
        t = type(value)
        v = fmt % (value)
        self.cmd(param + ' ' + v)
        rv = self.cmd(param + '?')
        if t(v) != t(rv):
            raise RuntimeError('Agilent failed to set %s to %s, reply %s, errors %s' % (param, v, rv, self.get_errors()))
    
    # NOTE: These 'set' functions do not call update(), since we expect
    #       the user to make multiple set_ calls followed by a single update().
            
    def set_hz(self, hz):
        '''Set output frequency in Hz.'''
        hz = float(hz)
        self.set_cmd(':freq', hz, '%.3f')
        self.state['hz'] = hz
        
    def set_dbm(self, dbm):
        '''Set output amplitude in dBm.'''
        dbm = float(dbm)
        self.set_cmd(':power', dbm, '%.7f')
        self.state['dbm'] = dbm
    
    def set_output(self, on):
        '''Set RF output on (1) or off (0).'''
        on = int(on)
        self.set_cmd(':output', on, '%d')
        self.state['output'] = on
    
    def get_hz(self):
        '''Get output frequency in Hz.'''
        if self.simulate:
            return self.state['hz']
        return float(self.cmd(':freq?'))
    
    def get_dbm(self):
        '''Get output amplitude in dBm.'''
        if self.simulate:
            return self.state['dbm']
        return float(self.cmd(':power?'))
    
    def get_output(self):
        '''Get output on (1) or off (0).'''
        if self.simulate:
            return self.state['output']
        return int(self.cmd(':output?'))


        
