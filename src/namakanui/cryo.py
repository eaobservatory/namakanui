'''
namakanui/cryo.py   RMB 20181108

Monitoring and control for an ALMA cryostat.
Valves, pumps, pressures, temperatures, power supply.

UNTESTED, INCOMPLETE.  Not used by the Namakanui system.


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
from namakanui.femc import FEMC
from namakanui import sim
import logging

class Cryo(object):
    '''
    Monitor and control the Namakanui cryostat.
    '''
    
    def __init__(self, inifilename, sleep, publish, simulate=None):
        '''Arguments:
            inifilename: Path to config file.
            sleep(seconds): Function to sleep for given seconds, e.g. time.sleep, drama.wait.
            publish(name, dict): Function to output dict with given name, e.g. drama.set_param.
            simulate: Bitmask. If not None (default), overrides setting in inifilename.
        '''
        # TODO simulate granularity? unsure what bits we'll have included.
        # TODO: does the cryostat have ESNs we need to check?
        self.config = IncludeParser(inifilename)
        self.sleep = sleep
        self.publish = publish
        if simulate is not None:
            self.simulate = simulate
        else:
            self.simulate = sim.str_to_bits(self.config['cryo']['simulate'])
        self.name = self.config['cryo']['pubname']
        self.state = {'number':0}
        self.logname = self.config['cryo']['logname']
        self.log = logging.getLogger(self.logname)
        self.log.debug('__init__ %s, sim=%d', inifilename, self.simulate)
        self.initialise()
    
    
    def initialise(self):
        '''
        Get state for those parameters that are not hardware readbacks,
        after which we keep track of state as the commands are given.
        Then update() to fill out the full state structure.
        '''
        self.log.debug('initialise')
        
        # fix simulate set.
        self.simulate &= sim.SIM_CRYO_FEMC
        
        if not self.simulate:
            interface = self.config['femc']['interface']
            node = int(self.config['femc']['node'], 0)
            self.femc = FEMC(interface, node)
        elif hasattr(self, 'femc'):
            del self.femc
        
        self.state['simulate'] = self.simulate
        self.state['sim_text'] = sim.bits_to_str(self.simulate)
        
        self.state['ppcomm_time'] = 0.0  # put this near the top of state
        
        # TODO: check ESNs?        
        
        if not self.simulate:
            # NOTE The name "turbopump_enable" was too long for DRAMA.
            self.state['backpump_on'] = self.femc.get_cryostat_backing_pump_enable()
            self.state['turbopump_on'] = self.femc.get_cryostat_turbo_pump_enable()
            self.state['vacgauge_on'] = self.femc.get_cryostat_vacuum_gauge_enable()
        else:
            self.state['backpump_on'] = 0
            self.state['turbopump_on'] = 0
            self.state['vacgauge_on'] = 0
        
        self.update()
        # Cryo.initialise
            
    
    def update(self):
        '''
        Update cryostat parameters.  Expect this to take ~21ms.
        Call at ~0.2Hz.
        '''
        self.log.debug('update')
         
        if not self.simulate:
            self.state['ppcomm_time'] = self.femc.get_ppcomm_time()  # expect ~1ms, TODO warn if long
        else:
            self.state['ppcomm_time'] = 0.0
         
        if self.state['backpump_on'] and not self.simulate:
            self.state['turbopump_state'] = self.femc.get_cryostat_turbo_pump_state()
            self.state['turbopump_speed'] = self.femc.get_cryostat_turbo_pump_speed()
            self.state['solvalve_state'] = self.femc.get_cryostat_solenoid_valve_state()
            # TODO: does this really depend on backing pump enabled?
            self.state['current_230v'] =  self.femc.get_cryostat_supply_current_230v()
        else:
            self.state['turbopump_state'] = 0
            self.state['turbopump_speed'] = 0
            self.state['solvalve_state'] = 0
            self.state['current_230v'] =  0.0
        
        if not self.simulate:
            self.state['gatevalve_state'] = self.femc.get_cryostat_gate_valve_state()
            self.state['vacgauge_state'] = self.femc.get_cryostat_vacuum_gauge_state()
            cpress = [self.femc.get_cryostat_vacuum_gauge_pressure(0),
                      self.femc.get_cryostat_vacuum_gauge_pressure(1)]
            self.state['cryostat_press'] = cpress
            ctemp = []
            for se in range(13):
                ctemp.append(self.femc.get_cryostat_temp(se))
            self.state['cryostat_temp'] = ctemp
        else:
            self.state['gatevalve_state'] = 0
            self.state['vacgauge_state'] = 0
            self.state['cryostat_press'] = [0.0]*2
            self.state['cryostat_temp'] = [0.0]*13
        
        self.state['number'] += 1
        self.publish(self.name, self.state)
        # Cryo.update

# TODO control funcs


    
