'''
RMB 20181108
Monitoring and control for the Namakanui cryostat.
Valves, pumps, pressures, temperatures, power supply.
'''

from namakanui.includeparser import IncludeParser
from namakanui.femc import FEMC
from namakanui import sim
import logging

class Cryo(object):
    '''
    Monitor and control the Namakanui cryostat.
    '''
    
    def __init__(self, inifilename, sleep, publish, simulate=None):
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
        self.initialise()
    
    
    def initialise(self):
        '''
        Update state for those parameters that are not hardware readbacks,
        after which we keep track of state as the commands are given.
        Then update() to fill out the full state structure.
        '''
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
            self.state['backpump_enable'] = self.femc.get_cryostat_backing_pump_enable()
            self.state['turbopump_enable'] = self.femc.get_cryostat_turbo_pump_enable()
            self.state['vacgauge_enable'] = self.femc.get_cryostat_vacuum_gauge_enable()
        else:
            self.state['backpump_enable'] = 0
            self.state['turbopump_enable'] = 0
            self.state['vacgauge_enable'] = 0
        
        self.update()
        # Cryo.initialise
            
    
    def update(self):
        '''
        Update cryostat parameters.  Expect this to take ~21ms.
        Call at ~0.2Hz.
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
        
        if not self.simulate:
            self.state['ppcomm_time'] = self.femc.get_ppcomm_time()  # expect ~1ms, TODO warn if long
        else:
            self.state['ppcomm_time'] = 0.0
        
        self.state['number'] += 1
        self.publish(self.name, self.state)
        # Cryo.update

# TODO control funcs


    
