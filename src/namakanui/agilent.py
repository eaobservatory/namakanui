'''
Ryan Berthold 20181010

TCP/IP socket interface to the Agilent N5173B signal generator,
using SCPI command language.

20181030 NOTE: The design board shows an Agilent 8257D.
Is its command set substantially the same?  Or will I need to create
a separate class?  Also if ASIAA uses a different signal generator
for the GLT, need to develop a new control class (with same interface).
'''

import socket

class Agilent(object):
    
    def __init__(self, ip, port=5025):
        self.s = socket.socket()
        self.s.settimeout(1)
        self.s.connect((ip, port))
    
    def __del__(self):
        self.s.close()
    
    def cmd(self, cmd):
        '''Send SCPI cmd.  If cmd ends in ?, return reply.
           The reply will be same type as cmd (bytes or str).'''
        convert = not isinstance(cmd, bytes)
        if convert:
            cmd = cmd.encode()  # convert to bytes
        cmd = cmd.strip()
        reply = cmd.endswith(b'?')
        cmd += b'\n'
        # packets are small, never expect this to fail -- be lazy.
        b = self.s.send(cmd)
        assert b == len(cmd)
        if reply:
            reply = self.s.recv(256)  # will replies ever be longer?
            reply = reply.strip()  # remove trailing newline
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
        t = type(value)
        v = fmt % (value)
        self.cmd(param + ' ' + v)
        rv = self.cmd(param + '?')
        if t(v) != t(rv):
            raise RuntimeError('Agilent failed to set %s to %s, reply %s, errors %s' % (param, v, rv, self.get_errors()))
            
    def set_hz(self, hz):
        '''Set output frequency in Hz.'''
        hz = float(hz)
        self.set_cmd(':freq', hz, '%.3f')
        
    def set_dbm(self, dbm):
        '''Set output amplitude in dBm.'''
        dbm = float(dbm)
        self.set_cmd(':power', dbm, '%.7f')
    
    def set_output(self, on):
        '''Set RF output on (1) or off (0).'''
        on = int(on)
        self.set_cmd(':output', on, '%d')
    
    def get_hz(self):
        '''Get output frequency in Hz.'''
        return float(self.cmd(':freq?'))
    
    def get_dbm(self):
        '''Get output amplitude in dBm.'''
        return float(self.cmd(':power?'))
    
    def get_output(self):
        '''Get output on (1) or off (0).'''
        return int(self.cmd(':output?'))
    
    
    
        
