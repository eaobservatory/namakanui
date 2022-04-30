'''
namakanui/cart.py   RMB 20181105

Cart: Warm and Cold Cartridge monitoring and control class.


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
import logging
import time
import collections
import os


class BadLock(RuntimeError):
    '''
    Raised by Cart.tune() if it fails to lock the receiver,
    or if the lock is lost during subsequent adjustment steps,
    but the cartridge itself is enabled and the arguments are valid.
    Having an explicit exception type for this case will let
    other functions, e.g. util.tune(), know that it's safe
    to adjust the reference signal power and try again.
    '''
    pass


def sign(x):
    '''
    Return 1 for positive, -1 for negative, and 0 for 0.
    Surprisingly, Python does not have a builtin sign() function.
    Used by Cart._optimize_fm().
    '''
    if x > 0:
        return 1
    if x < 0:
        return -1
    return 0


class Cart(object):
    '''
    Monitor and control a given band (warm and cold cartridges).
    NOTE: There are three update functions, so call update_one() at 0.6 Hz.
    '''
    
    def __init__(self, band, femc, inifile, sleep, publish, simulate=0, level=logging.INFO):
        '''
        Create a Cart instance from given config file.  Arguments:
            band: Cartridge band number, e.g. 6 for 230 GHz, 'U'u.
            femc: FEMC class instance or None if simulated.
            inifile: Path to config file or IncludeParser instance.
            sleep(seconds): Function to sleep for given seconds, e.g. time.sleep, drama.wait.
            publish(name, dict): Function to output dict with given name, e.g. drama.set_param.
            simulate: Mask, bitwise ORed with config settings.
        '''
        self.config = inifile
        if not hasattr(inifile, 'items'):
            self.config = IncludeParser(inifile)
        self.band = band
        self.ca = self.band-1  # cartridge index for FEMC
        self.femc = femc
        self.sleep = sleep
        self.publish = publish
        
        b = str(self.band)
        self.name = self.config[b]['name']
        self.log = logging.getLogger(self.name)
        self.simulate = sim.str_to_bits(self.config[b]['simulate']) | simulate
        self.state = {'number':0}
        # this list is used by update_one() and update_all()
        self.update_functions = [self.update_a, self.update_b, self.update_c]
        self.update_index = -1
        
        # flag to skip sis_v check in update_b() if currently ramping
        self.ramping_sis_v = False
        
        self.log.debug('__init__ %s, sim=%d, band=%d',
                       self.config.inifilename, self.simulate, band)
        
        cc = self.config[self.config[b]['cold']]
        wca = self.config[self.config[b]['warm']]
        cc_band = int(cc['Band'])
        wca_band = int(wca['Band'])
        if cc_band != wca_band:
            raise RuntimeError('%s Band %d != %s Band %d' % (cc.name, cc_band, wca.name, wca_band))
        if self.band != cc_band:
            raise RuntimeError('%s Band %d != given band %d' % (cc.name, cc_band, self.band))
        
        self.cold_esn = cc['ESN'].strip()
        self.warm_esn = wca['ESN'].strip()
        
        self.cold_mult = int(cc['Mult'])
        self.warm_mult = int(wca['Mult'])
        
        self.yig_lo = float(wca['FLOYIG'])
        self.yig_hi = float(wca['FHIYIG'])
        
        datapath = os.path.dirname(self.config.inifilename) + '/'
        
        fnames = 'freqLO, VDA, VDB, VGA, VGB' 
        self.pa_table = read_table_or_ascii(wca, 'LOParam', float, fnames, datapath)
        fnames = 'freqLO, IMag01, IMag02, IMag11, IMag12'
        self.magnet_table = read_table_or_ascii(cc, 'MagnetParam', float, fnames, datapath)
        self.hot_magnet_table = read_table_or_ascii(cc, 'HotMagnet', float, fnames, datapath)
        fnames = 'freqLO, VJ01, VJ02, VJ11, VJ12, IJ01, IJ02, IJ11, IJ12'
        self.mixer_table = read_table_or_ascii(cc, 'MixerParam', float, fnames, datapath)
        fnames = 'freqLO, Pol, SIS, VD1, VD2, VD3, ID1, ID2, ID3, VG1, VG2, VG3'
        lna_table = read_table_or_ascii(cc, 'PreampParam', float, fnames, datapath)
        
        # the lna_table's pol/sis columns make interpolation difficult,
        # so break it up into four separate tables.
        # 4x list comprehension is inefficient, but simple.
        fnames = 'freqLO, VD1, VD2, VD3, ID1, ID2, ID3, VG1, VG2, VG3'
        ttype = collections.namedtuple('PreampParam', fnames)
        self.lna_table_01 = [ttype(*[r[0]] + list(r[3:])) for r in lna_table if r.Pol==0 and r.SIS==1]
        self.lna_table_02 = [ttype(*[r[0]] + list(r[3:])) for r in lna_table if r.Pol==0 and r.SIS==2]
        self.lna_table_11 = [ttype(*[r[0]] + list(r[3:])) for r in lna_table if r.Pol==1 and r.SIS==1]
        self.lna_table_12 = [ttype(*[r[0]] + list(r[3:])) for r in lna_table if r.Pol==1 and r.SIS==2]
        self.hot_lna_table = read_table_or_ascii(cc, 'HotPreamp', float, fnames, datapath)
        
        self.initialise()
        
        self.log.setLevel(level)  # set log level last to allow DEBUG output during creation
        # Cart.__init__
    
    
    def update_all(self):
        '''Call all functions in self.update_functions, publishing once.'''
        self.log.debug('update_all')
        for f in self.update_functions:
            f(do_publish=False)
        self.state['number'] += 1
        self.publish(self.name, self.state)

    
    def update_one(self):
        '''Call the next function in self.update_functions.'''
        self.log.debug('update_one')
        self.update_index = (self.update_index + 1) % len(self.update_functions)
        self.update_functions[self.update_index]()

    
    def initialise(self):
        '''
        Get initial state of the parameters that are not read back from hardware.
        Future updates to these parameters are done immediately when commands are sent.
        Then fill out the remaining state using update_all() and perform
        bias voltage error measurement, which may take several seconds.
        '''
        self.log.debug('initialise')
        
        # get the sim bits specific to this cartridge band
        SIM_FEMC, SIM_WARM, SIM_COLD = sim.bits_for_band(self.band)
        
        # fix simulate set; simulated FEMC means simulated warm and cold carts.
        self.simulate &= (SIM_FEMC | SIM_WARM | SIM_COLD)
        if self.femc is None or self.femc.simulate:
            self.simulate |= SIM_FEMC
        if self.simulate & SIM_FEMC:
            self.simulate |= (SIM_WARM | SIM_COLD)
        
        self.state['simulate'] = self.simulate
        self.state['sim_text'] = sim.bits_to_str(self.simulate)
        self.log.info('initialise: simulate = %s', self.state['sim_text'])
        
        # break out sim flags just to avoid bitwise checks later
        self.sim_femc = bool(self.simulate & SIM_FEMC)
        self.sim_warm = bool(self.simulate & SIM_WARM)
        self.sim_cold = bool(self.simulate & SIM_COLD)
        
        # discard FEMC handle if simulated only via SIM_BX_FEMC
        if self.sim_femc:
            self.femc = None
        
        # RMB 20190730: cart ESNs don't seem to show up in list, so ignore.
        ## check ESNs
        #if not self.sim_femc:
            #esns = self.femc.retry_esns(10, .01*self.band)
            #esns = [bytes(reversed(e)).hex().upper() for e in esns]  # ini format?
            #if not self.sim_warm and self.warm_esn not in esns:
                #raise RuntimeError(self.name + ' warm cartridge ESN %s not found in list: %s' % (self.warm_esn, esns))
            #if not self.sim_cold and self.cold_esn not in esns:
                #raise RuntimeError(self.name + ' cold cartridge ESN %s not found in list: %s' % (self.cold_esn, esns))
        
        self.state['ppcomm_time'] = 0.0  # put this near the top of state
        
        # before receiving a tune command, we have no way
        # to know these parameters unless the IF switch
        # is pointing to this cartridge and it is actually locked.
        # not worth the effort.
        self.state['lo_ghz'] = 0.0
        self.state['yig_ghz'] = 0.0
        self.state['cold_mult'] = self.cold_mult
        self.state['warm_mult'] = self.warm_mult
        
        if not self.sim_femc:
            self.state['pd_enable'] = self.femc.get_pd_enable(self.ca)
        else:
            self.state['pd_enable'] = 0
        
        # create this entry so update_c doesn't need to check existence every time
        self.state['cart_temp'] = [0.0]*6
        
        # create this just for position in state structure
        self.state['pll_temp'] = 0.0
        
        # reset the hot flag so we zero params on first high_temperature()
        self.hot = False
        
        # this needs to be set before update_all() since high temps
        # will call _ramp_sis_bias_voltages to zero.
        self.bias_error = [0.0]*4

        # fill out rest of state dict, but don't publish yet
        for f in self.update_functions:
            f(do_publish=False)
        
        # RMB 20211123: now defer bias error calculation until first tune().
        ## if the cart is already powered, measure SIS bias error.
        ## sets PA gate/drain voltages to 0 as a side effect.
        ## this may take a few seconds.
        #self.bias_error = [0.0]*4
        #if self.state['pd_enable']:
        #    self._calc_sis_bias_error()
        
        # if config has a lock_side parameter, save it now.
        # it will be used as a default on first call to set_lock_side().
        self.default_lock_side = None
        if 'lock_side' in self.config[str(self.band)]:
            self.default_lock_side = self.config[str(self.band)]['lock_side']
        
        # publish state
        self.state['number'] += 1
        self.publish(self.name, self.state)
        # Cart.initialise
    
    # TODO: it might make more logical sense to break up updates into
    # warm and cold cartridges.  warm would take ~27ms, cold would take ~60ms.
    
    def update_a(self, do_publish=True):
        '''
        Update LNA parameters. Expect this to take ~40ms.
        '''
        self.log.debug('update_a(do_publish=%s)', do_publish)
        
        if self.state['pd_enable'] and not self.sim_cold:
            lna_enable = []
            dv = []
            dc = []
            gv = []
            for po in range(2):  # polarization
                for sb in range(2):  # sideband
                    lna_enable.append(self.femc.get_lna_enable(self.ca, po, sb))
                    for st in range(3):  # LNA stage
                        dv.append(self.femc.get_lna_drain_voltage(self.ca, po, sb, st))
                        dc.append(self.femc.get_lna_drain_current(self.ca, po, sb, st))
                        gv.append(self.femc.get_lna_gate_voltage(self.ca, po, sb, st))
            self.state['lna_enable'] = lna_enable
            self.state['lna_drain_v'] = dv
            self.state['lna_drain_c'] = dc
            self.state['lna_gate_v'] = gv
        else:
            self.state['lna_enable'] = [0]*4
            self.state['lna_drain_v'] = [0.0]*12
            self.state['lna_drain_c'] = [0.0]*12
            self.state['lna_gate_v'] = [0.0]*12
        
        if do_publish:
            self.state['number'] += 1
            self.publish(self.name, self.state)
        # Cart.update_a
    
    
    def update_b(self, do_publish=True):
        '''
        Update params for PLL lock, PA, SIS mixers. Expect this to take ~39ms.
        '''
        self.log.debug('update_b(do_publish=%s)', do_publish)
        
        if self.state['pd_enable'] and not self.sim_warm:
            self.state['yto_coarse'] = self.femc.get_cartridge_lo_yto_coarse_tune(self.ca)
            self.state['pll_ref_power'] = self.femc.get_cartridge_lo_pll_ref_total_power(self.ca)
            self.state['pll_if_power'] = self.femc.get_cartridge_lo_pll_if_total_power(self.ca)
            self.state['pll_loop_bw'] = self.femc.get_cartridge_lo_pll_loop_bandwidth_select(self.ca)
            self.state['pll_null_int'] = self.femc.get_cartridge_lo_pll_null_loop_integrator(self.ca)
            self.state['pll_sb_lock'] = self.femc.get_cartridge_lo_pll_sb_lock_polarity_select(self.ca)
            self.state['pll_lock_v'] = self.femc.get_cartridge_lo_pll_lock_detect_voltage(self.ca)
            self.state['pll_corr_v'] = self.femc.get_cartridge_lo_pll_correction_voltage(self.ca)
            self.state['pll_unlock'] = self.femc.get_cartridge_lo_pll_unlock_detect_latch(self.ca)
            pa_gv = []
            pa_dv = []
            pa_dc = []
            for po in range(2):  # polarization
                pa_gv.append(self.femc.get_cartridge_lo_pa_gate_voltage(self.ca, po))
                pa_dv.append(self.femc.get_cartridge_lo_pa_drain_voltage(self.ca, po))
                pa_dc.append(self.femc.get_cartridge_lo_pa_drain_current(self.ca, po))
            self.state['pa_gate_v'] = pa_gv
            self.state['pa_drain_v'] = pa_dv
            self.state['pa_drain_c'] = pa_dc
        else:
            self.state['yto_coarse'] = 0
            self.state['pll_ref_power'] = 0.0
            self.state['pll_if_power'] = 0.0
            self.state['pll_loop_bw'] = 0
            self.state['pll_null_int'] = 0
            self.state['pll_sb_lock'] = 0
            self.state['pll_lock_v'] = 0.0
            self.state['pll_corr_v'] = 0.0
            self.state['pll_unlock'] = 0
            self.state['pa_gate_v'] = [0.0]*2
            self.state['pa_drain_v'] = [0.0]*2
            self.state['pa_drain_c'] = [0.0]*2
        
        # pa drain voltage scale set values
        if 'pa_drain_s' not in self.state:
            self.state['pa_drain_s'] = [0.0]*2
        
        if self.state['pd_enable'] and not self.sim_cold:
            sis_open_loop = []
            sis_v = []
            sis_c = []
            sis_mag_v = []
            sis_mag_c = []
            for po in range(2):  # polarization
                for sb in range(2):  # sideband
                    sis_open_loop.append(self.femc.get_sis_open_loop(self.ca, po, sb))
                    sis_v.append(self.femc.get_sis_voltage(self.ca, po, sb))
                    sis_c.append(self.femc.get_sis_current(self.ca, po, sb))
                    sis_mag_v.append(self.femc.get_sis_magnet_voltage(self.ca, po, sb))
                    sis_mag_c.append(self.femc.get_sis_magnet_current(self.ca, po, sb))
            self.state['sis_open_loop'] = sis_open_loop
            self.state['sis_v'] = sis_v
            self.state['sis_c'] = sis_c
            self.state['sis_mag_v'] = sis_mag_v
            self.state['sis_mag_c'] = sis_mag_c
        else:
            self.state['sis_open_loop'] = [0]*4
            self.state['sis_v'] = [0.0]*4
            self.state['sis_c'] = [0.0]*4
            self.state['sis_mag_v'] = [0.0]*4
            self.state['sis_mag_c'] = [0.0]*4
        
        # sis bias voltage set values
        if 'sis_v_s' not in self.state:
            self.state['sis_v_s'] = [0.0]*4
        elif self.has_sis_mixers() and any(self.bias_error) and not self.ramping_sis_v:
            # double-check bias voltage commands and warn
            # TODO: resend bias commands?  throw an error?
            for i in range(4):
                cmd_mv = self.femc.get_sis_voltage_cmd(self.ca, i//2, i%2) + self.bias_error[i]
                if abs(cmd_mv - self.state['sis_v_s'][i]) > 0.001:
                    self.log.warning('update_b() corrupt SIS bias voltage, mixer %d set to %.3f instead of %.3f, possible TRAPPED FLUX', i, cmd_mv, self.state['sis_v_s'][i])
        
        if do_publish:
            self.state['number'] += 1
            self.publish(self.name, self.state)
        # Cart.update_b
    
    
    def update_c(self, do_publish=True):
        '''
        Update params for AMC, temperatures, misc. Expect this to take ~23ms.
        TODO could probably bundle into fewer top-level state params.
        '''
        self.log.debug('update_c(do_publish=%s)', do_publish)
        
        if not self.sim_femc:
            self.state['ppcomm_time'] = self.femc.get_ppcomm_time()  # TODO warn if >>1ms
        else:
            self.state['ppcomm_time'] = 0.0
        
        if self.state['pd_enable'] and not self.sim_warm:
            self.state['amc_gate_a_v'] = self.femc.get_cartridge_lo_amc_gate_a_voltage(self.ca)
            self.state['amc_drain_a_v'] = self.femc.get_cartridge_lo_amc_drain_a_voltage(self.ca)
            self.state['amc_drain_a_c'] = self.femc.get_cartridge_lo_amc_drain_a_current(self.ca)
            self.state['amc_gate_b_v'] = self.femc.get_cartridge_lo_amc_gate_b_voltage(self.ca)
            self.state['amc_drain_b_v'] = self.femc.get_cartridge_lo_amc_drain_b_voltage(self.ca)
            self.state['amc_drain_b_c'] = self.femc.get_cartridge_lo_amc_drain_b_current(self.ca)
            # TODO convert to volts?
            self.state['amc_mult_d_v'] = self.femc.get_cartridge_lo_amc_multiplier_d_voltage_counts(self.ca)
            self.state['amc_mult_d_c'] = self.femc.get_cartridge_lo_amc_multiplier_d_current(self.ca)
            self.state['amc_gate_e_v'] = self.femc.get_cartridge_lo_amc_gate_e_voltage(self.ca)
            self.state['amc_drain_e_v'] = self.femc.get_cartridge_lo_amc_drain_e_voltage(self.ca)
            self.state['amc_drain_e_c'] = self.femc.get_cartridge_lo_amc_drain_e_current(self.ca)
            self.state['amc_5v'] = self.femc.get_cartridge_lo_amc_supply_voltage_5v(self.ca)
            self.state['pa_3v'] = self.femc.get_cartridge_lo_pa_supply_voltage_3v(self.ca)
            self.state['pa_5v'] = self.femc.get_cartridge_lo_pa_supply_voltage_5v(self.ca)
            self.state['pll_temp'] = self.femc.get_cartridge_lo_pll_assembly_temp(self.ca)
            self.state['yig_heater_c'] = self.femc.get_cartridge_lo_yig_heater_current(self.ca) 
        else:
            self.state['amc_gate_a_v'] = 0.0
            self.state['amc_drain_a_v'] = 0.0
            self.state['amc_drain_a_c'] = 0.0
            self.state['amc_gate_b_v'] = 0.0
            self.state['amc_drain_b_v'] = 0.0
            self.state['amc_drain_b_c'] = 0.0
            self.state['amc_mult_d_v'] = 0
            self.state['amc_mult_d_c'] = 0.0
            self.state['amc_gate_e_v'] = 0.0
            self.state['amc_drain_e_v'] = 0.0
            self.state['amc_drain_e_c'] = 0.0
            self.state['amc_5v'] = 0.0
            self.state['pa_3v'] = 0.0
            self.state['pa_5v'] = 0.0
            self.state['pll_temp'] = 0.0
            self.state['yig_heater_c'] = 0.0
        
        # disconnected temperature sensors raise -5: hardware conversion error.
        # during testing with band3, i found that attempting to read such a
        # sensor would cause bad readings (328K vs 292K) for the pol0 mixer.
        # therefore we cache bad sensors (-1.0) and skip them on future reads.
        # if we trigger a bad read, go through the loop thrice more to clear
        # out the bad readings.
        # TODO: can other FEMC errors trigger bad temperature readings?
        if self.state['pd_enable'] and not self.sim_cold:
            loops = 1
            while loops:
                loops -= 1
                for te in range(6):
                    if self.state['cart_temp'][te] != -1.0:
                        try:
                            t = self.femc.get_cartridge_lo_cartridge_temp(self.ca, te)
                        except RuntimeError:
                            t = -1.0
                            loops = 3
                        self.state['cart_temp'][te] = t
        else:
            self.state['cart_temp'] = [0.0]*6
        
        # if the temperature has gone high, zero PA/LNA, mixer/magnets.
        if not self.hot:
            self.hot = self.high_temperature()
            if self.hot and self.state['pd_enable']:
                self.log.warn('high temperature, cart temps: %s', self.state['cart_temp'])
                self.zero()
        
        if do_publish:
            self.state['number'] += 1
            self.publish(self.name, self.state)
        # Cart.update_c


    def high_temperature(self):
        '''
        Returns True if the 4K stage, 12/20K stage, or mixers are above 30K.
        Also returns True if temperatures are unavailable or simulated.
        Uses cached temperatures in self.state; does not poll hardware.
        
        TODO: Consider hysteresis and what happens on cooldown.
              Do we need to reinitialize after we cool down from hot?
              Does this need to be done manually?
              Does the self.hot flag need to go into state for user?
              i.e. WAS_HOT, NEEDS_INIT
        
        NOTE: Normal order is  [4K, 110K, P0,  -1, 15K, P1]
              but for band3 is [-1, 110K, P01, -1, 15K, WCA]
              where the P01 mixers are in the 15K stage.
        
        GLT:  Band6 order is   [4K, 110K, -1,  P0, 15K, P1]
        '''
        cart_temp = self.state['cart_temp']
        if self.band == 3:
            return any(not 0.0 < cart_temp[te] < 30.0 for te in [2,4])
        return any(not 0.0 < cart_temp[te] < 30.0 for te in [0,3,4,5])
    
    
    def has_sis_mixers(self):
        '''
        Returns True if this cartridge has SIS mixers, as indicated by the
        presence of MixerParams in the config file.
        '''
        return bool(self.mixer_table)
    
    
    def has_sis_magnets(self, po=None, sb=None):
        '''
        Returns True if this cartridge has SIS magnets, as indicated by the
        presence of MagnetParams in the config file.  If po/sb are given,
        will check the table at current lo_ghz and return False for zero
        in the po/sb column (useful for band6).
        '''
        if not self.magnet_table:
            return False
        if po is None and sb is None:
            return True
        nom_magnet = interp_table(self.magnet_table, self.state['lo_ghz'])[1:]
        return bool(nom_magnet[po*2 + sb])
    
    
    def tune(self, lo_ghz, voltage, skip_servo_pa=False, lock_only=False):
        '''
        Lock the PLL to produce the given LO frequency.
        The reference signal generator must already be set properly.
        Attempt to set PLL control voltage near given value, if not None.
        Set the proper SIS, PA, and LNA parameters.
        
        It can sometimes be useful to skip_servo_pa,
        e.g. to save time during a dbm_table or mixer_pa script
        where the PA will be set manually.
        
        If lock_only is True, do not set SIS voltage, PA, LNA, or magnets;
        they will retain their previous values.  This can help avoid output
        power changes for small tuning adjustments, such as while
        doppler tracking during an observation, especially if there are
        step-changes in the tuning tables.
        '''
        self.log.info('tune(%g, %g, skip_servo_pa=%s, lock_only=%s)', lo_ghz, voltage, skip_servo_pa, lock_only)
        try:
            self._lock_pll(lo_ghz)
            self._adjust_fm(voltage)
            
            if not lock_only:
                # allow for high temperature testing
                nom_pa = interp_table(self.pa_table, lo_ghz)
                nom_mixer = interp_table(self.mixer_table, lo_ghz)
                if self.high_temperature():
                    nom_magnet = interp_table(self.hot_magnet_table, lo_ghz)
                    lna = interp_table(self.hot_lna_table, lo_ghz)
                    nom_lna_01 = nom_lna_02 = nom_lna_11 = nom_lna_12 = lna
                    # RMB 20200214: warm testing paranoia
                    nom_pa = [0.0]*5
                    nom_mixer = [0.0]*5
                else:
                    nom_magnet = interp_table(self.magnet_table, lo_ghz)
                    nom_lna_01 = interp_table(self.lna_table_01, lo_ghz)
                    nom_lna_02 = interp_table(self.lna_table_02, lo_ghz)
                    nom_lna_11 = interp_table(self.lna_table_11, lo_ghz)
                    nom_lna_12 = interp_table(self.lna_table_12, lo_ghz)
                
                # RMB 20200715: set LNA first, since apparently 
                # _set_lna_enable(1) can mess up the sis_bias_voltage values.
                for i, lna in enumerate([nom_lna_01, nom_lna_02, nom_lna_11, nom_lna_12]):
                    if lna:
                        self._set_lna(i//2, i%2, lna[1:])
                if not self.high_temperature():  # RMB 20200214: warm testing paranoia
                    self._set_lna_enable(1)

                # RMB 20211123: calculate SIS bias voltage setting error
                # if we haven't already done it -- 
                # this used to be done in initialise().
                if self.bias_error == [0.0]*4:
                    self._calc_sis_bias_error()
                
                if nom_magnet:
                    self._ramp_sis_magnet_currents(nom_magnet[1:])
                if nom_mixer:
                    self._ramp_sis_bias_voltages(nom_mixer[1:5])
                if nom_pa:
                    self._set_pa(nom_pa[1:])
                
                if not skip_servo_pa:
                    self._servo_pa()  # gets skipped at high temp already
            
            #self.log.info('past _servo_pa, double-checking bias.')

            # RMB 20200715: double-check mixer bias voltage; testing shows
            # that even commands like clear_unlock_detect_latch can
            # mess up the sis_bias_voltage values.
            if self.has_sis_mixers() and not self.sim_cold:
                for i in range(4):  # this loop may be necessary to make cmd errors visible
                    self.state['sis_v'][i] = self.femc.get_sis_voltage(self.ca, i//2, i%2)
                rebias = False
                for i in range(4):
                    cmd_mv = self.femc.get_sis_voltage_cmd(self.ca, i//2, i%2) + self.bias_error[i]
                    if abs(cmd_mv - self.state['sis_v_s'][i]) > 0.001:
                        rebias = True
                        self.log.warning('tune() corrupt SIS bias voltage, mixer %d set to %.3f instead of %.3f, resetting but there may be TRAPPED FLUX', i, cmd_mv, self.state['sis_v_s'][i])
                if rebias:
                    self._ramp_sis_bias_voltages(self.state['sis_v_s'])
                
            # final check in case we lost the lock after initial tune
            ll = 0
            if not self.sim_femc:
                ll = self.femc.get_cartridge_lo_pll_unlock_detect_latch(self.ca)
            self.state['pll_unlock'] = ll
            if ll:
                raise BadLock(self.name + ' lost lock after tuning at lo_ghz=%.9f' % (lo_ghz))
        except:
            raise
        finally:
            self.state['number'] += 1
            self.publish(self.name, self.state)
        # Cart.tune
        
        
    def _lock_pll(self, lo_ghz):
        '''
        Internal function only, does not publish state.
        Lock the PLL to produce the given LO frequency.
        The reference signal generator must already be set properly.
        Raises ValueError for bad lo_ghz, or RuntimeError on lock failure.
        '''
        # check lo_ghz against valid range.  we might be able to use
        # the correction voltage to tune slightly outside (2.3 MHz/volt),
        # but in practice _adjust_fm(0) will lose the lock.
        total_mult = self.cold_mult * self.warm_mult
        lo_min = self.yig_lo * total_mult
        lo_max = self.yig_hi * total_mult
        if not (lo_min <= lo_ghz <= lo_max):
            raise ValueError('%s _lock_pll lo_ghz %g not in [%g, %g] range' % (self.name, lo_ghz, lo_min, lo_max))
        
        yig_ghz = lo_ghz / total_mult
        yig_step = (self.yig_hi - self.yig_lo) / 4095  # GHz per count
        coarse_counts = max(0,min(4095, int((yig_ghz - self.yig_lo) / yig_step) ))
        window_counts = int(0.05 / yig_step) + 1  # 50 MHz, ~85 counts
        step_counts = max(1, int(0.003 / yig_step))  # 3 MHz, ~5 counts for band 3/6
        lo_counts = max(0, coarse_counts - window_counts)
        hi_counts = min(4095, coarse_counts + window_counts)
        
        self.state['lo_ghz'] = lo_ghz
        self.state['yig_ghz'] = yig_ghz
        
        self.log.info('_lock_pll lo=%.9f, yig=%.9f', lo_ghz, yig_ghz)
        
        # if simulating, pretend we are locked and return.
        if self.sim_warm:
            self.state['pll_lock_v'] = 5.0
            self.state['pll_corr_v'] = 0.0
            self.state['pll_unlock'] = 0
            self.state['pll_if_power'] = -2.0
            self.state['pll_ref_power'] = -2.0
            return
        
        # TODO move this before sim check?  enforce simulated power-on.
        # currently simulate forces pd_enable=0, though.
        if not self.state['pd_enable']:
            raise RuntimeError(self.name + ' power disabled')
        
        # for small changes we might hold the lock without adjustment.
        femc = self.femc
        ldv = femc.get_cartridge_lo_pll_lock_detect_voltage(self.ca)
        rfp = femc.get_cartridge_lo_pll_ref_total_power(self.ca)
        ifp = femc.get_cartridge_lo_pll_if_total_power(self.ca)
        if ldv > 3.0 and rfp < -0.5 and ifp < -0.5:  # good lock
            self.state['pll_lock_v'] = ldv
            self.state['pll_if_power'] = ifp
            self.state['pll_ref_power'] = rfp
            femc.set_cartridge_lo_pll_clear_unlock_detect_latch(self.ca)
            self.state['pll_unlock'] = 0
            # correction voltage might need longer to update, but check anyway
            cv = femc.get_cartridge_lo_pll_correction_voltage(self.ca)
            self.state['pll_corr_v'] = cv
            self.log.debug('_lock_pll already locked, corr_v %.2f', cv)
            return
        
        # if we don't have good reference power, give up now
        self.state['pll_ref_power'] = rfp
        if rfp < -3.0:
            raise RuntimeError(self.name + ' FLOOG (31.5 MHz) power too strong (%.2fV), please attenuate' % (rfp))
        if rfp > -0.5:
            raise RuntimeError(self.name + ' FLOOG (31.5 MHz) power too weak (%.2fV), check IF switch band' % (rfp))
        
        femc.set_cartridge_lo_pll_null_loop_integrator(self.ca, 1)
        femc.set_cartridge_lo_yto_coarse_tune(self.ca, coarse_counts)
        self.sleep(0.05)  # first step might be large
        
        # search outward from initial guess: +step, -step, +2step, -2step...
        step = 0
        while True:
            try_counts = coarse_counts + step
            if lo_counts <= try_counts <= hi_counts:
                self.log.debug('_lock_pll try_counts %d', try_counts)
                femc.set_cartridge_lo_pll_null_loop_integrator(self.ca, 1)
                femc.set_cartridge_lo_yto_coarse_tune(self.ca, try_counts)
                femc.set_cartridge_lo_pll_null_loop_integrator(self.ca, 0)
                self.sleep(0.012)  # set YTO 10ms, lock PLL 2ms
                ldv = femc.get_cartridge_lo_pll_lock_detect_voltage(self.ca)
                if ldv > 3.0:
                    coarse_counts = try_counts
                    break
            if step > 0:
                step = -step
            else:
                step = -step + step_counts
                if step > window_counts:  # failed to find lock
                    break
        
        femc.set_cartridge_lo_yto_coarse_tune(self.ca, coarse_counts)
        self.state['yto_coarse'] = coarse_counts
        
        # allow power readings a little time to settle
        self.sleep(0.05)
        ldv = femc.get_cartridge_lo_pll_lock_detect_voltage(self.ca)
        rfp = femc.get_cartridge_lo_pll_ref_total_power(self.ca)
        ifp = femc.get_cartridge_lo_pll_if_total_power(self.ca)
        self.state['pll_lock_v'] = ldv
        self.state['pll_ref_power'] = rfp
        self.state['pll_if_power'] = ifp
        
        if ldv > 3.0 and rfp < -0.5 and ifp < -0.5:  # good lock
            femc.set_cartridge_lo_pll_clear_unlock_detect_latch(self.ca)
            self.state['pll_unlock'] = 0
            cv = femc.get_cartridge_lo_pll_correction_voltage(self.ca)
            self.state['pll_corr_v'] = cv
            self.log.debug('_lock_pll locked, corr_v %.2f', cv)
            return
        
        self.state['pll_unlock'] = 1
        raise BadLock(self.name + ' failed to lock at lo_ghz=%.9f' % (lo_ghz))
        # Cart._lock_pll
    
    
    def _adjust_fm(self, voltage):
        '''
        Internal function only, does not publish state.
        Adjust YTO to get PLL FM (control) voltage near given value.
        If voltage is None, skip adjustment.
        
        Raises RuntimeError if lock lost during this operation.
        '''
        if voltage is None:
            return
        
        self.log.info('_adjust_fm(%.2f)', voltage)
        
        if self.sim_warm:
            self.state['pll_corr_v'] = voltage
            return
        
        if not self.state['pd_enable']:
            raise RuntimeError(self.name + ' power disabled')
        
        # deadband: skip adjustment if within +-1V of target
        if abs(self.state['pll_corr_v'] - voltage) <= 1.0:
            self.log.debug('_adjust_fm already at %.2fV, skipping.', self.state['pll_corr_v'])
            return
        
        femc = self.femc
        
        # TODO: FEND-40.00.00.00-089-D-MAN gives the FM tuning slope
        # as 2.5 MHz/Volt, but it might vary by cartridge.  Make configurable.
        # band 7, 20190731, _estimate_fm_slope:
        # counts_per_volt=2.01629, yig_slope=0.00116215 GHz/count, fm_slope=0.00234322 GHz/volt
        fm_slope = 0.0023  # GHz/Volt, conservative estimate
        yig_slope = (self.yig_hi - self.yig_lo) / 4095  # GHz/count
        counts_per_volt = fm_slope / yig_slope
        
        # quickly step toward target voltage (a large jump can lose the lock).
        # assume state is already up to date, don't query femc here.
        # NOTE: correction voltage decreases as yig counts increase.
        step = round((self.state['pll_corr_v'] - voltage) * counts_per_volt)
        coarse_counts = self.state['yto_coarse']
        try_counts = max(0,min(4095, coarse_counts + step))
        step = sign(try_counts - coarse_counts)
        self.log.debug('_adjust_fm quick-stepping from %d to %d counts...', coarse_counts, try_counts)
        while try_counts != coarse_counts:
            coarse_counts += step
            femc.set_cartridge_lo_yto_coarse_tune(self.ca, coarse_counts)
        
        # single-step toward target voltage until sign changes
        self.sleep(0.05)
        cv = femc.get_cartridge_lo_pll_correction_voltage(self.ca)
        ll = femc.get_cartridge_lo_pll_unlock_detect_latch(self.ca)
        self.log.debug('_adjust_fm unlock %d, corr_v %.2f, slow-stepping...', ll, cv)
        relv = cv - voltage
        step = sign(relv)
        try_counts = max(0,min(4095, coarse_counts + step))
        while ll == 0 and try_counts != coarse_counts and step == sign(relv):
            coarse_counts = try_counts
            femc.set_cartridge_lo_yto_coarse_tune(self.ca, coarse_counts)
            self.sleep(0.05)
            cv = femc.get_cartridge_lo_pll_correction_voltage(self.ca)
            ll = femc.get_cartridge_lo_pll_unlock_detect_latch(self.ca)
            relv = cv - voltage
            try_counts = max(0,min(4095, coarse_counts + step))
        
        self.state['yto_coarse'] = coarse_counts
        self.state['pll_corr_v'] = cv
        self.state['pll_unlock'] = ll
        self.state['pll_lock_v'] = femc.get_cartridge_lo_pll_lock_detect_voltage(self.ca)
        self.state['pll_ref_power'] = femc.get_cartridge_lo_pll_ref_total_power(self.ca)
        self.state['pll_if_power']  = femc.get_cartridge_lo_pll_if_total_power(self.ca)
        self.log.debug('_adjust_fm unlock %d, corr_v %.2f, final counts %d', ll, cv, coarse_counts)
        if ll:
            lo_ghz = self.state['lo_ghz']
            raise BadLock(self.name + ' lost lock while adjusting control voltage to %.2f at lo_ghz=%.9f' % (voltage, lo_ghz))
        # Cart._adjust_fm


    def _estimate_fm_slope(self):
        '''
        Testing function.  Does not publish state.
        Cartridge should already be tuned.
        Returns estimated FM tuning (control voltage) slope in GHz/Volt.
        Raises RuntimeError if lock is lost during this operation.
        
        This function may take a few seconds to complete, since it
        waits 0.05s between single steps of the YTO.
        '''
        self.log.info('_estimate_fm_slope')
        
        if self.sim_warm:
            return 0.0
        if not self.state['pd_enable']:
            raise RuntimeError(self.name + ' power disabled')
        
        femc = self.femc
        
        coarse_counts = self.state['yto_coarse']
        old_counts = coarse_counts
        
        # average the current correction voltage
        n = 10
        cv = 0.0
        for i in range(n):
            cv += femc.get_cartridge_lo_pll_correction_voltage(self.ca)
            self.sleep(0.01)
        cv /= n
        old_cv = cv
        
        # target voltage is 8V away, thru 0.
        voltage = sign(cv) * -8.0
        
        # single-step toward target voltage until sign changes
        relv = cv - voltage
        step = sign(relv)
        try_counts = max(0,min(4095, coarse_counts + step))
        ll = femc.get_cartridge_lo_pll_unlock_detect_latch(self.ca)
        while ll == 0 and try_counts != coarse_counts and step == sign(relv):
            coarse_counts = try_counts
            femc.set_cartridge_lo_yto_coarse_tune(self.ca, coarse_counts)
            self.sleep(0.05)
            cv = femc.get_cartridge_lo_pll_correction_voltage(self.ca)
            ll = femc.get_cartridge_lo_pll_unlock_detect_latch(self.ca)
            relv = cv - voltage
            try_counts = max(0,min(4095, coarse_counts + step))
        
        self.state['yto_coarse'] = coarse_counts
        self.state['pll_unlock'] = ll
        if ll:
            lo_ghz = self.state['lo_ghz']
            raise BadLock(self.name + ' lost lock in estimate_fm_slope at lo_ghz=%.9f' % (lo_ghz))
        
        # average new correction voltage
        cv = 0.0
        for i in range(n):
            cv += femc.get_cartridge_lo_pll_correction_voltage(self.ca)
            self.sleep(0.01)
        cv /= n
        
        # TODO: counts_per_volt is what we want anyway, maybe just return it
        counts_per_volt = abs((coarse_counts - old_counts) / (cv - old_cv))
        yig_slope = (self.yig_hi - self.yig_lo) / 4095  # GHz/count
        fm_slope = counts_per_volt * yig_slope  # GHz/Volt
        
        self.log.info('counts_per_volt=%g, yig_slope=%g GHz/count, fm_slope=%g GHz/volt',
                      counts_per_volt, yig_slope, fm_slope)
        
        return fm_slope
        # Cart._estimate_fm_slope

    
    def _servo_pa(self):
        '''
        Servo each PA[po] drain voltage to get the SIS mixer (sb=0) current
        close to nominal values from the mixer table.
        This procedure is taken from Appendix A of FEND-40.00.00.00-089-D-MAN.
        
        NOTE: PAs should already be set to nominal values from tune().
        
        Generally, increasing PA drain voltage results in greater (magnitude)
        SIS mixer current.  However, the mixer current can be noisy enough
        to result in small local minima/maxima.  The original algorithm looked
        for a +-5% "window", but I think instead we can just step toward the
        target mixer current until the error changes sign.

        The documented step of 2.5/255 can result in quantization steps
        for band7, I think due to float32 rounding.  We use a slightly
        higher value to avoid aliasing.

        20191004 HACK: Mixer 01 died, so servo the PA using sb2 instead.
        20220429: Go back to sb1 for the GLT
        '''
        self.log.info('_servo_pa')
        
        if self.sim_warm or self.sim_cold:
            return
        if not self.state['pd_enable']:
            raise RuntimeError(self.name + ' power disabled')
        if not self.has_sis_mixers():
            self.log.info('no SIS mixers, skipping _servo_pa')
            return
        if self.high_temperature():
            self.log.info('high temperature, skipping _servo_pa')
            return
        
        lo_ghz = self.state['lo_ghz']
        nom_pa = interp_table(self.pa_table, lo_ghz)[1:]
        nom_mixer = interp_table(self.mixer_table, lo_ghz)
        #nom_curr = [nom_mixer[5]*.001, nom_mixer[7]*.001]  # table in uA, but readout in mA.
        sb = 0
        nom_curr = [nom_mixer[5+sb]*.001, nom_mixer[7+sb]*.001]  # table in uA, but readout in mA.
        self.log.debug('_servo_pa nom_pa=%s, nom_curr=%s', nom_pa, nom_curr)
        for po in range(2):
            # pa affects current magnitude,
            # so for negative currents we must reverse our steps.
            step = 0.009803923  #2.5/255;
            if nom_curr[po] < 0.0:
                step *= -1.0
            pa = nom_pa[po]
            min_err = 1e300
            min_err_pa = pa
            step_dir = 0
            while 0.0 <= pa <= 2.5:
                # average mixer current
                curr = 0.0
                n = 10
                for i in range(n):
                    curr += self.femc.get_sis_current(self.ca, po, sb)
                curr /= n
                self.log.debug('_servo_pa po %d pa %.2f curr %.3f uA', po, pa, curr*1e3)
                diff_curr = nom_curr[po] - curr
                step_dir = step_dir or sign(diff_curr) or 1
                err = abs(diff_curr)
                if err < min_err:
                    min_err = err
                    min_err_pa = pa
                if sign(diff_curr) != step_dir:
                    break
                pa += step_dir * step
                self.femc.set_cartridge_lo_pa_pol_drain_voltage_scale(self.ca, po, pa)
                self.state['pa_drain_s'][po] = pa

            pa = min_err_pa
            self.femc.set_cartridge_lo_pa_pol_drain_voltage_scale(self.ca, po, pa)
            self.state['pa_drain_s'][po] = pa
            self.log.debug('_servo_pa po %d pa %.2f min_err %.3f uA (done)', po, pa, min_err*1e3)
        # Cart._servo_pa
    
    
    def zero(self):
        '''
        Disable amplifiers and ramp bias voltages and magnet currents to zero.
        Does not publish state.
        '''
        self.log.info('zeroing pa/lna/sis/mag')
        if not self.state['pd_enable']:
            return
        self._set_pa([0.0]*4)
        for po in range(2):
            for sb in range(2):
                self._set_lna(po, sb, [0.0]*9)
        self._set_lna_enable(0, force=True)
        self._ramp_sis_bias_voltages([0.0]*4)
        self._ramp_sis_magnet_currents([0.0]*4)
        # Cart.zero
    
    
    def power(self, enable):
        '''
        Enable or disable power to the cartridge (state['pd_enable']).
        This will take some time.  Power-off needs to ramp SIS bias voltage
        and magnet current to zero, which may take a few seconds.
        Power-on needs to demagnetize and deflux the SIS mixers, which may
        take several MINUTES.  In practice, the cartridges will be left
        powered on most of the time.
        
        RMB 20200413: Removed demagnetize_and_deflux on power-up.
          The temp_mon.py service effectively bypasses the procedure anyhow,
          and it really ought to be something we have more manual control over.
        '''
        enable = int(bool(enable))
        if enable and not self.state['pd_enable']:  # power-on
            self.log.info('power(1): power-on...')
            if not self.sim_femc:
                self.femc.set_pd_enable(self.ca, 1)
                self.state['pd_enable'] = 1  # in case initialise() fails
                self.log.info('1.0s sleep for cart to wake up...')
                self.sleep(1.0)  # cartridge needs some time to wake up
            self.initialise()  # calls _calc_sis_bias_error
            self._set_pa([0.0]*4)
            #self.demagnetize_and_deflux()  # RMB 20200413 removed
            # NOTE: we skip the "standard biasing sequence",
            # which can wait until the first tune cmd.
            self.state['number'] += 1
            self.publish(self.name, self.state)
            self.log.info('power-on complete.')
        elif self.state['pd_enable'] and not enable:  # power-off
            self.log.info('power(0): power-off...')
            self.zero()  # disable amps and ramp everything to 0
            if not self.sim_femc:
                self.femc.set_pd_enable(self.ca, 0)
                self.state['pd_enable'] = 0  # so background UPDATE doesn't choke
                self.log.info('0.1s sleep for cart to power down...')
                self.sleep(0.1)  # TODO: does cartridge need longer to power down?
            self.initialise()
            self.log.info('power-off complete.')
        elif enable:
            self.log.debug('power(1): power already on')
        else:
            self.log.debug('power(0): power already off')
        # Cart.power
    
    
    def demagnetize_and_deflux(self, heat=False):
        '''
        This could take a while.
        Described in section 10.1.1 of FEND-40.00.00.00-089-D-MAN.
        
        RMB 20200427: Testing shows that mixer heating does nothing
            for B6 and very little for B7.  Skip by default.
        '''
        self.log.info('demagnetize_and_deflux')
        
        if self.sim_cold:
            return
        if not self.state['pd_enable']:
            raise RuntimeError(self.name + ' power disabled')
        if self.high_temperature():
            self.log.info('high temperature, skipping demag/deflux')
            return
        
        # Preliminary Steps
        self._set_pa([0.0]*4)
        self._ramp_sis_bias_voltages([0.0]*4)  # harmless if not SIS mixers
        self._ramp_sis_magnet_currents([0.0]*4)  # harmless if no SIS magnets
        # Demagnetizing
        if not self.has_sis_magnets():
            self.log.info('no SIS magnets, skipping demagnetization')
        else:
            for po in range(2):
                for sb in range(2):
                    self._demagnetize(po,sb)
        
        # Mixer Heating
        if not heat:
            self.log.info('skipping mixer heating')
        else:
            self._mixer_heating()
        
        # Final Steps
        # NOTE: instead of setting parameters back to nominal,
        #       we leave everything at zero until next tune cmd.
        nom_i_mag = interp_table(self.magnet_table, self.state['lo_ghz'])
        if nom_i_mag:
            nom_i_mag = [1.1*x for x in nom_i_mag[1:]]
            self._ramp_sis_magnet_currents(nom_i_mag)
            self._ramp_sis_magnet_currents([0.0]*4)
        # Cart.demagnetize_and_deflux
    
    
    def _demagnetize(self, po, sb):
        '''
        Internal function.
        Demagnetize a SIS mixer.
        Assumes magnet current has already been ramped to zero.
        For band 6/7, takes 50 x 4 x 100ms = 20s.
        
        NOTE: We want to keep the timing consistent between current settings,
        but an event loop may be calling Cart.update_X functions taking 36ms
        or more.  Thus most of the sleeping in this function is done using
        regular time.sleep(), with only a brief custom sleep where the
        event loop can run.
        '''
        self.log.info('_demagnetize(%d,%d)', po, sb)
        
        if self.sim_cold:
            return
        if not self.state['pd_enable']:
            raise RuntimeError(self.name + ' power disabled')
        if self.high_temperature():
            # high magnet currents can cause damage at room temperature
            self.log.info('high temperature, skipping demagnetize')
            return
        if not self.has_sis_magnets(po,sb):
            self.log.info('no SIS magnets for po=%d sb=%d, skipping demagnetize', po,sb)
            return
        
        t0 = time.time()
        i_mag = [0,0,0,0,0, 30, 50, 50, 20, 50, 100][self.band]  # TODO make configurable
        sleep_secs = 0.1
        i_mag_dec = 1
        if self.band == 10:
            sleep_secs = 0.2
            i_mag_dec = 2
        i = 0
        while i_mag > 0:
            i_set = [i_mag, 0, -i_mag, 0][i]
            i = (i+1) % 4
            if i==0:
                i_mag -= i_mag_dec
            self.femc.set_sis_magnet_current(self.ca, po, sb, i_set)
            now = time.time()
            midpoint = now + sleep_secs*0.5
            endpoint = now + sleep_secs
            self.sleep(0.01)  # 10ms for the event loop
            s = midpoint - time.time()
            if s > 0.001:
                time.sleep(s)
            # TODO: avg several readings?
            mc = self.femc.get_sis_magnet_current(self.ca, po, sb)
            self.state['sis_mag_c'][po*2 + sb] = mc
            # TODO: save somewhere? probably too fast to justify publishing.
            self.log.debug('sis_mag_c(%d,%d): %d, %7.3f', po, sb, i_set, mc)
            s = endpoint - time.time()
            if s > 0.001:
                time.sleep(s)
        t1 = time.time()
        self.log.debug('_demagnetize: took %g seconds', t1-t0)
        # Cart._demagnetize
    
    
    def _mixer_heating(self):
        '''
        Heat SIS mixers to 12K and wait for them to cool back down.
        Note that the heaters automatically shut off after 1s,
        so we have to keep toggling them during the loop.
        
        TODO: support heating a single polarization?
        
        RMB 20200414: Testing shows that heater current never changes,
            so just toggle the heaters every 1s regardless.
            Result: B6 heating doesn't seem to work.
                    B7 rises slightly, <1K in 30s.  (.8K, .4K)
                       try toggling every 0.2s: (.8K, .4K)
                       try toggling every 2.0s: (.5K, .3K)
                       try 1s, 90s timeout: (.85K, .5K)
            
            B6: Does not work
            B7: Ineffectual
        '''
        self.log.info('_mixer_heating')
        
        if self.sim_cold:
            return
        if not self.state['pd_enable']:
            raise RuntimeError(self.name + ' power disabled')
        if not self.has_sis_mixers():
            self.log.info('not SIS mixers, skipping mixer heating')
            return
        if self.high_temperature():
            self.log.info('high temperature, skipping mixer heating')
            return

        t0 = time.time()
        self._ramp_sis_magnet_currents([0.0]*4)  # harmless if no SIS magnets
        # measure baseline pol0/1 heater current and mixer temp, 10x 50ms = 0.5s
        self.log.info('_mixer_heating: measuring baseline heater currents and mixer temps')
        base_heater_current_0 = 0.0
        base_heater_current_1 = 0.0
        base_mixer_temp_0 = 0.0
        base_mixer_temp_1 = 0.0
        n = 10
        for i in range(n):
            base_heater_current_0 += self.femc.get_sis_heater_current(self.ca, 0)
            base_heater_current_1 += self.femc.get_sis_heater_current(self.ca, 1)
            base_mixer_temp_0 += self.femc.get_cartridge_lo_cartridge_temp(self.ca, 2)
            base_mixer_temp_1 += self.femc.get_cartridge_lo_cartridge_temp(self.ca, 5)
            self.sleep(0.05)
        base_heater_current_0 = (base_heater_current_0 / n) + 1.0
        base_heater_current_1 = (base_heater_current_1 / n) + 1.0
        base_mixer_temp_0 = (base_mixer_temp_0 / n) + 0.2
        base_mixer_temp_1 = (base_mixer_temp_1 / n) + 0.2
        self.log.debug('_mixer_heating: current thresholds: %.3f %.3f', base_heater_current_0, base_heater_current_1)
        self.log.debug('_mixer_heating: kelvin thresholds: %.2f %.2f', base_mixer_temp_0, base_mixer_temp_1)
        target_temp = 12.0  # kelvin
        if self.band == 8:
            target_temp = 20.0
        timeout = 30
        if self.band == 9:
            timeout = 3
        now = time.time()
        timeout += now  # wall time
        toggle = now + 1
        debug_interval = .2
        debug_time = now + debug_interval
        self.log.info('_mixer_heating: heating loop')
        while now < timeout:
            # TODO: publish state during this loop?  or otherwise log currents/temps?
            heater_current_0 = self.femc.get_sis_heater_current(self.ca, 0)
            heater_current_1 = self.femc.get_sis_heater_current(self.ca, 1)
            #if heater_current_0 < base_heater_current_0 or heater_current_1 < base_heater_current_1:
            if now > toggle:
                toggle = now + 1
                self.log.debug('_mixer_heating: toggling heaters, %.1fs left',timeout-now)
                # heaters must be disabled, then enabled.
                self.femc.set_sis_heater_enable(self.ca, 0, 0)
                self.femc.set_sis_heater_enable(self.ca, 1, 0)
                self.femc.set_sis_heater_enable(self.ca, 0, 1)
                self.femc.set_sis_heater_enable(self.ca, 1, 1)
            self.sleep(0.02)
            mixer_temp_0 = self.femc.get_cartridge_lo_cartridge_temp(self.ca, 2)
            mixer_temp_1 = self.femc.get_cartridge_lo_cartridge_temp(self.ca, 5)
            now = time.time()
            if now >= debug_time:
                debug_time = now + debug_interval
                self.log.debug('_mixer_heating: currents [%.3f, %.3f], kelvins [%.2f, %.2f]',
                               heater_current_0, heater_current_1, mixer_temp_0, mixer_temp_1)
            if mixer_temp_0 >= target_temp and mixer_temp_1 >= target_temp:
                break
        # disable heaters
        self.femc.set_sis_heater_enable(self.ca, 0, 0)
        self.femc.set_sis_heater_enable(self.ca, 1, 0)
        self.log.info('_mixer_heating: heaters off, hot kelvins: %.2f %.2f', mixer_temp_0, mixer_temp_1)
        # TODO: complain if mixer temps are lower than target?
        timeout = time.time() + 300  # 5min
        self.log.info('_mixer_heating: cooldown loop')
        while time.time() < timeout:
            # TODO publish state during loop or otherwise log temps?
            self.sleep(1)
            mixer_temp_0 = self.femc.get_cartridge_lo_cartridge_temp(self.ca, 2)
            mixer_temp_1 = self.femc.get_cartridge_lo_cartridge_temp(self.ca, 5)
            self.log.debug('_mixer_heating: kelvins: %.2f %.2f', mixer_temp_0, mixer_temp_1)
            if mixer_temp_0 < base_mixer_temp_0 and mixer_temp_1 < base_mixer_temp_1:
                break
        self.log.info('_mixer_heating: cold kelvins: %.2f %.2f', mixer_temp_0, mixer_temp_1)
        t1 = time.time()
        self.log.debug('_mixer_heating: took %g seconds', t1-t0)
        if mixer_temp_0 >= base_mixer_temp_0 or mixer_temp_1 >= base_mixer_temp_1:
            raise RuntimeError(self.name + ' _mixer_heating cooldown failed, (%.2f, %.2f) >= (%.2f, %.2f) K' % (mixer_temp_0, mixer_temp_1, base_mixer_temp_0, base_mixer_temp_1))
        # Cart._mixer_heating
    
    
    def _calc_sis_bias_error(self):
        '''
        Internal function, does not publish state.
        Set PAs to 0, then calculate SIS bias voltage setting error
        according to section 10.3.2 of FEND-40.00.00.00-089-D-MAN.
        '''
        self.bias_error = [0.0]*4
        if self.sim_cold:
            return
        if not self.state['pd_enable']:
            raise RuntimeError(self.name + ' power disabled')
        if not self.has_sis_mixers():
            self.log.info('not SIS mixers, skipping bias voltage offset calc')
            return
        if self.high_temperature():
            self.log.info('high temperature, skipping bias voltage offset calc')
            return
        self.log.info('calculating SIS bias voltage setting offset')
        self._set_pa([0.0]*4)
        mt = self.magnet_table
        if self.high_temperature():
            mt = self.hot_magnet_table
        nominal_magnet_current = interp_table(mt, self.state['lo_ghz'])
        if nominal_magnet_current:
            self._ramp_sis_magnet_currents(nominal_magnet_current[1:])
        sis_setting = [0,0,0, 10.0, 4.8, 2.3, 9.0, 2.2, 2.2, 2.3, 2.2][self.band]  # TODO config
        self._ramp_sis_bias_voltages([sis_setting]*4)  # note bias_error=0 here
        self.sleep(0.01)
        sbv = [0.0]*4  # avg sis bias voltage reading
        n = 100
        for i in range(n):
            for po in range(2):
                for sb in range(2):
                    sbv[po*2 + sb] += self.femc.get_sis_voltage(self.ca, po, sb)
            if (i+1)%20 == 0:  # every ~80ms
                self.sleep(.01)
        for i in range(4):
            sbv[i] = sbv[i]/n
            self.bias_error[i] = sbv[i] - sis_setting
        self.log.info('SIS bias voltage setting offset: %s', self.bias_error)
        self._ramp_sis_bias_voltages([0.0]*4)
        # Cart._calc_sis_bias_error
        
    
    def _ramp_sis(self, values, key, step, f):
        '''
        Internal function, does not publish state or check femc/simulate.
        Used by _ramp_sis_magnet_currents and _ramp_sis_bias_voltages.
        Assumes self.state[key] is up-to-date.
        
        TODO: Ramp in parallel, it's probably safe.
        '''
        i = 0
        j = 0  # sleep counter
        for po in range(2):
            for sb in range(2):
                val = self.state[key][i]
                end = values[i]
                inc = step * sign(end-val)
                while abs(end-val) > step:
                    val += inc
                    f(self.ca, po, sb, val)
                    j += 1
                    if j%80 == 0:
                        self.sleep(0.01)
                f(self.ca, po, sb, end)
                self.state[key][i] = end  # in case _ramp called again before next update
                i += 1
                #self.sleep(0.01)  # these ramps might take 300ms each!
        # Cart._ramp_sis
    
    
    def _ramp_sis_magnet_currents(self, ma):
        '''
        Internal function, does not publish state.
        Ramp magnet currents to desired values in 0.1mA steps.
        Order of current array ma is pol/sis [01, 02, 11, 12].
        '''
        self.log.debug('_ramp_sis_magnet_currents(%s)', ma)
        if self.sim_cold:
            self.state['sis_mag_c'] = ma
            return
        if not self.state['pd_enable']:
            raise RuntimeError(self.name + ' power disabled')
        self._ramp_sis(ma, 'sis_mag_c', 0.1, self.femc.set_sis_magnet_current)
        # Cart._ramp_sis_magnet_currents
    
    
    def _ramp_sis_bias_voltages(self, mv, retry=3):
        '''
        Internal function, does not publish state.
        Ramp bias voltages to desired values in 0.05mV steps.
        Order of voltage array mv is pol/sis [01, 02, 11, 12].
        Subtracts self.bias_error from given mv.
        
        RMB 20200714: A set_sis_voltage command will sometimes cause the
            FEMC to set one of the other mixers to the wrong value.
            Double-check and retry, or raise RuntimeError if out of tries.
        '''
        self.log.debug('_ramp_sis_bias_voltages(%s)', mv)
        self.state['sis_v_s'] = mv
        if self.sim_cold:
            self.state['sis_v'] = mv
            return
        if not self.state['pd_enable']:
            raise RuntimeError(self.name + ' power disabled')
        set_mv = [0.0]*4
        get_mv = [0.0]*4
        for i in range(4):
            set_mv[i] = mv[i] - self.bias_error[i]
            get_mv[i] = self.femc.get_sis_voltage(self.ca, i//2, i%2)
            # this can fail if bias voltage not set yet; assume 0.
            # maybe this test should move into FEMC class code.
            try:
                self.state['sis_v'][i] = self.femc.get_sis_voltage_cmd(self.ca, i//2, i%2)
            except RuntimeError:
                self.state['sis_v'][i] = 0.0  # or should we use get_mv[i]?
        self.log.debug('_ramp_sis_bias_voltages arg mv:  %s', mv)
        self.log.debug('_ramp_sis_bias_voltages get mv: %s', get_mv)
        self.log.debug('_ramp_sis_bias_voltages set mv: %s', set_mv)
        self.log.debug('_ramp_sis_bias_voltages cmd mv: %s', self.state['sis_v'])
        try:
            self.ramping_sis_v = True
            self._ramp_sis(set_mv, 'sis_v', 0.05, self.femc.set_sis_voltage)
        finally:
            self.ramping_sis_v = False
        # double-check and retry
        for i in range(4):  # this loop may be necessary to make cmd errors visible
            self.state['sis_v'][i] = self.femc.get_sis_voltage(self.ca, i//2, i%2)
        for i in range(4):
            cmd_mv = self.femc.get_sis_voltage_cmd(self.ca, i//2, i%2) + self.bias_error[i]
            if abs(cmd_mv - mv[i]) > 0.001:
                emsg = '_ramp_sis_bias_voltages bad cmd, mixer %d set to %.3f instead of %.3f'%(i, cmd_mv, mv[i])
                if retry:
                    self.log.warning(emsg + ', retrying but there might be TRAPPED FLUX')
                    return self._ramp_sis_bias_voltages(mv, retry-1)
                else:
                    self.log.error(emsg + ', raising error.')
                    raise RuntimeError(emsg)
        # Cart._ramp_sis_bias_voltages
    
    
    def _set_pa(self, pa):
        '''
        Internal function, does not publish state.
        Given pa is [VDA, VDB, VGA, VGB] (same as table row),
        where (I assume) A is pol0 and B is pol1.
        
        TODO: Setting these without a cold cartridge (even to zero)
        might require putting the FEMC into TROUBLESHOOTING mode.
        
        TODO: Is there a disconnect between set (scale) and get (voltage)?
        Do the INI file parameters account for scale correctly?
        '''
        self.log.debug('_set_pa(%s)', pa)
        if self.sim_warm:
            self.state['pa_drain_v'] = pa[0:2]
            self.state['pa_drain_s'] = pa[0:2]
            if len(pa) > 2:
                self.state['pa_gate_v'] = pa[2:4]
            return
        if not self.state['pd_enable']:
            raise RuntimeError(self.name + ' power disabled')
        for po in range(2):
            self.femc.set_cartridge_lo_pa_pol_drain_voltage_scale(self.ca, po, pa[po])
            self.state['pa_drain_s'][po] = pa[po]
            if len(pa) > 2:
                self.femc.set_cartridge_lo_pa_pol_gate_voltage(self.ca, po, pa[po+2])
        # Cart._set_pa


    def _set_lna(self, po, sb, lna):
        '''
        Internal function, does not publish state.
        Given lna is [VD1, VD2, VD3, ID1, ID2, ID3, VG1, VG2, VG3] (same as table row).
        '''
        self.log.debug('_set_lna(%d, %d, %s)', po, sb, lna)
        lna_state_i = (po*2 + sb) * 3
        if self.sim_cold:
            self.state['lna_drain_v'][lna_state_i:lna_state_i+3] = lna[0:3]
            self.state['lna_drain_c'][lna_state_i:lna_state_i+3] = lna[3:6]
            self.state['lna_gate_v'][lna_state_i:lna_state_i+3] = lna[6:9]
            return
        if not self.state['pd_enable']:
            raise RuntimeError(self.name + ' power disabled')
        for st in range(3):
            self.femc.set_lna_drain_voltage(self.ca, po, sb, st, lna[st])
            self.femc.set_lna_drain_current(self.ca, po, sb, st, lna[3+st])
        # Cart._set_lna


    def _set_lna_enable(self, enable, force=False):
        '''
        Internal function, does not publish state.
        Calls set_lna_enable for all mixers where enable doesn't match
        current state, which is kept updated by the update_a function.
        '''
        self.log.info('_set_lna_enable(%s, force=%s)', enable, force)
        enable = int(bool(enable))
        if self.sim_cold:
            self.state['lna_enable'] = [enable]*4
            return
        if not self.state['pd_enable']:
            raise RuntimeError(self.name + ' power disabled')
        for po in range(2):
            for sb in range(2):
                if force or enable != self.state['lna_enable'][po*2 + sb]:
                    self.femc.set_lna_enable(self.ca, po, sb, enable)
                    self.state['lna_enable'][po*2 + sb] = enable
        # Cart._set_lna_enable

    
    def set_lock_side(self, lock_side, force=False):
        '''
        Set PLL to lock above or below the reference signal.
        Argument lock_side:
            0 or "below": lock below reference
            1 or "above": lock above reference
            None: use value from config on first call,
                  no change on subsequent calls
        Updates state but does not publish.
        Does nothing if lock_side already matches state[pll_sb_lock],
        which is kept updated by the update_b function.
        '''
        lock_side = lock_side or self.default_lock_side
        self.default_lock_side = None  # use for first call only
        if lock_side is None:
            lock_side = self.state['pll_sb_lock']
        else:
            lock_side = lock_side.lower() if hasattr(lock_side, 'lower') else lock_side
            lock_side = {0:0, 1:1, '0':0, '1':1, 'below':0, 'above':1}[lock_side]
        lock_str = {0:'below', 1:'above'}[lock_side]
        self.log.info('set_lock_side(%d, force=%s): %s', lock_side, force, lock_str)
        if self.sim_warm:
            self.state['pll_sb_lock'] = lock_side
            return
        if not self.state['pd_enable']:
            raise RuntimeError(self.name + ' power disabled')
        if force or lock_side != self.state['pll_sb_lock']:
            self.femc.set_cartridge_lo_pll_sb_lock_polarity_select(self.ca, lock_side)
            self.state['pll_sb_lock'] = lock_side
        # Cart.set_lock_side
