'''
namakanui/ifswitch.py   RMB 20190807

Controller for Bill Stahm's IF Switch module,
using the ADAM classes created by John Kuroda.

The low-frequency lines (<12 GHz) are switched by Mini Circuits, MSP4T.
The high-frequency lines (>18 GHz) are switched by a Keysight, 87104D.

TODO: This could be a bit more generic, selecting Rx1, Rx2, Rx3 instead
      of band 3, 6, 7.  But for now we'll keep it Namakanui-specific.


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
import adam.adam6260
import adam.adam6024


class IFSwitch(object):
    '''
    Class to control Bill Stahm's IF Switch module,
    using the ADAM classes created by John Kuroda.
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
        cfg = self.config['ifswitch']
        self.sleep = sleep
        self.publish = publish
        self.simulate = sim.str_to_bits(cfg['simulate']) | simulate
        self.name = cfg['name']
        self.state = {'number':0}
        self.state['DO'] = [0]*6
        self.state['AI'] = [0.0]*6
        self.log = logging.getLogger(self.name)
        
        # init only saves ip/port, so this is fine even if simulating
        self.adam_6260 = adam.adam6260.Adam6260(cfg['ip_6260'], int(cfg['port_6260']))
        self.adam_6024 = adam.adam6024.Adam6024(cfg['ip_6024'], int(cfg['port_6024']))
        
        self.log.debug('__init__ %s, sim=%d, 6260=%s:%d, 6024=%s:%d',
                       self.config.inifilename, self.simulate,
                       self.adam_6260.ip, self.adam_6260.port,
                       self.adam_6024.ip, self.adam_6024.port)
        
        self.initialise()
        
        self.log.setLevel(logging.INFO)  # once created, be quiet even if root is DEBUG
        # IFSwitch.__init__


    def __del__(self):
        self.log.debug('__del__')
        self.close()
        # IFSwitch.__del__
    
    
    def close(self):
        '''close the connections to the ADAM units'''
        self.log.debug('close')
        self.adam_6260.close()
        self.adam_6024.close()
        # IFSwitch.close
    
    
    def initialise(self):
        '''Open the connections to the ADAMs and get/publish state.'''
        self.log.debug('initialise')
        
        # fix simulate set
        self.simulate &= sim.SIM_IFSW_6260 | sim.SIM_IFSW_6024
        
        self.state['simulate'] = self.simulate
        self.state['sim_text'] = sim.bits_to_str(self.simulate)
        
        self.close()
        if not self.simulate & sim.SIM_IFSW_6260:
            self.log.debug('connecting 6260, %s:%d', self.adam_6260.ip, self.adam_6260.port)
            self.adam_6260.connect()
            modname = self.adam_6260.get_module_name()
            self.log.debug('6260 module name: %s', modname)
        if not self.simulate & sim.SIM_IFSW_6024:
            self.log.debug('connecting 6024, %s:%d', self.adam_6024.ip, self.adam_6024.port)
            self.adam_6024.connect()
            modname = self.adam_6024.get_module_name()
            self.log.debug('6024 module name: %s', modname)
        
        self.update()
        # IFSwitch.initialise

    
    def update(self, do_publish=True):
        '''Update and publish state.  Call every 10s.
           NOTE: The 6260 will time out and disconnect if we don't
                 talk to it every 30s or so.
        '''
        self.log.debug('update(%s)', do_publish)
        
        if not self.simulate & sim.SIM_IFSW_6260:
            DO = self.adam_6260.get_DO_status()
            self.state['DO'] = DO
        
        if not self.simulate & sim.SIM_IFSW_6024:
            AI = self.adam_6024.get_AI_status()
            self.state['AI'] = AI
        else:
            # pretend the 31.5 MHz oscillator is locked
            self.state['AI'][0] = 5.0
        
        if do_publish:
            self.state['number'] += 1
            self.publish(self.name, self.state)
        # IFSwitch.update
    
    
    def raise_315(self):
        '''Raise RuntimeError if 31.5 MHz oscillator is unlocked.
           Does not call update() first.
        '''
        if self.state['AI'][0] < 3.5:
            raise RuntimeError('31.5 MHz oscillator unlocked, voltage %g' % (self.state['AI'][0]))
        # IFSwitch.raise_315
    
    
    def set_band(self, band):
        '''Switch to the desired receiver band, [3,6,7].
        '''
        self.log.debug('set_band(%s)', band)
        
        band = int(band)
        if band not in [3,6,7]:
            raise ValueError('band %d not one of [3,6,7]' % (band))
        
        # get desired output state
        i = {3:0, 6:1, 7:2}[band]
        outputs = [0]*6
        outputs[i] = 1
        outputs[i+3] = 1
        
        if self.simulate & sim.SIM_IFSW_6260:
            self.state['DO'] = outputs
            self.update()
            self.raise_315()  # might not be simulating the 6024, so check
            return
        
        # check current status, might as well publish
        self.update()
        
        # if things already look correct, do nothing
        if self.state['DO'] == outputs:
            self.log.debug('set_band: DO already %s', outputs)
            self.raise_315()  # ...but check on the 31.5 MHz lock first
            return
        
        # zero all outputs.  note that since the keysight switch is a latching
        # switch, this will not actually break the previous connection.
        # however, the next connection will be done break-before-make.
        self.log.debug('set_band: zeroing outputs')
        self.adam_6260.set_DO([0]*6)
        
        # wait a short time for the relays to open
        self.sleep(0.05)
        
        # set the new relay positions.  note that though the keysight is a
        # latching switch, it has an internal position sensor that cuts the
        # drive current once the relay is closed -- so we just leave the
        # desired bit enabled.
        self.log.debug('set_band: setting outputs to %s', outputs)
        self.adam_6260.set_DO(outputs)
        
        # wait a short time for the relays to close
        self.sleep(0.05)
        
        # publish new state
        self.update()
        
        # might as well double-check
        if self.state['DO'] != outputs:
            raise RuntimeError('failed to set DO: tried %s, but status is %s' % (outputs, self.state['DO']))
        
        # might as well check this again too
        self.raise_315()
        
        # IFSwitch.set_band


    def get_band(self):
        '''Return current band (3,6,7) or 0 if unknown.'''
        DO = self.state['DO']
        if DO == [1,0,0,1,0,0]:
            return 3
        elif DO == [0,1,0,0,1,0]:
            return 6
        elif DO == [0,0,1,0,0,1]:
            return 7
        return 0
        # IFSwitch.get_band





