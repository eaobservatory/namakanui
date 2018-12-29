'''
Ryan Berthold 20181105
Cart: Warm and Cold Cartridge monitoring and control class.
Also helper functions for dealing with tables in INI files.
'''

from namakanui.includeparser import IncludeParser
from namakanui.femc import FEMC
import logging
import time
import collections
import bisect

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


def read_table(config_section, name, dtype, fnames):
    '''
    Return a table from a section of the config file.
    The table will be a list of namedtuples holding values of dtype.
    The config file should look like this:
        [Section]
        Names=37
        Name01=42, 64, 11
        ...
        Name37=21, 45, 66
    If the table is unsorted (ascending first column), raise RuntimeError.
    '''
    num = int(config_section[name + 's'])
    table = []
    ttype = collections.namedtuple(name, fnames)
    prev = None
    for i in range(1,num+1):
        val = config_section[name + '%02d' % (i)]
        tup = ttype(*[dtype(x.strip()) for x in val.split(',')])
        if prev is not None and tup[0] < prev:
            raise RuntimeError('[%s] %s table values are out of order' % (config_section.name, name))
        prev = tup[0]
        table.append(tup)
    return table


def interp_table(table, freqLO):
    '''
    Return a linearly-interpolated row in table at given freqLO GHz.
    Assumes freqLO is the first column in the table.
    If outside the table bounds, return the first or last row.
    If table is empty, return None.
    '''
    if not table:
        return None
    if freqLO <= table[0][0]:
        return table[0]
    if freqLO >= table[-1][0]:
        return table[-1]
    j = bisect.bisect(table, (freqLO,))
    i = j-1
    if table[i].freqLO == table[j].freqLO:
        return table[i]  # arbitrary, else divide by zero below
    f = (freqLO - table[i].freqLO) / (table[j].freqLO - table[i].freqLO)
    ttype = type(table[i])
    return ttype(*[x + f*(y-x) for x,y in zip(table[i], table[j])])


