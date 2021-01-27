'''
namakanui/reference.py    RMB 20181010

TCP/IP socket interface to the reference signal generator,
which is either an Agilent N5173B or Keysight E8257D,
using SCPI command language.

Renamed to "Reference" (from "Agilent") 20210127.


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


class Reference(object):
    '''
    Class to control an Agilent N5173B or Keysight E8257D signal generator.
    '''
    
    def __init__(self, inifile, sleep, publish, simulate=0):
        '''Arguments:
            inifile: Path to config file or IncludeParser instance.
            sleep(seconds): Function to sleep for given seconds, e.g. time.sleep, drama.wait.
            publish(name, dict): Function to output dict with given name, e.g. drama.set_param.
            simulate: Mask, bitwise ORed with config settings.
        '''
        self.config = inifile
        if not hasattr(inifile, 'items'):
            self.config = IncludeParser(inifile)
        rconfig = self.config['reference']
        self.sleep = sleep
        self.publish = publish
        self.simulate = sim.str_to_bits(rconfig['simulate']) | simulate
        self.name = rconfig['pubname']
        self.state = {'number':0}
        self.logname = rconfig['logname']
        self.log = logging.getLogger(self.logname)
        self.ip = rconfig['ip']
        self.port = int(rconfig['port'])
        self.safe_dbm = float(rconfig['safe_dbm'])
        self.max_dbm = float(rconfig['max_dbm'])
        self.harmonic = int(rconfig['harmonic'])
        self.floog = float(rconfig['floog'])
        
        datapath = os.path.dirname(self.config.inifilename) + '/'
        self.dbm_tables = {}  # indexed by band, 0 = photonics table
        self.dbm_tables[0] = read_ascii(datapath + rconfig['photonics_dbm'])
        dbm_config = self.config[rconfig['dbm_tables']]
        for b in [3,6,7]:
            self.dbm_tables[b] = read_ascii(datapath + dbm_config['b%d_dbm'%(b)])
        
        self.log.debug('__init__ %s, sim=%d, %s:%d, dbm=%g, harmonic=%d, floog=%g',
                       self.config.inifilename, self.simulate, self.ip, self.port,
                       self.safe_dbm, self.harmonic, self.floog)
        self.initialise()
    
    def __del__(self):
        self.log.debug('__del__')
        self.close()
    
    def close(self):
        '''Close the socket connection to the signal generator.'''
        if hasattr(self, 's'):
            self.log.debug('closing socket')
            self.s.close()
            del self.s
    
    def initialise(self):
        '''Open the socket connection to the hardware and get/publish state.'''
        self.log.debug('initialise')
        
        # fix simulate set
        self.simulate &= sim.SIM_REFERENCE
        
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
        Update parameters.  If publish_only, do not query params first.
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
    
    def cmd(self, cmd, reconnect=True):
        '''Send SCPI cmd.  If cmd ends in ?, return reply.
           The reply will be same type as cmd (bytes or str).'''
        orig_cmd = cmd
        convert = not isinstance(cmd, bytes)
        if convert:
            cmd = cmd.encode()  # convert to bytes
        cmd = cmd.strip()
        self.log.debug('cmd: %s', cmd)
        reply = cmd.endswith(b'?')
        cmd += b'\n'
        # wrap this whole thing in a try block, since
        # we sometimes see a recv() timeout even after select.
        # we also need to watch for b'' in case connection closed.
        try:
            # clear out recv buffer before sending cmd
            buf = b'x'
            while buf and select.select([self.s], [], [], 0)[0]:
                buf = self.s.recv(256)
            assert buf, 'lost connection'
            # packets are small, never expect this to fail
            b = self.s.send(cmd)
            assert b == len(cmd), 'only sent %d/%d bytes'%(b,len(cmd))
            if reply:
                reply = self.s.recv(256)
                assert reply, 'no reply, lost connection'
                reply = reply.strip()  # remove trailing newline
                self.log.debug('reply: %s', reply)
                if convert:
                    reply = reply.decode()  # convert to string
                return reply
        except (OSError, AssertionError) as e:
            if reconnect:
                self.log.warning('socket %s, attempting reconnect', e)
                self.initialise()
                self.log.info('reconnected, retrying cmd %s', cmd[:-1])
                return self.cmd(orig_cmd, reconnect=False)
            else:
                self.log.error('socket %s, cmd %s', e, cmd[:-1])
                raise
        # cmd
    
    def get_errors(self):
        '''Clear the error message queue and return as list of strings.'''
        self.log.debug('get_errors')
        e = []
        while True:
            e.append(self.cmd(':syst:err?'))
            if not e[-1]:
                raise RuntimeError('Reference bad reply to error query, queue so far %s' % (e))
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
            raise RuntimeError('Reference failed to set %s to %s, reply %s, errors %s' % (param, v, rv, self.get_errors()))
    
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
        dbm = min(dbm, self.max_dbm)
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

    def interp_dbm(self, band, ghz):
        '''
        Get interpolated dBm for this band and frequency.
        If band==0, use photonics table; ghz should be SG frequency.
        Otherwise,  use the band  table; ghz should be LO frequency.
        '''
        return interp_table(self.dbm_tables[band], ghz).dbm

    def set_hz_dbm(self, hz, dbm):
        '''
        Safely set frequency in Hz and output power in dBm.
        If increasing power output, sets the frequency first.
        If decreasing power output, sets the output power first.
        Updates state, but does not publish.
        '''
        if dbm > self.state['dbm']:
            self.set_hz(hz)
            self.set_dbm(dbm)
        else:
            self.set_dbm(dbm)
            self.set_hz(hz)


