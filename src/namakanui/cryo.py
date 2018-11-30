'''
RMB 20181108
Monitoring and control for the Namakanui cryostat.
Valves, pumps, pressures, temperatures, power supply.
'''

import time

class Cryo(object):
    '''Monitor and control the Namakanui cryostat.'''
    
    def __init__(self, femc, sleep, publish):
        # TODO simulate config from somewhere, for now sim everything.
        # TODO simulate granularity? unsure what bits we'll have included.
        self.femc = femc
        self.simulate = set(['all'])
        self.name = 'CRYO'
        self.state = {}
        # NOTE we go through a full update cycle to init state before publish.
        self.sleep = time.sleep  # event loop might not be ready yet
        self.publish = lambda: None  # nop
        self.update_0()
        self.update_all()
        self.sleep = sleep
        self.publish = publish
        self.publish(self.name, self.state)
    
    
    def update_one(self):
        '''Cycle through update_X functions.  Call at 0.2 Hz.'''
        self.update_a()
    
    
    def update_all(self):
        '''Call all update_X functions to perform a full update.'''
        self.update_a()
    
    
    def update_0(self):
        '''
        Update state for those parameters that are not hardware readbacks,
        after which we keep track of state as the commands are given.
        '''
        femc = self.femc
        self.state['number'] = 0
        self.state['simulate'] = ' '.join(self.simulate)
        if femc and not self.simulate:
            self.state['backpump_enable'] = femc.get_cryostat_backing_pump_enable()
            self.state['turbopump_enable'] = femc.get_cryostat_turbo_pump_enable()
            self.state['vacgauge_enable'] = femc.get_cryostat_vacuum_gauge_enable()
        else:
            self.state['backpump_enable'] = 0
            self.state['turbopump_enable'] = 0
            self.state['vacgauge_enable'] = 0
        self.publish(self.name, self.state)
        # Cryo.update_0
            
    
    def update_a(self):
        '''
        Update cryostat parameters.  Expect this to take ~21ms.
        '''
        femc = self.femc
        if femc and self.state['backpump_enable'] and not self.simulate:
            self.state['turbopump_state'] = femc.get_cryostat_turbo_pump_state()
            self.state['turbopump_speed'] = femc.get_cryostat_turbo_pump_speed()
            self.state['solvalve_state'] = femc.get_cryostat_solenoid_valve_state()
            # TODO: does this really depend on backing pump enabled?
            self.state['current_230v'] =  femc.get_cryostat_supply_current_230v()
        else:
            self.state['turbopump_state'] = 0
            self.state['turbopump_speed'] = 0
            self.state['solvalve_state'] = 0
            self.state['current_230v'] =  0.0
        
        if femc and not self.simulate:
            self.state['gatevalve_state'] = femc.get_cryostat_gate_valve_state()
            self.state['vacgauge_state'] = femc.get_cryostat_vacuum_gauge_state()
            cpress = [femc.get_cryostat_vacuum_gauge_pressure(0),
                      femc.get_cryostat_vacuum_gauge_pressure(1)]
            self.state['cryostat_press'] = cpress
            ctemp = []
            for se in range(13):
                ctemp.append(femc.get_cryostat_temp(se))
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


    
