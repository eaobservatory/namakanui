'''
RMB 20181108
Monitoring and control for the Namakanui cryostat.
Valves, pumps, pressures, temperatures, power supply.
'''

from namakanui.base import Base
from namakanui.femc import FEMC
import logging

class Cryo(Base):
    '''
    Monitor and control the Namakanui cryostat.
    
    NOTE: There is only one update function, so call update_one() at 0.2Hz.
    '''
    
    def __init__(self, inifilename, sleep, publish):
        # TODO simulate granularity? unsure what bits we'll have included.
        # TODO: does the cryostat have ESNs we need to check?
        Base.__init__(self, inifilename)  # should probably use magic super().__init__()
        self.sleep = sleep
        self.publish = publish
        self._simulate = set(self.config['cryo']['simulate'].split())  # note underscore
        self.name = self.config['cryo']['pubname']
        self.state = {'number':0}
        self.update_functions = [self.update_a]
        self.log = logging.getLogger(self.config['cryo']['logname'])
        self.simulate = self._simulate  # assignment invokes initialise()
    
    
    def initialise(self):
        '''
        Update state for those parameters that are not hardware readbacks,
        after which we keep track of state as the commands are given.
        Then update_all to fill out the full state structure.
        '''
        # fix simulate set.  for now, any implies all.  TODO
        if self._simulate:
            self._simulate = set(['femc', 'all'])  # note underscore
        
        if 'femc' not in self.simulate:
            interface = self.config['femc']['interface']
            node = int(self.config['femc']['node'], 0)
            self.femc = FEMC(interface, node)
        elif hasattr(self, 'femc'):
            del self.femc
        
        self.state['simulate'] = ' '.join(self.simulate)
        if not self.simulate:
            self.state['backpump_enable'] = self.femc.get_cryostat_backing_pump_enable()
            self.state['turbopump_enable'] = self.femc.get_cryostat_turbo_pump_enable()
            self.state['vacgauge_enable'] = self.femc.get_cryostat_vacuum_gauge_enable()
        else:
            self.state['backpump_enable'] = 0
            self.state['turbopump_enable'] = 0
            self.state['vacgauge_enable'] = 0
        
        self.update_all()
        # Cryo.initialise
            
    
    def update_a(self):
        '''
        Update cryostat parameters.  Expect this to take ~21ms.
        '''
        if self.state['backpump_enable'] and not self.simulate:
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
        # Cryo.update_a

# TODO control funcs


    
