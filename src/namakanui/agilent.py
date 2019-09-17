'''
Ryan Berthold 20181010

TCP/IP socket interface to the Agilent N5173B / E8257D signal generator,
using SCPI command language.

'''

from namakanui.ini import *
from namakanui import sim
import socket
import logging


class Agilent(object):
    '''
    Class to control an Agilent N5173B signal generator.
    '''
    
    def __init__(self, inifilename, sleep, publish, simulate=None):
        '''Arguments:
            inifilename: Path to config file.
            sleep(seconds): Function to sleep for given seconds, e.g. time.sleep, drama.wait.
            publish(name, dict): Function to output dict with given name, e.g. drama.set_param.
            simulate: Bitmask. If not None (default), overrides setting in inifilename.
        '''
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
        self.safe_dbm = float(agconfig['safe_dbm'])
        self.harmonic = int(agconfig['harmonic'])
        self.floog = float(agconfig['floog'])
        
        self.dbm_tables = {}  # indexed by band
        for b in [3,6,7]:
            self.dbm_tables[b] = read_table(self.config['dbm_b%d'%(b)], 'dbm', float, ['lo', 'dbm'])
        
        self.log.debug('__init__ %s, sim=%d, %s:%d, dbm=%g, harmonic=%d, floog=%g',
                       inifilename, self.simulate, self.ip, self.port,
                       self.safe_dbm, self.harmonic, self.floog)
        self.initialise()
    
    def __del__(self):
        self.log.debug('__del__')
        self.close()
    
    def close(self):
        '''Close the socket connection to the Agilent.'''
        if hasattr(self, 's'):
            self.log.debug('closing socket')
            self.s.close()
            del self.s
    
    def initialise(self):
        '''Open the socket connection to the Agilent and get/publish state.'''
        self.log.debug('initialise')
        
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
            # these functions update state dict
            self.get_hz()
            self.get_dbm()
            self.get_output()
        else:
            self.state['hz'] = 0.0
            self.state['dbm'] = self.safe_dbm
            self.state['output'] = 0
        self.update(publish_only=True)
    
    def update(self, publish_only=False):
        '''
        Update Agilent parameters.  If publish_only, do not query params first.
        Call at ~0.1Hz.
        '''
        self.log.debug('update')
        if not publish_only:
            # these functions update state dict
            self.get_hz()
            self.get_dbm()
            self.get_output()
        self.state['number'] += 1
        self.publish(self.name, self.state)
    
    def cmd(self, cmd):
        '''Send SCPI cmd.  If cmd ends in ?, return reply.
           The reply will be same type as cmd (bytes or str).'''
        convert = not isinstance(cmd, bytes)
        if convert:
            cmd = cmd.encode()  # convert to bytes
        cmd = cmd.strip()
        self.log.debug('cmd: %s', cmd)
        reply = cmd.endswith(b'?')
        cmd += b'\n'
        # packets are small, never expect this to fail -- be lazy.
        b = self.s.send(cmd)
        assert b == len(cmd)
        if reply:
            reply = self.s.recv(256)  # will replies ever be longer?
            reply = reply.strip()  # remove trailing newline
            self.log.debug('reply: %s', reply)
            if convert:
                reply = reply.decode()  # convert to string
            return reply

    def get_errors(self):
        '''Clear the error message queue and return as list of strings.'''
        self.log.debug('get_errors')
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
        self.log.debug('set_cmd(%s, %s, %s)', param, value, fmt)
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
        '''Set output frequency in Hz.  Updates state, but does not publish.'''
        hz = float(hz)
        self.set_cmd(':freq', hz, '%.3f')
        self.state['hz'] = hz
        
    def set_dbm(self, dbm):
        '''Set output amplitude in dBm.  Updates state, but does not publish.'''
        dbm = float(dbm)
        self.set_cmd(':power', dbm, '%.2f')
        self.state['dbm'] = dbm
    
    def set_output(self, on):
        '''Set RF output on (1) or off (0).  Updates state, but does not publish.'''
        on = int(on)
        if on:
            on = 1
        self.set_cmd(':output', on, '%d')
        self.state['output'] = on
    
    def get_hz(self):
        '''Get output frequency in Hz.  Updates state, but does not publish.'''
        if self.simulate:
            return self.state['hz']
        hz = float(self.cmd(':freq?'))
        self.state['hz'] = hz
        return hz
    
    def get_dbm(self):
        '''Get output amplitude in dBm.  Updates state, but does not publish.'''
        if self.simulate:
            return self.state['dbm']
        dbm = float(self.cmd(':power?'))
        self.state['dbm'] = dbm
        return dbm
    
    def get_output(self):
        '''Get output on (1) or off (0).  Updates state, but does not publish.'''
        if self.simulate:
            return self.state['output']
        on = int(self.cmd(':output?'))
        self.state['output'] = on
        return on

    def interp_dbm(self, band, lo_ghz):
        '''Get interpolated dBm for this band and frequency.'''
        return interp_table(self.dbm_tables[band], lo_ghz)[-1]


