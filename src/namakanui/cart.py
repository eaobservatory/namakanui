'''
Ryan Berthold 20181105
Cart: Warm and Cold Cartridge monitoring and control class.
Also helper functions for dealing with tables in INI files.
'''

import namakanui  # for sleep, publish
import logging

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


def read_table(self, config_section, name, dtype, fnames):
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
        tup = ttype(dtype(x.strip()) for x in val.split(','))
        if prev is not None and tup[0] < prev:
            raise RuntimeError('[%s] %s table values are out of order' % (config_section.name, name))
        prev = tup[0]
        table.append(tup)
    return table


def interp_table(self, table, freqLO):
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
    return ttype(x + f*(y-x) for x,y in zip(table[i], table[j]))


class Cart(object):
    '''
    Monitor and control a given band (warm and cold cartridges).
    
    TODO: should instances own a reference to the FEMC, vs passing in?
    '''
    
    def __init__(self, cc, wca):
        '''
        Create a Cart instance from given sections of the config file.
        '''
        cc_band = int(cc['Band'])
        wca_band = int(wca['Band'])
        if cc_band != wca_band:
            raise RuntimeError('%s Band %d != %s Band %d' % (cc.name, cc_band, wca.name, wca_band))
        self.band = cc_band
        self.ca = self.band-1  # cartridge index for FEMC
        self.name = 'BAND%d' % (self.band)  # TODO configurable
        
        self.log = logging.getLogger(__name__ + '.' + self.name)
        
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
        fnames = 'freqLO, VJ01, VJ02, VJ11, VJ12, IJ01, IJ02, IJ11, IJ12'
        self.mixer_table = read_table(cc, 'MixerParam', float, fnames)
        fnames = 'freqLO, Pol, SIS, VD1, VD2, VD3, ID1, ID2, ID3, VG1, VG2, VG3'
        lna_table = read_table(cc, 'PreampParam', float, fnames)
        
        # the lna_table's pol/sis columns make interpolation difficult,
        # so break it up into four separate tables.
        # 4x list comprehension is inefficient, but simple.
        fnames = 'freqLO, VD1, VD2, VD3, ID1, ID2, ID3, VG1, VG2, VG3'
        ttype = collections.namedtuple('PreampParam', fnames)
        self.lna_table_01 = [ttype([r[0]] + list(r[3:])) for r in lna_table if r.Pol==0 and r.SIS==1]
        self.lna_table_02 = [ttype([r[0]] + list(r[3:])) for r in lna_table if r.Pol==0 and r.SIS==2]
        self.lna_table_11 = [ttype([r[0]] + list(r[3:])) for r in lna_table if r.Pol==1 and r.SIS==1]
        self.lna_table_12 = [ttype([r[0]] + list(r[3:])) for r in lna_table if r.Pol==1 and r.SIS==2]
        
        # hold state in a dict, for ease of DRAMA parameter publishing later
        self.state = {}
        
        # use a set of simulated components (strings) rather than a bitmask
        self.simulate = set()
        if wca.getboolean('Simulate'):
            self.simulate.add('warm')
        if cc.getboolean('Simulate'):
            self.simulate.add('cold')
        
        self.log.info('__init__ done, simulate=%s', self.simulate)
        # Cart.__init__
    
    
    def update_0(self, femc):
        '''
        Get initial state of the parameters that are not read back from hardware.
        Future updates to these parameters are done immediately when commands are sent.
        TODO accomodate single-sideband carts, e.g. band 3.
        '''
        self.state['number'] = 0
        self.state['simulate'] = ' '.join(self.simulate)
        
        # before receiving a tune command,
        # we have no way to know these parameters unless the IF switch
        # is pointing to this cartridge and it is actually locked.
        # not worth the effort.
        self.state['lo_ghz'] = 0.0
        self.state['yig_ghz'] = 0.0
        self.state['cold_mult'] = self.cold_mult
        self.state['warm_mult'] = self.warm_mult
        
        if femc:  # else simulated
            self.state['pd_enable'] = femc.get_pd_enable(self.ca)
        else:
            self.state['pd_enable'] = 0
        
        if femc and self.state['pd_enable'] and 'cold' not in self.simulate:
            sis_open_loop = []
            lna_enable = []
            lna_led_enable = []
            for po in range(2):
                for sb in range(2):
                    sis_open_loop.append(femc.get_sis_open_loop(self.ca, po, sb))
                    lna_enable.append(femc.get_lna_enable(self.ca, po, sb))
                    lna_led_enable.append(femc.get_lna_led_enable(self.ca, po, sb))
            self.state['sis_open_loop'] = sis_open_loop
            self.state['lna_enable'] = lna_enable
            self.state['lna_led_enable'] = lna_led_enable
        else:
            self.state['sis_open_loop'] = [0]*4
            self.state['lna_enable'] = [0]*4
            self.state['lna_led_enable'] = [0]*4
        
        if femc and self.state['pd_enable'] and 'warm' not in self.simulate:
            self.state['yto_coarse'] = femc.get_cartridge_lo_yto_coarse_tune(self.ca)
            #self.state[''] = femc.get_cartridge_lo_photomixer_enable(self.ca)
            self.state['pll_loop_bw'] = femc.get_cartridge_lo_pll_loop_bandwidth_select(self.ca)
            self.state['pll_sb_lock'] = femc.get_cartridge_lo_pll_sb_lock_polarity_select(self.ca)
            self.state['pll_null_int'] = femc.get_cartridge_lo_pll_null_loop_integrator(self.ca)
        else:
            self.state['yto_coarse'] = 0
            self.state['pll_loop_bw'] = 0
            self.state['pll_sb_lock'] = 0
            self.state['pll_null_int'] = 0
        
        namakanui.publish(self.name, self.state)
        # Cart.update_0
    
    
    def update_a(self, femc):
        '''
        Update LNA parameters. Expect this to take ~36ms.
        TODO accomodate single-sideband carts, e.g. band 3.
        '''
        if femc and self.state['pd_enable'] and 'cold' not in self.simulate:
            dv = []
            dc = []
            gv = []
            for po in range(2):  # polarization
                for sb in range(2):  # sideband
                    for st in range(3):  # LNA stage
                        dv.append(femc.get_lna_drain_voltage(self.ca, po, sb, st))
                        dc.append(femc.get_lna_drain_current(self.ca, po, sb, st))
                        gv.append(femc.get_lna_gate_voltage(self.ca, po, sb, st))
            self.state['lna_drain_v'] = dv;
            self.state['lna_drain_c'] = dc;
            self.state['lna_gate_v'] = gv;
        else:
            self.state['lna_drain_v'] = [0.0]*12;
            self.state['lna_drain_c'] = [0.0]*12;
            self.state['lna_gate_v'] = [0.0]*12;
            
        self.state['number'] += 1
        namakanui.publish(self.name, self.state)
        # Cart.update_a
    
    
    def update_b(self, femc):
        '''
        Update params for PLL lock, PA, SIS mixers. Expect this to take ~25ms.
        TODO accomodate single-sideband carts and those without SIS magnets (band3).
        '''
        if femc and self.state['pd_enable'] and 'warm' not in self.simulate:
            self.state['pll_lock_v'] = femc.get_cartridge_lo_pll_lock_detect_voltage(self.ca)
            self.state['pll_corr_v'] = femc.get_cartridge_lo_pll_correction_voltage(self.ca)
            self.state['pll_unlock'] = femc.get_cartridge_lo_pll_unlock_detect_latch(self.ca)
            pa_gv = []
            pa_dv = []
            pa_dc = []
            for po in range(2):  # polarization
                pa_gv.append(femc.get_cartridge_lo_pa_gate_voltage(self.ca, po))
                pa_dv.append(femc.get_cartridge_lo_pa_drain_voltage(self.ca, po))
                pa_dc.append(femc.get_cartridge_lo_pa_drain_current(self.ca, po))
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
        
        if femc and self.state['pd_enable'] and 'cold' not in self.simulate:
            sis_v = []
            sis_c = []
            sis_mag_v = []
            sis_mag_c = []
            for po in range(2):  # polarization
                for sb in range(2):  # sideband
                    sis_v.append(femc.get_sis_voltage(self.ca, po, sb))
                    sis_c.append(femc.get_sis_current(self.ca, po, sb))
                    sis_mag_v.append(femc.get_sis_magnet_voltage(self.ca, po, sb))
                    sis_mag_c.append(femc.get_sis_magnet_current(self.ca, po, sb))
            self.state['sis_v'] = sis_v
            self.state['sis_c'] = sis_c
            self.state['sis_mag_v'] = sis_mag_v
            self.state['sis_mag_c'] = sis_mag_c
        else:
            self.state['sis_v'] = [0.0]*4
            self.state['sis_c'] = [0.0]*4
            self.state['sis_mag_v'] = [0.0]*4
            self.state['sis_mag_c'] = [0.0]*4
        
        self.state['number'] += 1
        namakanui.publish(self.name, self.state)
        # Cart.update_b
    
    
    def update_c(self, femc):
        '''
        Update params for AMC, temperatures, misc. Expect this to take ~24ms.
        TODO could probably bundle into fewer top-level state params.
        '''
        if femc and self.state['pd_enable'] and 'warm' not in self.simulate:
            self.state['amc_gate_a_v'] = femc.get_cartridge_lo_amc_gate_a_voltage(self.ca)
            self.state['amc_drain_a_v'] = femc.get_cartridge_lo_amc_drain_a_voltage(self.ca)
            self.state['amc_drain_a_c'] = femc.get_cartridge_lo_amc_drain_a_current(self.ca)
            self.state['amc_gate_b_v'] = femc.get_cartridge_lo_amc_gate_b_voltage(self.ca)
            self.state['amc_drain_b_v'] = femc.get_cartridge_lo_amc_drain_b_voltage(self.ca)
            self.state['amc_drain_b_c'] = femc.get_cartridge_lo_amc_drain_b_current(self.ca)
            # TODO convert to volts?
            self.state['amc_mult_d_v'] = femc.get_cartridge_lo_amc_multiplier_d_voltage_counts(self.ca)
            self.state['amc_mult_d_c'] = femc.get_cartridge_lo_amc_multiplier_d_current(self.ca)
            self.state['amc_gate_e_v'] = femc.get_cartridge_lo_amc_gate_e_voltage(self.ca)
            self.state['amc_drain_e_v'] = femc.get_cartridge_lo_amc_drain_e_voltage(self.ca)
            self.state['amc_drain_e_c'] = femc.get_cartridge_lo_amc_drain_e_current(self.ca)
            self.state['amc_5v'] = femc.get_cartridge_lo_amc_supply_voltage_5v(self.ca)
            self.state['pa_3v'] = femc.get_cartridge_lo_pa_supply_voltage_3v(self.ca)
            self.state['pa_5v'] = femc.get_cartridge_lo_pa_supply_voltage_5v(self.ca)
            self.state['pll_temp'] = femc.get_cartridge_lo_pll_assembly_temp(self.ca)
            self.state['yig_heater_c'] = femc.get_cartridge_lo_yig_heater_current(self.ca) 
            self.state['pll_ref_power'] = femc.get_cartridge_lo_pll_ref_total_power(self.ca)
            self.state['pll_if_power'] = femc.get_cartridge_lo_pll_if_total_power(self.ca)
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
            
        if femc and self.state['pd_enable'] and 'cold' not in self.simulate:
            t = []
            for te in range(6):
                t.append(femc.get_cartridge_lo_cartridge_temp(self.ca, te))
            self.state['cart_temp'] = t
        else:
            self.state['cart_temp'] = [0.0]*6
        
        self.state['number'] += 1
        namakanui.publish(self.name, self.state)
        # Cart.update_c

    
    def tune(self, femc, lo_ghz, voltage):
        '''
        Lock the PLL to produce the given LO frequency.
        The reference signal generator must already be set properly.
        Attempt to set control voltage near given value, if not None.
        Set the proper PA, SIS, and LNA parameters.
        '''
        try:
            self.state['lo_ghz'] = lo_ghz
            self._lock_pll(femc, lo_ghz)
            self._optimize_fm(femc, voltage)
            # TODO order of the following?
            self._optimize_pa(femc, lo_ghz)
            self._optimize_lna(femc, lo_ghz)
            self._optimize_sis(femc, lo_ghz)
        except:
            # TODO: on any failure we should probably zero the PA
            # and set sis/lna to safe values.
            raise
        finally:
            self.state['number'] += 1
            namakanui.publish(self.name, self.state)
        # Cart.tune
        
        
    def _lock_pll(self, femc, lo_ghz):
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
        
        self.state['yig_ghz'] = yig_ghz
        
        # if simulating, pretend we are locked and return.
        if not femc or 'warm' in self.simulate:
            self.state['pll_lock_v'] = 5.0
            self.state['pll_corr_v'] = 0.0
            self.state['pll_unlock'] = 0
            self.state['pll_if_power'] = -2.0
            self.state['pll_ref_power'] = -2.0
            return
        
        if not self.state['pd_enable']:
            raise RuntimeError(self.name + ' power disabled')
        
        # for small changes we might hold the lock without adjustment.
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
        namakanui.sleep(0.05)  # first step might be large
        
        step = 0
        while True:
            try_counts = coarse_counts + step
            if lo_counts <= try_counts <= hi_counts:
                femc.set_cartridge_lo_pll_null_loop_integrator(self.ca, 1)
                femc.set_cartridge_lo_yto_coarse_tune(self.ca, try_counts)
                femc.set_cartridge_lo_pll_null_loop_integrator(self.ca, 0)
                namakanui.sleep(0.012)  # set YTO 10ms, lock PLL 2ms
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
        namakanui.sleep(0.05)
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
        raise RuntimeError(self.name + ' failed to lock at lo_ghz=%.9f' % (lo_ghz))
        # Cart._lock_pll
    
    def _optimize_fm(self, femc, voltage):
        '''
        Internal function only, does not publish state.
        Adjust YTO to get PLL FM (control) voltage near given value.
        If voltage is None, skip optimization.
        
        Raises RuntimeError if lock lost during this operation.
        '''
        if voltage is None:
            return
        
        if not femc or 'warm' in self.simulate:
            self.state['pll_corr_v'] = voltage
            return
        
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
        if try_counts != coarse_counts
            coarse_counts = try_counts
            femc.set_cartridge_lo_yto_coarse_tune(self.ca, coarse_counts)
            namakanui.sleep(0.05)
        
        # single-step toward target voltage until sign changes
        cv = femc.get_cartridge_lo_pll_correction_voltage(self.ca)
        ll = femc.get_cartridge_lo_pll_unlock_detect_latch(self.ca)
        relv = cv - voltage
        step = sign(relv)
        try_counts = max(0,min(4095, coarse_counts + step))
        while ll == 0 and try_counts != coarse_counts and step == sign(relv):
            coarse_counts = try_counts
            femc.set_cartridge_lo_yto_coarse_tune(self.ca, coarse_counts)
            namakanui.sleep(0.05)
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
            raise RuntimeError(self.name + ' lost lock while optimizing control voltage to %.2f at lo_ghz=%.9f' % (voltage, lo_ghz))
        # Cart._optimize_fm
  
  
    def _optimize_pa(self, femc, lo_ghz):
        pass
        
    def _optimize_lna(self, femc, lo_ghz):
        pass
        
    def _optimize_sis(self, femc, lo_ghz):
        pass

'''
TODO power on/off, demag, deflux, tune, adjust corrv

'''