class Cart(object):
    '''
    Monitor and control a given band (warm and cold cartridges).
    NOTE: There are three update functions, so call update_one() at 0.6 Hz.
    '''
    
    def __init__(self, band, inifilename, sleep, publish):
        '''
        Create a Cart instance from given config file.
        '''
        self.config = IncludeParser(inifilename)
        self.band = band
        self.ca = self.band-1  # cartridge index for FEMC
        self.sleep = sleep
        self.publish = publish
        
        b = str(self.band)
        self.logname = self.config[b]['logname']
        self.log = logging.getLogger(self.logname)
        self.name = self.config[b]['pubname']
        self.simulate = set(self.config[b]['simulate'].split())
        self.state = {'number':0}
        # this list is used by update_one() and update_all()
        self.update_functions = [self.update_a, self.update_b, self.update_c]
        self.update_index = -1
        
        self.log.info('__init__')
        
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
        
        fnames = 'freqLO, VDA, VDB, VGA, VGB' 
        self.pa_table = read_table(wca, 'LOParam', float, fnames)
        fnames = 'freqLO, IMag01, IMag02, IMag11, IMag12'
        self.magnet_table = read_table(cc, 'MagnetParam', float, fnames)
        self.hot_magnet_table = read_table(cc, 'HotMagnet', float, fnames)
        fnames = 'freqLO, VJ01, VJ02, VJ11, VJ12, IJ01, IJ02, IJ11, IJ12'
        self.mixer_table = read_table(cc, 'MixerParam', float, fnames)
        fnames = 'freqLO, Pol, SIS, VD1, VD2, VD3, ID1, ID2, ID3, VG1, VG2, VG3'
        lna_table = read_table(cc, 'PreampParam', float, fnames)
        
        # the lna_table's pol/sis columns make interpolation difficult,
        # so break it up into four separate tables.
        # 4x list comprehension is inefficient, but simple.
        fnames = 'freqLO, VD1, VD2, VD3, ID1, ID2, ID3, VG1, VG2, VG3'
        ttype = collections.namedtuple('PreampParam', fnames)
        self.lna_table_01 = [ttype(*[r[0]] + list(r[3:])) for r in lna_table if r.Pol==0 and r.SIS==1]
        self.lna_table_02 = [ttype(*[r[0]] + list(r[3:])) for r in lna_table if r.Pol==0 and r.SIS==2]
        self.lna_table_11 = [ttype(*[r[0]] + list(r[3:])) for r in lna_table if r.Pol==1 and r.SIS==1]
        self.lna_table_12 = [ttype(*[r[0]] + list(r[3:])) for r in lna_table if r.Pol==1 and r.SIS==2]
        self.hot_lna = read_table(cc, 'HotPreamp', float, fnames)
        
        self.initialise()
        self.log.info('__init__ done')
        # Cart.__init__
    
    
    def update_all(self):
        '''Call all functions in self.update_functions, publishing once.'''
        for f in self.update_functions:
            f(do_publish=False)
        self.state['number'] += 1
        self.publish(self.name, self.state)

    
    def update_one(self):
        '''Call the next function in self.update_functions.'''
        self.update_index = (self.update_index + 1) % len(self.update_functions)
        self.update_functions[self.update_index]()

    
    def initialise(self):
        '''
        Get initial state of the parameters that are not read back from hardware.
        Future updates to these parameters are done immediately when commands are sent.
        Then fill out the remaining state using update_all() and perform
        bias voltage error measurement, which may take several seconds.
        '''
        # fix simulate set; simulated FEMC means simulated warm and cold carts.
        if 'femc' in self.simulate:
            self.simulate |= {'warm', 'cold'}
        
        self.log.info('initialise: simulate = %s', self.simulate)
        
        # (re)connect to FEMC if not simulated, otherwise delete
        if 'femc' not in self.simulate:
            interface = self.config['femc']['interface']
            node = int(self.config['femc']['node'], 0)
            self.femc = FEMC(interface, node)
        elif hasattr(self, 'femc'):
            del self.femc
        
        self.state['simulate'] = ' '.join(self.simulate)
        
        if not ('warm' in self.simulate and 'cold' in self.simulate):
            esns = self.femc.retry_esns(10, .01*self.band)
            esns = [bytes(reversed(e)).hex().upper() for e in esns]  # ini format?
            if 'warm' not in self.simulate and self.warm_esn not in esns:
                raise RuntimeError(self.logname + ' warm cartridge ESN %s not found in list: %s' % (self.warm_esn, esns))
            if 'cold' not in self.simulate and self.cold_esn not in esns:
                raise RuntimeError(self.logname + ' cold cartridge ESN %s not found in list: %s' % (self.cold_esn, esns))
        
        # before receiving a tune command, we have no way
        # to know these parameters unless the IF switch
        # is pointing to this cartridge and it is actually locked.
        # not worth the effort.
        self.state['lo_ghz'] = 0.0
        self.state['yig_ghz'] = 0.0
        self.state['cold_mult'] = self.cold_mult
        self.state['warm_mult'] = self.warm_mult
        
        if 'femc' not in self.simulate:
            self.state['pd_enable'] = self.femc.get_pd_enable(self.ca)
        else:
            self.state['pd_enable'] = 0
        
        if self.state['pd_enable'] and 'cold' not in self.simulate:
            sis_open_loop = []
            lna_enable = []
            lna_led_enable = []
            for po in range(2):
                for sb in range(2):
                    sis_open_loop.append(self.femc.get_sis_open_loop(self.ca, po, sb))
                    lna_enable.append(self.femc.get_lna_enable(self.ca, po, sb))
                    lna_led_enable.append(self.femc.get_lna_led_enable(self.ca, po, sb))
            self.state['sis_open_loop'] = sis_open_loop
            self.state['lna_enable'] = lna_enable
            self.state['lna_led_enable'] = lna_led_enable
        else:
            self.state['sis_open_loop'] = [0]*4
            self.state['lna_enable'] = [0]*4
            self.state['lna_led_enable'] = [0]*4
        
        if self.state['pd_enable'] and 'warm' not in self.simulate:
            self.state['yto_coarse'] = self.femc.get_cartridge_lo_yto_coarse_tune(self.ca)
            #self.state[''] = femc.get_cartridge_lo_photomixer_enable(self.ca)
            self.state['pll_loop_bw'] = self.femc.get_cartridge_lo_pll_loop_bandwidth_select(self.ca)
            self.state['pll_sb_lock'] = self.femc.get_cartridge_lo_pll_sb_lock_polarity_select(self.ca)
            self.state['pll_null_int'] = self.femc.get_cartridge_lo_pll_null_loop_integrator(self.ca)
        else:
            self.state['yto_coarse'] = 0
            self.state['pll_loop_bw'] = 0
            self.state['pll_sb_lock'] = 0
            self.state['pll_null_int'] = 0
        
        # create this entry so update_c doesn't need to check existence every time
        self.state['cart_temp'] = [0.0]*6
        
        # reset the hot flag so we zero params on first high_temperature()
        self.hot = False
        
        self.update_all()  # fill out rest of state dict
        
        # if the cart is already powered, measure SIS bias error.
        # sets PA gate/drain voltages to 0 as a side effect.
        # this may take a few seconds.
        self.bias_error = [0.0]*4
        if self.state['pd_enable']:
            self._calc_sis_bias_error()
        
        # Cart.initialise
    
    # TODO: it might make more logical sense to break up updates into
    # warm and cold cartridges.  warm would take ~27ms, cold would take ~60ms.
    
    def update_a(self, do_publish=True):
        '''
        Update LNA parameters. Expect this to take ~36ms.
        '''
        if self.state['pd_enable'] and 'cold' not in self.simulate:
            dv = []
            dc = []
            gv = []
            for po in range(2):  # polarization
                for sb in range(2):  # sideband
                    for st in range(3):  # LNA stage
                        dv.append(self.femc.get_lna_drain_voltage(self.ca, po, sb, st))
                        dc.append(self.femc.get_lna_drain_current(self.ca, po, sb, st))
                        gv.append(self.femc.get_lna_gate_voltage(self.ca, po, sb, st))
            self.state['lna_drain_v'] = dv;
            self.state['lna_drain_c'] = dc;
            self.state['lna_gate_v'] = gv;
        else:
            self.state['lna_drain_v'] = [0.0]*12;
            self.state['lna_drain_c'] = [0.0]*12;
            self.state['lna_gate_v'] = [0.0]*12;
        
        if do_publish:
            self.state['number'] += 1
            self.publish(self.name, self.state)
        # Cart.update_a
    
    
    def update_b(self, do_publish=True):
        '''
        Update params for PLL lock, PA, SIS mixers. Expect this to take ~25ms.
        '''
        if self.state['pd_enable'] and 'warm' not in self.simulate:
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
            self.state['pll_lock_v'] = 0.0
            self.state['pll_corr_v'] = 0.0
            self.state['pll_unlock'] = 0
            self.state['pa_gate_v'] = [0.0]*2
            self.state['pa_drain_v'] = [0.0]*2
            self.state['pa_drain_c'] = [0.0]*2
        
        if self.state['pd_enable'] and 'cold' not in self.simulate:
            sis_v = []
            sis_c = []
            sis_mag_v = []
            sis_mag_c = []
            for po in range(2):  # polarization
                for sb in range(2):  # sideband
                    sis_v.append(self.femc.get_sis_voltage(self.ca, po, sb))
                    sis_c.append(self.femc.get_sis_current(self.ca, po, sb))
                    sis_mag_v.append(self.femc.get_sis_magnet_voltage(self.ca, po, sb))
                    sis_mag_c.append(self.femc.get_sis_magnet_current(self.ca, po, sb))
            self.state['sis_v'] = sis_v
            self.state['sis_c'] = sis_c
            self.state['sis_mag_v'] = sis_mag_v
            self.state['sis_mag_c'] = sis_mag_c
        else:
            self.state['sis_v'] = [0.0]*4
            self.state['sis_c'] = [0.0]*4
            self.state['sis_mag_v'] = [0.0]*4
            self.state['sis_mag_c'] = [0.0]*4
        
        if do_publish:
            self.state['number'] += 1
            self.publish(self.name, self.state)
        # Cart.update_b
    
    
    def update_c(self, do_publish=True):
        '''
        Update params for AMC, temperatures, misc. Expect this to take ~24ms.
        TODO could probably bundle into fewer top-level state params.
        '''
        if self.state['pd_enable'] and 'warm' not in self.simulate:
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
            self.state['pll_ref_power'] = self.femc.get_cartridge_lo_pll_ref_total_power(self.ca)
            self.state['pll_if_power'] = self.femc.get_cartridge_lo_pll_if_total_power(self.ca)
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
            self.state['pll_ref_power'] = 0.0
            self.state['pll_if_power'] = 0.0
        
        # disconnected temperature sensors raise -5: hardware conversion error.
        # during testing with band3, i found that attempting to read such a
        # sensor would cause bad readings (328K vs 292K) for the pol0 mixer.
        # therefore we cache bad sensors (-1.0) and skip them on future reads.
        # if we trigger a bad read, go through the loop thrice more to clear
        # out the bad readings.
        # TODO: can other FEMC errors trigger bad temperature readings?
        if self.state['pd_enable'] and 'cold' not in self.simulate:
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
            if self.hot:
                self.log.warn('high temperature, setting pa/lna/sis to zero')
                self._ramp_sis_magnet_currents([0.0]*4)
                for i in range(4):
                    self._set_lna(i//2,i%2, [0.0]*9)
                self._ramp_sis_bias_voltages([0.0]*4)
                self._set_pa([0.0]*4)
        
        if do_publish:
            self.state['number'] += 1
            self.publish(self.name, self.state)
        # Cart.update_c


    def high_temperature(self):
        '''
        Returns True if the 4K stage, 12/20K stage, or mixers are above 30K.
        Also returns True if temperatures are unavailable or simulated.
        Uses cached temperatures in self.state; does not poll hardware.
        '''
        return any(not 0.0 < self.state['cart_temp'][te] < 30.0 for te in [0,2,4,5])
    
    
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
        in the po/sb column (useful for e.g. band8, apparently).
        '''
        if not self.magnet_table:
            return False
        if po is None and sb is None:
            return True
        nom_magnet = interp_table(self.magnet_table, self.state['lo_ghz'])[1:]
        return bool(nom_magnet[po*2 + sb])
    
    
    def tune(self, lo_ghz, voltage):
        '''
        Lock the PLL to produce the given LO frequency.
        The reference signal generator must already be set properly.
        Attempt to set PLL control voltage near given value, if not None.
        Set the proper SIS, PA, and LNA parameters.
        '''
        self.log.info('tune(%g, %g)', lo_ghz, voltage)
        try:
            self._lock_pll(lo_ghz)
            self._adjust_fm(voltage)
            
            # allow for high temperature testing
            nom_pa = interp_table(self.pa_table, lo_ghz)
            nom_mixer = interp_table(self.mixer_table, lo_ghz)
            if self.high_temperature():
                nom_magnet = interp_table(self.hot_magnet_table, lo_ghz)
                lna = interp_table(self.hot_lna_table, lo_ghz)
                nom_lna_01 = nom_lna_02 = nom_lna_11 = nom_lna_12 = lna
            else:
                nom_magnet = interp_table(self.magnet_table, lo_ghz)
                nom_lna_01 = interp_table(self.lna_table_01, lo_ghz)
                nom_lna_02 = interp_table(self.lna_table_02, lo_ghz)
                nom_lna_11 = interp_table(self.lna_table_11, lo_ghz)
                nom_lna_12 = interp_table(self.lna_table_12, lo_ghz)
            
            if nom_magnet:
                self._ramp_sis_magnet_currents(nom_magnet[1:])
            if nom_mixer:
                self._ramp_sis_bias_voltages(nom_mixer[1:5])
            if nom_pa:
                self._set_pa(nom_pa[1:])
            for i, lna in enumerate([nom_lna_01, nom_lna_02, nom_lna_11, nom_lna_12]):
                if lna:
                    self._set_lna(i//2, i%2, lna[1:])
            
            self._servo_pa()
            
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
        Raises RuntimeError on lock failure.
        '''
        yig_ghz = lo_ghz / (self.cold_mult * self.warm_mult)
        yig_step = (self.yig_hi - self.yig_lo) / 4095  # GHz per count
        coarse_counts = max(0,min(4095, int((yig_ghz - self.yig_lo) / yig_step) ))
        window_counts = int(0.05 / yig_step) + 1  # 50 MHz, ~85 counts
        step_counts = max(1, int(0.003 / yig_step))  # 3 MHz, ~5 counts for band 3/6
        lo_counts = max(0, coarse_counts - window_counts)
        hi_counts = min(4095, coarse_counts + window_counts)
        
        self.state['lo_ghz'] = lo_ghz
        self.state['yig_ghz'] = yig_ghz
        
        self.log.debug('_lock_pll lo: %.9f, yig: %.9f', lo_ghz, yig_ghz)
        
        # if simulating, pretend we are locked and return.
        if 'warm' in self.simulate:
            self.state['pll_lock_v'] = 5.0
            self.state['pll_corr_v'] = 0.0
            self.state['pll_unlock'] = 0
            self.state['pll_if_power'] = -2.0
            self.state['pll_ref_power'] = -2.0
            return
        
        # TODO move this before sim check?  enforce simulated power-on.
        # currently simulate forces pd_enable=0, though.
        if not self.state['pd_enable']:
            raise RuntimeError(self.logname + ' power disabled')
        
        # for small changes we might hold the lock without adjustment.
        femc = self.femc
        ldv = femc.get_cartridge_lo_pll_lock_detect_voltage(self.ca)
        rfp = femc.get_cartridge_lo_pll_ref_total_power(self.ca)
        ifp = femc.get_cartridge_lo_pll_if_total_power(self.ca)
        if ldv > 3.0 and rfp < -0.5 and ifp < -0.5:
            self.state['pll_lock_v'] = ldv
            self.state['pll_if_power'] = ifp
            self.state['pll_ref_power'] = rfp
            femc.set_cartridge_lo_pll_clear_unlock_detect_latch(self.ca)
            self.state['pll_unlock'] = 0
            # correction voltage might need longer to update, but check anyway
            self.state['pll_corr_v'] = femc.get_cartridge_lo_pll_correction_voltage(self.ca)
            return
        
        femc.set_cartridge_lo_pll_null_loop_integrator(self.ca, 1)
        femc.set_cartridge_lo_yto_coarse_tune(self.ca, coarse_counts)
        self.sleep(0.05)  # first step might be large
        
        step = 0
        while True:
            try_counts = coarse_counts + step
            if lo_counts <= try_counts <= hi_counts:
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
        
        if ldv > 3.0 and rfp < -0.5 and ifp < -0.5:
            femc.set_cartridge_lo_pll_clear_unlock_detect_latch(self.ca)
            self.state['pll_unlock'] = 0
            self.state['pll_corr_v'] = femc.get_cartridge_lo_pll_correction_voltage(self.ca)
            return
        
        self.state['pll_unlock'] = 1
        raise RuntimeError(self.logname + ' failed to lock at lo_ghz=%.9f' % (lo_ghz))
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
        
        self.log.debug('_adjust_fm(%.2f)', voltage)
        
        if 'warm' in self.simulate:
            self.state['pll_corr_v'] = voltage
            return
        
        if not self.state['pd_enable']:
            raise RuntimeError(self.logname + ' power disabled')
        
        femc = self.femc
        
        # TODO: FEND-40.00.00.00-089-D-MAN gives the FM tuning slope
        # as 2.5 MHz/Volt, but it might vary by cartridge.  Make configurable.
        fm_slope = 0.0025  # GHz/Volt
        yig_slope = (self.yig_hi - self.yig_lo) / 4095  # GHz/count
        counts_per_volt = fm_slope / yig_slope
        
        # start with a large jump toward target voltage.
        # assume state is already up to date, don't query femc here.
        # NOTE: correction voltage decreases as yig counts increase.
        step = round((self.state['pll_corr_v'] - voltage) * counts_per_volt)
        coarse_counts = self.state['yto_coarse']
        try_counts = max(0,min(4095, coarse_counts + step))
        if try_counts != coarse_counts:
            coarse_counts = try_counts
            femc.set_cartridge_lo_yto_coarse_tune(self.ca, coarse_counts)
            self.sleep(0.05)
        
        # single-step toward target voltage until sign changes
        cv = femc.get_cartridge_lo_pll_correction_voltage(self.ca)
        ll = femc.get_cartridge_lo_pll_unlock_detect_latch(self.ca)
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
        if ll:
            lo_ghz = self.state['lo_ghz']
            raise RuntimeError(self.logname + ' lost lock while adjusting control voltage to %.2f at lo_ghz=%.9f' % (voltage, lo_ghz))
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
        if 'warm' in self.simulate:
            return 0.0
        if not self.state['pd_enable']:
            raise RuntimeError(self.logname + ' power disabled')
        
        femc = self.femc
        
        coarse_counts = self.state['yto_coarse']
        old_counts = coarse_counts
        n = 10
        cv = 0.0
        for i in range(n):
            cv += femc.get_cartridge_lo_pll_correction_voltage(self.ca)
        cv /= n
        old_cv = cv
        voltage = sign(cv) * -8.0
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
            raise RuntimeError(self.logname + ' lost lock in estimate_fm_slope at lo_ghz=%.9f' % (lo_ghz))
        
        cv = 0.0
        for i in range(n):
            cv += femc.get_cartridge_lo_pll_correction_voltage(self.ca)
        cv /= n
        
        # TODO: counts_per_volt is what we want anyway, maybe just return it
        counts_per_volt = abs((coarse_counts - old_counts) / (cv - old_cv))
        yig_slope = (self.yig_hi - self.yig_lo) / 4095  # GHz/count
        fm_slope = counts_per_volt * yig_slope  # GHz/Volt
        return fm_slope
        # Cart._estimate_fm_slope

    
    def _servo_pa(self):
        '''
        Servo each PA[po] drain voltage to get the SIS mixer (sb=0) current
        close to nominal values from the mixer table.
        This procedure is taken from Appendix A of FEND-40.00.00.00-089-D-MAN.
        
        TODO: I'd like to see the general shape of current vs drain curves.
        In general, increased voltage produces increased mixer current,
        but there might be local maxima to deal with.
        '''
        if 'warm' in self.simulate or 'cold' in self.simulate:
            return
        if not self.state['pd_enable']:
            raise RuntimeError(self.logname + ' power disabled')
        if not self.has_sis_mixers():
            self.log.info('no SIS mixers, skipping _servo_pa')
            return
        if self.high_temperature():
            self.log.info('high temperature, skipping _servo_pa')
            return
        self.log.info('_servo_pa')
        lo_ghz = self.state['lo_ghz']
        nom_pa = interp_table(self.pa_table, lo_ghz)[1:]
        nom_mixer = interp_table(self.mixer_table, lo_ghz)
        nom_curr = [nom_mixer[5]*.001, nom_mixer[7]*.001]  # table in uA, but readout in mA.
        step = 2.5/255
        for po in range(2):
            pa = nom_pa[po]
            win_curr = nom_curr[po] * 0.05  # +-5% window
            win_lo = nom_curr[po] - win_curr
            win_hi = nom_curr[po] + win_curr
            win_dir = 0
            min_err = 1e300
            done = False
            while 0.0 < pa < 2.5 and not done:
                curr = 0.0
                n = 10
                for i in range(n):
                    # TODO do we need a short sleep between reads?
                    curr += self.femc.get_sis_current(self.ca, po, 0)
                curr /= n
                if curr < win_lo:
                    pa += step
                elif curr > win_hi:
                    pa -= step
                else:
                    # in the window, step until error increases, then step back.
                    # assign step direction only once to prevent oscillation.
                    diff_curr = nom_curr[po] - curr
                    win_dir = win_dir or sign(diff_curr) or 1
                    err = abs(diff_curr)
                    if err < min_err:
                        min_err = err
                        pa += win_dir * step
                    else:
                        pa -= win_dir * step
                        done = True
                self.femc.set_cartridge_lo_pa_pol_drain_voltage_scale(self.ca, po, pa)
                # TODO do we need a small sleep to let sis current adjust?
            if pa <= 0.0 or pa >= 2.5:
                pa = nom_pa[po]
                self.log.warn('_servo_pa[%d] failed, setting back to %g', po, pa)
                self.femc.set_cartridge_lo_pa_pol_drain_voltage_scale(self.ca, po, pa)
        # Cart._servo_pa
    
    

    def power(self, enable):
        '''
        Enable or disable power to the cartridge (state['pd_enable']).
        This will take some time.  Power-off needs to ramp SIS bias voltage
        and magnet current to zero, which may take a few seconds.
        Power-on needs to demagnetize and deflux the SIS mixers, which may
        take several MINUTES.  In practice, the cartridges will be left
        powered on most of the time.
        '''
        enable = int(bool(enable))
        if enable and not self.state['pd_enable']:  # power-on
            self.log.info('power(1): power-on...')
            if 'femc' not in self.simulate:
                self.femc.set_pd_enable(self.ca, 1)
                self.sleep(1)  # cartridge needs a second to wake up
            self.initialise()  # calls _calc_sis_bias_error
            self._set_pa([0.0]*4)
            self.demagnetize_and_deflux()
            # NOTE: we skip the "standard biasing sequence",
            # which can wait until the first tune cmd.
            self.state['number'] += 1
            self.publish(self.name, self.state)
            self.log.info('power-on complete.')
        elif self.state['pd_enable'] and not enable:  # power-off
            self.log.info('power(0): power-off...')
            self._set_pa([0.0]*4)
            self._ramp_sis_bias_voltages([0.0]*4)
            self._ramp_sis_magnet_currents([0.0]*4)
            if 'femc' not in self.simulate:
                self.state['pd_enable'] = 0  # so background UPDATE doesn't choke
                self.femc.set_pd_enable(self.ca, 0)
                self.sleep(0.1)  # TODO: does cartridge need longer to power down?
            self.initialise()
            self.log.info('power-off complete.')
        elif enable:
            self.log.info('power(1): power already on')
        else:
            self.log.info('power(0): power already off')
        # Cart.power
    
    
    def demagnetize_and_deflux(self):
        '''
        This could take a while.
        Described in section 10.1.1 of FEND-40.00.00.00-089-D-MAN.
        '''
        if 'cold' in self.simulate:
            return
        if not self.state['pd_enable']:
            raise RuntimeError(self.logname + ' power disabled')
        if self.high_temperature():
            self.log.info('high temperature, skipping demag/deflux')
            return
        self.log.info('demagnetize_and_deflux')
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
        if self.high_temperature():
            # high magnet currents can cause damage at room temperature
            self.log.info('high temperature, skipping demagnetize')
            return
        if not self.has_sis_magnets(po,sb):
            self.log.info('no SIS magnets for po=%d sb=%d, skipping demagnetize', po,sb)
            return
        self.log.info('_demagnetize(%d,%d)', po, sb)
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
            self.state['sis_mag_c'][po*2 + sb] = self.femc.get_sis_magnet_current(self.ca, po, sb)
            # TODO: save somewhere? probably too fast to justify publishing.
            self.log_debug('sis_mag_c(%d,%d): %d, %7.3f', po, sb, i_set, self.state['sis_mag_c'][po*2 + sb])
            s = endpoint - time.time()
            if s > 0.001:
                time.sleep(s)
        # Cart._demagnetize
    
    def _mixer_heating(self):
        '''
        Heat SIS mixers to 12K and wait for them to cool back down.
        Note that the heaters automatically shut off after 1s,
        so we have to keep toggling them during the loop.
        
        TODO: support heating a single polarization?
        '''
        if 'cold' in self.simulate:
            return
        if not self.has_sis_mixers():
            self.log.info('not SIS mixers, skipping mixer heating')
            return
        if self.high_temperature():
            self.log.info('high temperature, skipping mixer heating')
            return
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
        self.log.debug('_mixer_heating: current thresholds: %g %g', base_heater_current_0, base_heater_current_1)
        self.log.debug('_mixer_heating: kelvin thresholds: %g %g', base_mixer_temp_0, base_mixer_temp_1)
        target_temp = 12.0  # kelvin
        if self.band == 8:
            target_temp = 20.0
        timeout = 30
        if self.band == 9:
            timeout = 3
        timeout += time.time()  # wall time
        self.log.info('_mixer_heating: heating loop')
        while time.time() < timeout:
            # TODO: publish state during this loop?  or otherwise log currents/temps?
            heater_current_0 = self.femc.get_sis_heater_current(self.ca, 0)
            heater_current_1 = self.femc.get_sis_heater_current(self.ca, 1)
            if heater_current_0 < base_heater_current_0 or heater_current_1 < base_heater_current_1:
                self.log.debug('mixer_heating: toggling heaters')
                # heaters must be disabled, then enabled.
                self.femc.set_sis_heater_enable(self.ca, 0, 0)
                self.femc.set_sis_heater_enable(self.ca, 1, 0)
                self.femc.set_sis_heater_enable(self.ca, 0, 1)
                self.femc.set_sis_heater_enable(self.ca, 1, 1)
            self.sleep(0.02)
            mixer_temp_0 = self.femc.get_cartridge_lo_cartridge_temp(self.ca, 2)
            mixer_temp_1 = self.femc.get_cartridge_lo_cartridge_temp(self.ca, 5)
            if mixer_temp_0 >= target_temp and mixer_temp_1 >= target_temp:
                break
        # disable heaters
        self.femc.set_sis_heater_enable(self.ca, 0, 0)
        self.femc.set_sis_heater_enable(self.ca, 1, 0)
        self.log.debug('_mixer_heating: hot kelvins: %g %g', mixer_temp_0, mixer_temp_1)
        # TODO: complain if mixer temps are lower than target?
        timeout = time.time() + 300  # 5min
        self.log.info('_mixer_heating: cooldown loop')
        while time.time() < timeout:
            # TODO publish state during loop or otherwise log temps?
            self.sleep(1)
            mixer_temp_0 = self.femc.get_cartridge_lo_cartridge_temp(self.ca, 2)
            mixer_temp_1 = self.femc.get_cartridge_lo_cartridge_temp(self.ca, 5)
            if mixer_temp_0 < base_mixer_temp_0 and mixer_temp_1 < base_mixer_temp_1:
                break
        self.log.debug('_mixer_heating: cold kelvins: %g %g', mixer_temp_0, mixer_temp_1)
        if mixer_temp_0 >= base_mixer_temp_0 or mixer_temp_1 >= base_mixer_temp_1:
            raise RuntimeError(self.logname + ' _mixer_heating cooldown failed, (%g, %g) >= (%g, %g) K' % (mixer_temp_0, mixer_temp_1, base_mixer_temp_0, base_mixer_temp_1))
        # Cart._mixer_heating
    
    def _calc_sis_bias_error(self):
        '''
        Internal function, does not publish state.
        Set PAs to 0, then calculate SIS bias voltage setting error
        according to section 10.3.2 of FEND-40.00.00.00-089-D-MAN.
        '''
        self.bias_error = [0.0]*4
        if 'cold' in self.simulate:
            return
        if not self.state['pd_enable']:
            raise RuntimeError(self.logname + ' power disabled')
        if not self.has_sis_mixers():
            self.log.info('not SIS mixers, skipping bias voltage error calc')
            return
        self.log.info('calculating SIS bias voltage setting error')
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
            self.bias_error[i] = sbv[i] - sis_setting[i]
        self.log.info('SIS bias voltage setting error: %s', self.bias_error)
        self._ramp_sis_bias_voltages([0.0]*4)
        # Cart._calc_sis_bias_error
        
    
    def _ramp_sis(self, values, key, step, f):
        '''
        Internal function, does not publish state or check femc/simulate.
        Used by _ramp_sis_magnet_currents and _ramp_sis_bias_voltages.
        Assumes self.state[key] is up-to-date.
        '''
        i = 0
        for po in range(2):
            for sb in range(2):
                val = self.state[key][i]
                end = ma[i]
                inc = step * sign(end-val)
                j = 0
                while abs(end-val) > step:
                    val += inc
                    f(self.ca, po, sb, val)
                    j += 1
                    if j%80 == 0:
                        self.sleep(0.01)
                f(self.ca, po, sb, end)
                self.state[key][i] = end  # in case _ramp called again before next update
                i += 1
                self.sleep(0.01)  # these ramps might take 300ms each!
        # Cart._ramp_sis
    
    def _ramp_sis_magnet_currents(self, ma):
        '''
        Internal function, does not publish state.
        Ramp magnet currents to desired values in 0.1mA steps.
        Order of current array ma is pol/sis [01, 02, 11, 12].
        '''
        if 'cold' in self.simulate:
            self.state['sis_mag_c'] = ma
            return
        self.log.debug('ramping SIS magnet current to %s', ma)
        self._ramp_sis(ma, 'sis_mag_c', 0.1, self.femc.set_sis_magnet_current)
        # Cart._ramp_sis_magnet_currents
    
    def _ramp_sis_bias_voltages(self, mv):
        '''
        Internal function, does not publish state.
        Ramp bias voltages to desired values in 0.05mV steps.
        Order of voltage array mv is pol/sis [01, 02, 11, 12].
        Subtracts self.bias_error from given mv.
        
        NOTE use of special get_sis_voltage_cmd, TODO NEEDS TESTING ON STARTUP.
        '''
        if 'cold' in self.simulate:
            self.state['sis_v'] = mv
            return
        self.log.debug('ramping SIS bias voltage to %s', mv)
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
                self.state['sis_v'][i] = 0.0
        self.log.debug('_ramp_sis_bias_voltages arg mv:  %s', mv)
        self.log.debug('_ramp_sis_bias_voltages set mv: %s', set_mv)
        self.log.debug('_ramp_sis_bias_voltages get mv: %s', get_mv)
        self.log.debug('_ramp_sis_bias_voltages cmd mv: %s', self.state['sis_v'])
        self._ramp_sis(set_mv, 'sis_v', 0.05, self.femc.set_sis_voltage)
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
        if 'warm' in self.simulate:
            self.state['pa_drain_v'] = pa[0:2]
            self.state['pa_gate_v'] = pa[2:4]
            return
        self.log.debug('setting PA to %s', pa)
        for po in range(2):
            self.femc.set_cartridge_lo_pa_pol_drain_voltage_scale(self.ca, po, pa[po])
            self.femc.set_cartridge_lo_pa_pol_gate_voltage(self.ca, po, pa[po+2])
        # Cart._set_pa

    def _set_lna(self, po, sb, lna):
        '''
        Internal function, does not publish state.
        Given lna is [VD1, VD2, VD3, ID1, ID2, ID3, VG1, VG2, VG3] (same as table row).
        
        TODO: Where do we need to ENABLE the LNA?  Powerup? Tune? Here?
              Should we enable LNA before or after setting drain v/c?
              Do we need a pause after enabling the LNA?
        
        TODO: Are we supposed to compare to nominal gate voltage?
        
        TODO: What does LNA LED do?
        '''
        lna_state_i = (po*2 + sb) * 3
        if 'cold' in self.simulate:
            self.state['lna_drain_v'][lna_state_i:lna_state_i+3] = lna[0:3]
            self.state['lna_drain_c'][lna_state_i:lna_state_i+3] = lna[3:6]
            self.state['lna_gate_v'][lna_state_i:lna_state_i+3] = lna[6:9]
            return
        self.log.debug('setting LNA[%d][%d] to %s', po, sb, lna)
        for st in range(3):
            self.femc.set_lna_drain_voltage(self.ca, po, sb, st, lna[st])
            self.femc.set_lna_drain_current(self.ca, po, sb, st, lna[3+st])
        # Cart._set_lna




