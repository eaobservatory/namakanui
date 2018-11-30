'''
Ryan Berthold 20181016
Namakanui receiver monitoring and control.
User interface is through the Namakanui class.

TODO: Consider simulation

TODO: it'd be nice if states could have more verbose names.  nested structs?
'''

from namakanui.femc import FEMC
from namakanui.agilent import Agilent
from namakanui.cart import Cart
from namakanui.cryo import Cryo
from namakanui.version import __version__

import time
import configparser
import collections
import bisect
import logging

log = logging.getLogger(__name__)

# default publish function, does nothing
def nop(*args, **kwargs):
    pass

# user can override these after import (e.g. for a DRAMA task).
# submodules also use these, so changes immediately affect the whole system.
sleep = time.sleep  # sleep(seconds)
publish = nop  # publish(name, state)


class Namakanui(object):
    
    def __init__(self, inifilename, **kwargs):
        '''
        Read config from inifilename, then do basic initialisation.
        Sections of inifilename can be overridden using kwargs, e.g.
          nk = Namakanui('config.ini', agilent={'dbm':'-13', 'harmonic':'4'})
        
        This function does not change system state;
        if cartridges are powered off they will be left that way.
        '''
        log.info('__init__(%s, %s)', inifilename, kwargs)
        
        config = configparser.ConfigParser()
        config.read(inifilename)
        # ConfigParser has an update() method, but it overwrites whole sections.
        for section,values in kwargs:
            if not section in config:
                config[section] = {}
            config[section].update(values)
        
        
        
        # TODO might simulate agilent too
        self.agilent = Agilent(config['agilent']['ip'])
        #self.agilent.set_output(0)
        #self.agilent.set_dbm(config['agilent']['dbm'])
        self.dbm = config['agilent']['dbm']  # to be set on first tune
        self.harmonic = int(config['agilent']['harmonic'])
        self.floog = float(config['agilent']['floog'])  # GHz
        
        # TODO rearrange the config file and simplify a bit.
        
        providerCode = config['configuration']['providerCode']
        configId = config['configuration']['configId']
        configuration_name = '~Configuration%s-%s' % (providerCode, configId)
        description = config[configuration_name]['Description']
        fe_pcci = config[configuration_name]['FrontEnd']
        fe_pc = fe_pcci.split(',')[0].strip()
        fe_ci = fe_pcci.split(',')[1].strip()
        frontend_name = '~FrontEnd%s-%s' % (fe_pc, fe_ci)
        # set of shared resources to simulate, e.g. 'femc', 'load'.
        sim = config[frontend_name]['Simulate'].replace(',',' ')
        self.simulate = set(sim.split())
        
        self.femc = None
        esns = []
        if 'femc' not in self.simulate:
            interface = config['connection']['interface']
            node_id = int(config['connection']['nodeAddress'],0)
            # TODO check if simulating femc first; this might be 'none'.
            self.femc = FEMC(interface, node_id)  # TODO verbose, timeout
            log.info('femc.get_ppcomm_time: %.6fs', self.femc.get_ppcomm_time())
            esns = self.femc.get_esns()
            esns = [bytes(reversed(e)).hex().upper() for e in esns]  # ini format
            log.info('ESNs: %s', esns)
        
        fnames = 'port, band, CCProvider, CCId, WCAProvider, WCAID'
        carts = self.read_table(config[frontend_name], 'Cart', int, fnames)
        self.cart = {}  # dict of Cart instances, indexed by band number
        for c in carts:
            cc_name = '~ColdCart%s-%s' % (c.CCProvider, c.CCId)
            wca_name = '~WCA%s-%s' % (c.WCAProvider, c.WCAID)
            cart = Cart(self.femc, config[cc_name], config[wca_name])
            if cart.warm_esn not in esns:
                cart.simulate.add('warm')
            if cart.cold_esn not in esns:
                cart.simulate.add('cold')
            log.info('Band %d: [%s] [%s] simulate: %s', cart.band, wca_name, cc_name, cart.simulate)
            self.cart[cart.band] = cart
        
        # TODO more init params for cryo (config section)
        self.cryo = Cryo(self.femc)
        
        # TODO: Troubleshooting mode.
        # Newer FEMC firmware allows setting PA params (for instance)
        # without CC present, if placed in Troubleshooting mode.
        # Could perhaps put in troubleshooting mode just for powerup.
        
        # TODO: Allow for carts to be turned on and off.  We don't necessarily
        # want to change power state just because we start up this MC class.
        # Carts need to account for whether they are on/off in their updates.
        
        # TODO: All state should be filled in (even simulated state) before
        # the first publish is called, so clients don't choke.
        
        # TODO: We just need better separation between carts and namakanui supervisor;
        # carts need to take care of themselves a bit more.  supervisor controls the
        # load, sets agilent, monitors cryostat.  carts handle yig tuning.
        # so break the carts out into their own class.
        # likewise break cryo out into its own class, with its own state.
        # when we get a load, it will have its own state also.
        # publish params (name)... becomes a little more complicated.
        
        
        
        ## power up if needed
        #for band,cart in self.cart.items():
            #cart.had_power = self.femc.get_pd_enable(cart.ca)
            #if not cart.had_power and not ('warm' in cart.simulate and 'cold' in cart.simulate):
                #log.info('powering up band %d', band)
                #self.femc.set_pd_enable(cart.ca, 1)
                ## wait 1s to let cartridge wake up
                #self.sleep(1)
            #if not cart.simulate:
                ## need both warm and cold to set PA (even to zero)
                #self.femc.set_cartridge_lo_pa_pol_gate_voltage(cart.ca, 0, 0)
                #self.femc.set_cartridge_lo_pa_pol_gate_voltage(cart.ca, 1, 0)
                #self.femc.set_cartridge_lo_pa_pol_drain_voltage_scale(cart.ca, 0, 0)
                #self.femc.set_cartridge_lo_pa_pol_drain_voltage_scale(cart.ca, 1, 0)
            #if not 'cold' in cart.simulate:
                ## TODO
                ## sweep SIS magnet current and bias voltage to zero
                #pass
        
        # read initial state for shared resources and all cartridges.
        # by spacing out the carts this way, each one will update state
        # every ~1.5s instead of in .5s bursts (assuming 3 carts @ 2Hz).
        self.name = 'DYN_STATE'  # TODO better name?
        self.state = {}
        self.update_index = 0
        self.update_funcs = [self.update_a, self.cryo.update_a]
        self.update_funcs += [cart.update_a for cart in self.cart.values()]
        self.update_funcs += [cart.update_b for cart in self.cart.values()]
        self.update_funcs += [cart.update_c for cart in self.cart.values()]
        self.update_0()
        self.cryo.update_0()
        for cart in self.cart.values():
            cart.update_0()
        for f in self.update_funcs:
            self.update()
        
        ## demagnetize and deflux the carts we just turned on
        #for band,cart in self.cart.items():
            #if not cart.had_power and not 'cold' in cart.simulate:
                ## TODO
                ## perform demagnetization and mixer heating.
                #pass
            ## no more need for this
            #del cart.had_power
        
        # wait for all carts to cool back to operating temperature
        #timeout = time.time() + 5*60
        #progress = time.time() + 10
        #cold = set()
        #log.info('waiting up to 5 minutes for cartridges to cool')
        #while time.time() < timeout and cold != set(self.cart.keys()):
        
        # TODO
        # need to create a MIXER HEATING function which can do multiple
        # bands in parallel.  or heat one-by-one and wait for cooldown
        # in parallel.
        
        log.info('__init__ complete')
    
    
    def __del__(self):
        '''
        Note there is no way to guarantee python will run this function,
        so it is better to call shutdown() explicitly.
        '''
        self.shutdown()
    
    
    def shutdown(self):
        #'''
        #Put amps back in a safe state, close sockets.
        #Leaves all cartridges powered on (in standby).
        #'''
        #if self.femc:
            #log.info('shutdown femc')
            ## TODO disable amps, magnets, heaters, etc. for ALL BANDS
            #self.femc.s.close()  # TODO femc should have own shutdown func
            #self.femc = None
        #if self.agilent:
            #log.info('shutdown agilent')
            #self.agilent.set_output(0)
            #self.agilent.s.close()  # TODO: agilent should have own shutdown func
            #self.agilent = None
        # TODO -- I'm not sure this makes sense anymore
        pass
    
    
    def update(self):
        '''
        Call this function at ~2Hz.
        Update current state of the instrument.
        To avoid long pauses, each cartridge has several update functions.
        At each call we increment a counter and call the next function
        in the list; at 2Hz we get through the whole state in about 5s.
        '''
        self.update_funcs[self.update_index]()
        self.update_index = (self.update_index + 1) % len(self.update_funcs)
        # Namakanui.update
    
    
    def update_0(self):
        '''
        Set and publish shared state for relatively static parameters.
        This function is called once during __init__.
        '''
        self.state['number'] = 0
        self.state['simulate'] = ' '.join(self.simulate)
        self.state['harmonic'] = self.harmonic
        self.state['floog_ghz'] = self.floog
        # TODO make more generic, might not be an agilent...
        if self.agilent:
            self.state['agilent_out'] = self.agilent.get_output()
            self.state['agilent_dbm'] = self.agilent.get_dbm()
            self.state['agilent_ghz'] = self.agilent.get_hz() * 1e-9
        else:
            self.state['agilent_out'] = 0
            self.state['agilent_dbm'] = 0.0
            self.state['agilent_ghz'] = 0.0
        publish(self.name, self.state)
        # Namakanui.update_0
    
    
    def update_a(self):
        '''
        Update the shared state.
        '''
        if self.femc:
            self.state['ppcomm_time'] = self.femc.get_ppcomm_time()  # expect ~1ms, TODO warn if long
        else:
            self.state['ppcomm_time'] = 0.0
        self.state['number'] += 1
        publish(self.name, self.state)
        # Namakanui.update_a
    
    
    def tune(self, band, lo_ghz, voltage):
        '''
        Tune given receiver band to lo_ghz.
        If not None, optimize control voltage close to given value [-10,10].
        
        TODO:
        make sure IF switch is pointed at us first
        enable PA output at table values
        slew SIS magnet and bias voltage to table values
        servo PA drain voltage to optimize SIS current
        set LNA parameters to table values
        '''
        cart = self.cart[band]
        fyig = lo_ghz / (cart.cold_mult * cart.warm_mult)
        fsig = (fyig*cart.warm_mult + self.floog)/self.harmonic
        log.info('Namakanui tune band %d to %g GHz; YIG=%g, SG=%g', self.band, lo_ghz, fyig, fsig)
        if self.agilent:
            self.agilent.set_hz(fsig*1e9)
            self.agilent.set_dbm(self.dbm)
            self.agilent.set_output(1)
            self.state['agilent_ghz'] = fsig
            self.state['agilent_dbm'] = self.dbm
            self.state['agilent_out'] = 1
            publish(self.name, self.state)
            sleep(.05)  # wait 50ms; if close to previous frequency, PLL might hold the lock.
            
        cart.tune(self.femc, lo_ghz, voltage)  # will raise on lock failure
        
        # TODO that other stuff above: PA, SIS, LNA.
        # Namakanui.tune
        

# TODO power up/down functions per cart.







