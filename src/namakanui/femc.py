'''
namakanui/femc.py   RMB 20180607

Python3 SocketCAN interface to the FEMC.

This software was designed using the following documents as references:

    ALMA-40.00.00.00-70.35.25.00-C-ICD  -- FEMC Interface Control Document
    FEND-40.04.03.03-002-A-DSN -- FEMC RCA Map
    ALMA-70.35.10.03-001-A-SPE -- ALMA MC Bus Interface Specification
    FEND-40.00.00.00-173-A-MAN -- front end operation manual
    FEND-40.09.03.00-053-A-MAN -- front end engineering control software user manual

And also the FEMC firmware code:

    https://github.com/morganmcleod/ALMA-FEMC

Abbreviations:

    AMC:   Active Multiplier Chain
    EDFA:  Erbium-Doped Fiber Amplifier
    FETIM: Front End Thermal Interlock Module
    FLOOG: First LO Offset Generator
    LPR:   LO Photonic Receiver
    PA:    Power Amplifier
    PLL:   Phase Locked Loop
    RCA:   Relative CAN Address
    YIG:   Yttrium Iron Garnet
    YTO:   YIG Tuned Oscillator

SAFETY: Check https://safe.nrao.edu/wiki/bin/view/ALMA/FrontEndOperationManual
Various components might be subject to damaging power levels.
Certain operations must be run with fe_mode=1 (troubleshooting),
which disables certain interlocks.  Users are advised to read all listed
documents before using this module.


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
import namakanui.util

import sys
import socket
import struct
import time
import select
import logging

# Custom exception types for more obvious fault messages
class FEMC_RuntimeError(RuntimeError):
    pass

class FEMC_ValueError(ValueError):
    pass

_errors = {
    -1: "communication problem between control module and peripheral",
    -2: "addressed hardware not installed",
    -3: "operation restricted by hardware manufacturer directives",
    -4: "(warning) properties of addressed hardware not fully encoded",
    -5: "hardware conversion error",
    -6: "(warning) hardware readout retry",
    -7: "hardware error state",
    -10: "value in error range",
    -11: "(warning) value in warning range",
    -12: "undefined RCA",
    -13: "value in error range, action taken by FEMC",
    -14: "(warning) value in warning range, action taken by FEMC",
    -15: "feature not yet implemented in hardware"
}

_setup_errors = {
    0: "no error, comms established",
    1: "error registering special monitor functions",
    2: "error registering special control functions",
    3: "error registering monitor functions",
    4: "error registering control functions",
    5: "warning, this function has already been called",
    6: "AMBSI1-ARCOM communication not yet established",
    7: "timeout while forwarding CAN message to ARCOM board",
    8: "the FEMC is booting up; wait until ready"
}

# compiled structs might save a bit of parsing time when packing/unpacking
# can0: canid, dlc, pad, data
_IB3x8s = struct.Struct("<IB3x8s")
# pcan: len, type, tag, timestamp, chan, dlc, flags, canid, candata
_HH8x8xxBHI8s = struct.Struct(">HH8x8xxBHI8s")
_b = struct.Struct("b")
_B = struct.Struct("B")
_H = struct.Struct(">H")
_f = struct.Struct(">f")
_Bb = struct.Struct("Bb")
_Hb = struct.Struct(">Hb")
_fb = struct.Struct(">fb")


# RCA offsets for submodule functions, taken from FEND-40.04.03.03-002-A-DSN,
# double-checking against FEMC firmware code to correct any errors.

_sis_voltage =   0x08
_sis_current =   0x10
_sis_open_loop = 0x18

_sis_magnet_voltage = 0x20
_sis_magnet_current = 0x30

_lna_drain_voltage = 0x40
_lna_drain_current = 0x41
_lna_gate_voltage =  0x42
_lna_enable = 0x58

_lna_led_enable = 0x100

_sis_heater_enable =  0x180
_sis_heater_current = 0x1c0

_dac_reset_strobe = 0x280
_dac_clear_strobe = 0x2a0

_lo_yto_coarse_tune =    0x800  # NOTE ushort counts

_lo_photomixer_enable =  0x810
_lo_photomixer_voltage = 0x814
_lo_photomixer_current = 0x818

_lo_pll_lock_detect_voltage =  0x820
_lo_pll_correction_voltage =   0x821
_lo_pll_assembly_temp =        0x822
_lo_pll_yig_heater_current =   0x823
_lo_pll_ref_total_power =      0x824
_lo_pll_if_total_power =       0x825
# NOTE 0x826 is skipped -- 'bogoFunction' (bogus?) in FEMC firmware code
_lo_pll_unlock_detect_latch =       0x827
_lo_pll_clear_unlock_detect_latch = 0x828
_lo_pll_loop_bandwidth_select =     0x829
_lo_pll_sb_lock_polarity_select =   0x82a
_lo_pll_null_loop_integrator =      0x82b

_lo_amc_gate_a_voltage =  0x830
_lo_amc_drain_a_voltage = 0x831
_lo_amc_drain_a_current = 0x832
_lo_amc_gate_b_voltage =  0x833
_lo_amc_drain_b_voltage = 0x834
_lo_amc_drain_b_current = 0x835
_lo_amc_multiplier_d_voltage = 0x836  # NOTE ubyte counts, not float
_lo_amc_gate_e_voltage =  0x837
_lo_amc_drain_e_voltage = 0x838
_lo_amc_drain_e_current = 0x839
_lo_amc_multiplier_d_current = 0x83a
_lo_amc_supply_voltage_5v = 0x83b

_lo_pa_gate_voltage =  0x840
_lo_pa_drain_voltage = 0x841
_lo_pa_drain_current = 0x842
_lo_pa_supply_voltage_3v = 0x848
_lo_pa_supply_voltage_5v = 0x84c

_lo_cartridge_temp = 0x880

_pd_current = 0xa000
_pd_voltage = 0xa001
_pd_enable =  0xa00c
_pd_powered_modules = 0xa0a0

# if_switch 0xb000 TODO if needed -- i.e. if using ALMA vs homebrew.

_cryostat_temp = 0xc000
_cryostat_backing_pump_enable = 0xc034
#_cryostat_backing_pump_current  # no such thing
_cryostat_turbo_pump_enable = 0xc038
_cryostat_turbo_pump_state =  0xc039
_cryostat_turbo_pump_speed =  0xc03a
_cryostat_gate_valve_state =  0xc03c
_cryostat_solenoid_valve_state = 0xc040
_cryostat_vacuum_controller_pressure = 0xc044
_cryostat_vacuum_controller_enable =   0xc046
_cryostat_vacuum_controller_state =    0xc047
_cryostat_supply_current_230v = 0xc048
#_cryostat_cold_head  # skipping this, hours & reset -- will not use.

# FEND-40.04.03.03-002-A-DSN was no use here; below from firmware code.
#LPR 0xd000
# mask 0x00030, shift 4
#  0-1 lprTemp lprTempHandler (no subs)
#  2 optical switch opticalSwitchHandler
#     0x0000F, shift 1  (shouldn't it be 0xE?) (no subs on these)
#     0: porthandler
#     1: shutterhandler
#     2: forceshutterhandler (only control)
#     3: statehandler
#     4: busyhandler
#  3 edfa edfaHandler
#     0x0000C, shift 2
#     0: laser
#         0x00003, no shift
#         0: pumpTempHandler
#         1: driveCurrentHandler
#         2: photoDetectCurrentHandler
#     1: photodetector
#         0x00003, no shift
#         0: current
#         1: conversion coefficient
#         2: power
#     2: modulationinput
#         0x00002, shift 1
#         0: valueHandler
#         1: MISpecialMsgs (control only)
#            0: DAC reset strobe
#     3: driverstate -- no sub (temp alarm)

_lpr_temp = 0xd000

_lpr_opt_switch_port =    0xd020
_lpr_opt_switch_shutter = 0xd022
_lpr_opt_switch_force_shutter = 0xd024
_lpr_opt_switch_state =   0xd026
_lpr_opt_switch_busy =    0xd028

_lpr_edfa_laser_pump_temp =     0xd030
_lpr_edfa_laser_drive_current = 0xd031
_lpr_edfa_laser_photo_detect_current = 0xd032

_lpr_edfa_photo_detector_current = 0xd034
#_lpr_edfa_photo_detector_conversion_coefficient = 0xd035  # no docs
_lpr_edfa_photo_detector_power =   0xd036

_lpr_edfa_modulation_input_value = 0xd038
_lpr_edfa_modulation_input_special_dac_reset_strobe = 0xd03a

_lpr_edfa_driver_state = 0xd03c  # temperature alarm


# fetim 0xe000 TODO if needed -- might not be installed


# TODO: come up with a better output format for verbose messages.
# ought to mimic candump output, e.g.:
# 00505822   [5]  00 00 00 00 FF

class FEMC(object):
    
    def __init__(self, inifile=None, sleep=time.sleep, publish=namakanui.nop, simulate=0, level=logging.INFO):
        '''Arguments:
            inifile: Path to config file or IncludeParser instance.
            sleep(seconds): Function to sleep for given seconds, e.g. time.sleep, drama.wait.
            publish(name, dict): Function to output dict with given name, e.g. drama.set_param.
            simulate: Mask, bitwise ORed with config settings.
            level: Logging level, default INFO.
        '''
        if inifile is None:
            binpath, datapath = namakanui.util.get_paths()
            inifile = datapath + 'femc.ini'
        self.config = inifile
        if not hasattr(inifile, 'items'):
            self.config = IncludeParser(inifile)
        cfg = self.config['femc']
        self.sleep = sleep
        self.publish = publish
        self.simulate = sim.str_to_bits(cfg['simulate']) | simulate
        self.simulate &= sim.SIM_FEMC
        self.name = cfg['name']
        
        self.log = logging.getLogger(self.name)
        
        self.interface = cfg['interface']
        self.node_id = int(cfg['node'], 0)
        self.node = (self.node_id+1) << 18
        self.timeout = float(cfg['timeout'])
        self.fe_mode = int(cfg['fe_mode'])
        self.pcand = 'use_pcand' in cfg and int(cfg['use_pcand'])
        self.pcan = 'use_pcan' in cfg and int(cfg['use_pcan'])
        self.pcan = self.pcan or self.pcand  # for struct pack/unpack
        
        self.state = {'number':0,
                      'simulate':self.simulate,
                      'interface':self.interface,
                      'node':self.node_id,
                      'timeout':self.timeout,
                      'fe_mode':self.fe_mode,
                     }
        
        # create a socket even if simulated so close() is simple
        #self.s = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
        self.s_tx = socket.socket()
        self.s_rx = self.s_tx
        
        self.log.debug('__init__ %s, sim=%d, interface=%s, node=0x%x, timeout=%g',
                       self.config.inifilename, self.simulate,
                       self.interface, self.node_id, self.timeout)
        
        # NOTE This class does not yet handle simulate;
        #      caller must not invoke any other methods if simulated.
        if self.simulate:
            self.update()
            return
        
        if self.pcand:  # connect to daemon, always tcp
            pcand_ip = cfg['pcand_ip']
            pcand_port = int(cfg['pcand_port'])
            self.state['interface'] = 'pcand://%s:%d'%(pcand_ip, pcand_port)
            self.s_tx.settimeout(self.timeout)
            self.log.debug('connecting to namakanui_pcand.py at %s:%d', pcand_ip, pcand_port)
            self.s_tx.connect((pcand_ip, pcand_port))
            self.s_tx.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        
        elif self.pcan:  # connect directly to PEAK PCAN-Ethernet Gateway
            pcan_type = cfg['pcan_type'].lower()
            lan2can_ip = cfg['lan2can_ip']  # PCAN IP
            lan2can_port = int(cfg['lan2can_port'])
            can2lan_port = int(cfg['can2lan_port'])  # on localhost
            iface = '%s://%s:%d:%d'%(pcan_type, lan2can_ip, lan2can_port, can2lan_port)
            self.state['interface'] = iface
            if pcan_type == 'tcp':
                self.s_tx.settimeout(self.timeout)
                self.log.debug('connecting tcp pcan tx at %s:%d', lan2can_ip, lan2can_port)
                self.s_tx.connect((lan2can_ip, lan2can_port))
                can2lan_listener = socket.socket()
                can2lan_listener.settimeout(5)
                can2lan_listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self.log.debug('waiting for tcp pcan rx on port %d', can2lan_port)
                can2lan_listener.bind(('0.0.0.0', can2lan_port))
                can2lan_listener.listen()
                self.s_rx = can2lan_listener.accept()[0]
                self.s_rx.settimeout(self.timeout)
                can2lan_listener.shutdown(socket.SHUT_RDWR)
                can2lan_listener.close()
            else:  # udp
                self.s_tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.s_tx.settimeout(self.timeout)
                # connect() here avoids having to use sendto() later
                self.log.debug('connect udp pcan tx at %s:%d', lan2can_ip, lan2can_port)
                self.s_tx.connect((lan2can_ip, lan2can_port))
                self.s_rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.s_rx.settimeout(self.timeout)
                self.log.debug('bind udp pcan rx on port %d', can2lan_port)
                self.s_rx.bind(('0.0.0.0', can2lan_port))
        
        else: # socketcan
            self.log.debug('bind socketcan interface %s', self.interface)
            self.s_tx = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
            self.s_tx.bind((self.interface,))
            self.s_tx.settimeout(self.timeout)
            self.s_rx = self.s_tx
        
        setup = self.get_setup_info()
        if setup != 0 and setup != 5:
            estr = _setup_errors.get(setup, "unknown error")
            raise FEMC_RuntimeError("get_setup_info error: %d: %s" % (setup, estr))
        
        self.set_fe_mode(self.fe_mode, do_publish=False)

        # PCAN TCP will send old replies to a new connection,
        # so try clearing the rx socket at this point.
        self.clear()
        
        # TODO: other setup/init
        
        self.update()
        
        self.log.setLevel(level)  # set log level last to allow DEBUG output during creation
        # FEMC.__init__
        
    def __del__(self):
        self.log.debug('__del__')
        self.close()
    
    def close(self):
        self.log.debug('close')
        self.s_tx.close()
        self.s_rx.close()
    
    def update(self):
        # TODO include ppcomm and other stats in state
        self.state['number'] += 1
        self.publish(self.name, self.state)
    
    def clear(self):
        '''Empty the rx socket buffer.  Used before sending a command.
           RMB 20200228: This function has been raising socket.timeout errors,
                         which seems impossible.  Perhaps there's a mutex involved,
                         and if one process gets rescheduled while holding it,
                         the other can time out on rare occasions.  For now I
                         will just ignore socket.timeout, up to 3 times.
        '''
        tries = 0
        r,w,x = select.select([self.s_rx], [], [], 0)
        while r:
            try:
                self.s_rx.recv(65536)  # minimize loops
            except socket.timeout:
                self.log.debug('clear: recv socket.timeout')
                tries += 1
                if tries > 3:
                    raise
                # if there is a mutex involved, a small sleep might allow
                # the other process to grab it back.  40ms for context switch.
                time.sleep(.04)
            r,w,x = select.select([self.s_rx], [], [], 0)
        
    def make_rca(self, cartridge=0, polarization=0, sideband=0, lna_stage=0,
                 dac=0, pa_channel=0, cartridge_temp=0, pd_module=0, pd_channel=0,
                 if_channel_po=0, if_channel_sb=0, cryostat_temp=0, vacuum_sensor=0,
                 lpr_temp=0):
        '''Return an RCA mask built up from given components.
           You should OR this with the fixed RCA offset for the particular
           monitor/control point you're calling.'''
        if cartridge < 0 or cartridge > 9:
            raise FEMC_ValueError("cartridge outside [0,9] range")
        if polarization < 0 or polarization > 1:
            raise FEMC_ValueError("polarization outside [0,1] range")
        if sideband < 0 or sideband > 1:
            raise FEMC_ValueError("sideband outside [0,1] range")
        if lna_stage < 0 or lna_stage > 5:
            raise FEMC_ValueError("lna_stage outside [0,5] range")
        if dac < 0 or dac > 1:
            raise FEMC_ValueError("dac outside [0,1] range")
        if pa_channel < 0 or pa_channel > 1:
            raise FEMC_ValueError("pa_channel outside [0,1] range")
        if cartridge_temp < 0 or cartridge_temp > 5:
            raise FEMC_ValueError("cartridge_temp outside [0,5] range")
        if pd_module < 0 or pd_module > 9:
            raise FEMC_ValueError("pd_module outside [0,9] range")
        if pd_channel < 0 or pd_channel > 5:
            raise FEMC_ValueError("pd_channel outside [0,5] range")  # TODO CHECK ME
        if if_channel_po < 0 or if_channel_po > 1:
            raise FEMC_ValueError("if_channel_po outside [0,1] range")
        if if_channel_sb < 0 or if_channel_sb > 1:
            raise FEMC_ValueError("if_channel_sb outside [0,1] range")
        if cryostat_temp < 0 or cryostat_temp > 12:
            raise FEMC_ValueError("cryostat_temp outside [0,12] range")
        if vacuum_sensor < 0 or vacuum_sensor > 1:
            raise FEMC_ValueError("vacuum_sensor outside [0,1] range")
        if lpr_temp < 0 or lpr_temp > 1:
            raise FEMC_ValueError("lpr_temp outside [0,1] range")
        return cartridge<<12 | polarization<<10 | sideband<<7 \
                | lna_stage<<2 | dac<<6 | pa_channel<<2 | cartridge_temp<<4 \
                | pd_module<<4 | pd_channel<<1 \
                | if_channel_po<<3 | if_channel_sb<<2 \
                | cryostat_temp<<2 | vacuum_sensor<<0 \
                | lpr_temp<<4
        
    
    def set_rca(self, rca, data):
        '''Send SocketCAN packet to RCA with packed data bytes.
           Before sending, empties the socket of any waiting data --
           these are commands/replies of any concurrent clients.
           The transmit queue is very shallow, so we select() until
           the socket is writable, then try to send until timeout.
           '''
        if self.pcan:
            packet = _HH8x8xxBHI8s.pack(36, 0x80, len(data), 0x02,
                                        socket.CAN_EFF_FLAG | self.node | rca, data)
        else:
            packet = _IB3x8s.pack(socket.CAN_EFF_FLAG | self.node | rca, len(data), data)
        plen = len(packet)
        self.log.debug('set_rca send %d bytes: 0x%s', plen, packet.hex())
        self.clear()  # empty socket buffer of any nonrelated traffic
        timeout = self.s_tx.gettimeout() or 0
        wall_timeout = time.time() + timeout
        while timeout >= 0:
            r,w,x = select.select([], [self.s_tx], [], timeout)
            try:
                num = self.s_tx.send(packet)
                if num != plen:
                    raise FEMC_RuntimeError("only sent %d/%d bytes" % (num, plen))
                return
            except OSError as e:
                if e.errno == 105:  # No buffer space available
                    timeout = wall_timeout - time.time()
                    continue
                else:
                    raise
        raise FEMC_RuntimeError("timeout waiting to send")
        
    def try_get_rca(self, rca):
        '''Send SocketCAN packet to RCA and return reply data bytes.
           For resilience to other traffic on bus (or misread commands),
           keep looking for a matching reply id until timeout expires.
           20181128: The matching reply id must have data bytes, otherwise
                     we assume it's an outgoing command and ignore it.'''
        s_can_id = self.node | rca
        self.set_rca(rca, b'')
        r_can_id = None
        data_len = 0
        timeout = time.time() + (self.s_rx.gettimeout() or 0)
        badreps = []
        plen = 16
        if self.pcan:
            plen = 36
        while (r_can_id is None) or ((r_can_id != s_can_id or not data_len) and time.time() < timeout):
            try:
                reply = self.s_rx.recv(plen)
            except socket.timeout:
                break
            if len(reply) != plen:
                raise FEMC_RuntimeError("only received %d/%d bytes: 0x%s" % (len(reply), plen,  reply.hex()))
            self.log.debug('get_rca recv %d bytes: 0x%s', len(reply), reply.hex())
            if self.pcan:
                plen, mtype, data_len, flags, r_can_id, data = _HH8x8xxBHI8s.unpack(reply)
            else:
                r_can_id, data_len, data = _IB3x8s.unpack(reply)
            r_can_id &= socket.CAN_EFF_MASK
            if r_can_id != s_can_id:
                badreps.append(reply.hex())
                self.log.debug('get_rca %x unexpected reply id %x', s_can_id, r_can_id)
            elif not data_len:
                badreps.append(reply.hex())
                self.log.debug('get_rca %x got reply with no data', s_can_id)
        if r_can_id != s_can_id or not data_len:
            raise FEMC_RuntimeError("timeout after %d bad replies: %s" % (len(badreps), "<omitted>"))#badreps))
        data = data[:data_len]
        return data
    
    def get_rca(self, rca):
        '''Call try_get_rca in a loop since sometimes the FEMC ignores us.'''
        loop = 0
        loops = 10
        while loop < loops:
            if loop:
                self.log.debug('get_rca retry %s', loop)
            try:
                data = self.try_get_rca(rca)
                return data
            except FEMC_RuntimeError as e:
                self.log.debug('get_rca %s', e)
                loop += 1
                if loop >= loops:
                    raise
    
    def set_special(self, rca_offset, ubyte=0):
        '''Send a SPECIAL control command, base 0x21000'''
        self.set_rca(0x21000 | rca_offset, _B.pack(ubyte))
    
    def get_special(self, rca_offset):
        '''Send a SPECIAL monitor command, base 0x20000; return data bytes.'''
        return self.get_rca(0x20000 | rca_offset)
    
    def try_set_get_rca(self, rca, data):
        '''Set, then get same rca to check for errors.
           Used by STANDARD control commands.
           On error, raise a FEMC_RuntimeError exception.'''
        self.set_rca(rca, data)
        r_data = self.try_get_rca(rca)
        # TODO: certain operations might require action for specific errors,
        # so it'd be better to raise an exception that's easier to check.
        if r_data[-1] != 0:
            code = _b.unpack(r_data[-1:])[0]  # r_data[-1] is unsigned; must unpack
            estr = _errors.get(code, "unrecognized error code")
            raise FEMC_RuntimeError("error code from set 0x%08x: %d: %s" % (self.node|rca, code, estr))
        if len(r_data) != len(data) + 1 or r_data[:-1] != data:
            raise FEMC_RuntimeError("bad reply from set 0x%08x: expected 0x%s, got 0x%s" % (self.node|rca, data.hex(), r_data.hex()))
    
    def set_get_rca(self, rca, data):
        '''Call try_set_get_rca in a loop since sometimes the FEMC ignores us.
           TODO: Custom exception type, bail on error codes.'''
        loop = 0
        loops = 10
        while loop < loops:
            if loop:
                self.log.debug('set_get_rca retry %s', loop)
            try:
                self.try_set_get_rca(rca, data)
                return
            except FEMC_RuntimeError as e:
                self.log.debug('set_get_rca %s', e)
                loop += 1
                if loop >= loops or str(e).startswith('error code'):
                    raise
    
    # NOTE: The functions below could automatically infer data types,
    # but explicit typing might help catch some obscure errors.
    
    def set_standard_ubyte(self, rca_offset, value):
        '''Send a STANDARD control command, base 0x10000, with ubyte value.'''
        self.set_get_rca(0x10000 | rca_offset, _B.pack(value))
    
    def set_standard_ushort(self, rca_offset, value):
        '''Send a STANDARD control command, base 0x10000, with ushort value.'''
        self.set_get_rca(0x10000 | rca_offset, _H.pack(value))
    
    def set_standard_float(self, rca_offset, value):
        '''Send a STANDARD control command, base 0x10000, with float value.'''
        self.set_get_rca(0x10000 | rca_offset, _f.pack(value))
    
    def get_standard_ubyte(self, rca_offset):
        '''Send a STANDARD monitor command, base 0x00000; return ubyte value.'''
        d = self.get_rca(0x00000 | rca_offset)
        if d[-1] != 0:
            e = _b.unpack(d[-1:])[0]  # d[-1] is unsigned; must unpack
            estr = _errors.get(e, "unrecognized error code")
            raise FEMC_RuntimeError("error code from get 0x%08x: %d: %s" % (self.node|rca_offset, e, estr))
        if len(d) != 2:
            raise FEMC_RuntimeError("reply len from get 0x%08x not 2: 0x%s" % (self.node|rca_offset, d.hex()))
        return _B.unpack(d[:-1])[0]
    
    def get_standard_ushort(self, rca_offset):
        '''Send a STANDARD monitor command, base 0x00000; return ushort value.'''
        d = self.get_rca(0x00000 | rca_offset)
        if d[-1] != 0:
            e = _b.unpack(d[-1:])[0]  # d[-1] is unsigned; must unpack
            estr = _errors.get(e, "unrecognized error code")
            raise FEMC_RuntimeError("error code from get 0x%08x: %d: %s" % (self.node|rca_offset, e, estr))
        if len(d) != 3:
            raise FEMC_RuntimeError("reply len from get 0x%08x not 3: 0x%s" % (self.node|rca_offset, d.hex()))
        return _H.unpack(d[:-1])[0]
    
    def get_standard_float(self, rca_offset):
        '''Send a STANDARD monitor command, base 0x00000; return float value.'''
        d = self.get_rca(0x00000 | rca_offset)
        if d[-1] != 0:
            e = _b.unpack(d[-1:])[0]  # d[-1] is unsigned; must unpack
            estr = _errors.get(e, "unrecognized error code")
            raise FEMC_RuntimeError("error code from get 0x%08x: %d: %s" % (self.node|rca_offset, e, estr))
        if len(d) != 5:
            raise FEMC_RuntimeError("reply len from get 0x%08x not 5: 0x%s" % (self.node|rca_offset, d.hex()))
        return _f.unpack(d[:-1])[0]
    
    ########### special SET commands ###########
    
    def set_exit_program(self):
        '''Debug only, causes ARCOM board to "gracefully" halt program.'''
        self.set_special(0x00)
    
    def set_reboot(self):
        '''Debug only, causes reboot of the ARCOM board.'''
        self.set_special(0x01)
    
    def set_console_enable(self, enable):
        '''Sets state of FEMC console, enabled by default at startup.
           Allows for debug operation; adds about 50us to CAN comm times.'''
        arg = 0
        if enable:
            arg = 1
        self.set_special(0x09, arg)
    
    def set_fe_mode(self, mode, do_publish=True):
        '''Set FEMC operating mode.
             0: Operational
             1: Troubleshooting: no software interlocks in place, trained staff only.
             2: Maintenance: only the special RCA is available.'''
        if mode < 0 or mode > 2:
            raise FEMC_ValueError("mode %s not in [0,2] range" % (repr(mode)))
        self.set_special(0x0e, mode)
        self.fe_mode = mode
        self.state['fe_mode'] = mode
        if do_publish:
            self.update()
    
    def set_read_esn(self):
        '''Search the ESNs available on the One Wire Bus.  This process is
           identical to the one run at startup and will update all affected
           variables and files.  Takes 1~2s, during which FEMC will be unresponsive.'''
        self.set_special(0x0f)
    
    ########### special GET commands ###########
    
    def get_ambsi1_version_info(self):
        '''Return the version information for the AMBSI1 firmware.
           NOTE the actual size of the tuple returned may differ from docs.'''
        return self.get_special(0x00)
    
    def get_setup_info(self):
        '''Causes the AMBSI1 to query the ARCOM board for lowest/highest RCAs.
           The AMBSI1 then tries to register the functions associated with the RCAs.
           This monitor request has to be issued before any other monitor or control
           request, otherwise there will be no function register apart from the
           intrinsic AMBSI1 RCAs starting at 0x30000.  Note that this class calls
           this function in __init__(), so you shouldn't have to.  Returns:
             0: no error, comms established
             1: error registering special monitor functions
             2: error registering special control functions
             3: error registering monitor functions
             4: error registering control functions
             5: warning, this function has already been called
             6: AMBSI1-ARCOM communication not yet established
             7: timeout while forwaring CAN message to ARCOM board
             8: the FEMC is booting up; wait until ready'''
        return self.get_special(0x01)[0]
    
    def get_version_info(self):
        '''Returns the version info for the ARCOM Pegasus firmware.'
           NOTE the actual size of the tuple returned may differ from docs.'''
        return self.get_special(0x02)
    
    def get_special_monitor_rca(self):
        '''Return the RCA range for the special monitor points, (first,last).'''
        return struct.unpack(">II", self.get_special(0x03))
    
    def get_special_control_rca(self):
        '''Return the RCA range for the special control points, (first,last).'''
        return struct.unpack(">II", self.get_special(0x04))
    
    def get_monitor_rca(self):
        '''Return the RCA range for the standard monitor points, (first,last).'''
        return struct.unpack(">II", self.get_special(0x05))
    
    def get_control_rca(self):
        '''Return the RCA range for the special control points, (first,last).'''
        return struct.unpack(">II", self.get_special(0x06))
    
    def get_ppcomm_time(self):
        '''Debug only; gets a message payload of 8 0xff bytes.
           This gives an estimate of the longest time necessary to respond to the
           largest monitor request without performing any operation; it is a
           measure of the longest comm time between ARCOM and AMSI1 boards.
           This function checks the payload and returns the elapsed time
           in seconds, but it probably won't be very accurate.'''
        t0 = time.time()
        payload = self.get_special(0x07)
        t1 = time.time()
        # RMB 20211207: Skip payload check for GLT, reply does not match spec
        #if payload != b'\xff\xff\xff\xff\xff\xff\xff\xff':
        #    raise FEMC_RuntimeError('bad payload, expected 8x 0xff, received 0x%s' % (payload.hex()))
        return t1-t0
    
    def get_fpga_version_info(self):
        '''Returns FPGA code version info.
           NOTE the actual size of the tuple returned may differ from docs.'''
        return self.get_special(0x08)
    
    def get_console_enable(self):
        '''Returns current state of FEMC console.  The console is enabled
           by default on startup, and adds ~50us to CAN comm time.
             0: console disabled
             1: console enabled'''
        return self.get_special(0x09)[0]
    
    def get_esns(self):
        '''Return a list of electronic serial numbers found.
           Any errors usually indicate that another client is
           trying to get the ESN list at the same time we are.'''
        n = self.get_special(0x0a)[0]
        esns = []
        while len(esns) < n:
            esn = self.get_special(0x0b)
            if esn == b'\x00'*8 or esn == b'\xff'*8:
                raise FEMC_RuntimeError('expected %d esns, but only found %d: %s' % (n, len(esns), esns))
            esns.append(esn)
        esn = self.get_special(0x0b)
        if esn != b'\x00'*8 and esn != b'\xff'*8:
            esns.append(esn)
            raise FEMC_RuntimeError('extra esn found: %s' % (esns))
        if len(set(esns)) != n:
            raise FEMC_RuntimeError('duplicate esns found: %s' % (esns))
        return esns
    
    def retry_esns(self, tries, sleep_seconds):
        '''Since concurrence is an issue for get_esns(), retry for the given
           number of tries, sleeping sleep_seconds in between.'''
        for i in range(tries):
            try:
                esns = self.get_esns()
                break
            except FEMC_RuntimeError:
                if (i+1) == tries:
                    raise
                time.sleep(sleep_seconds)
        return esns
        
    
    def get_errors_number(self):
        '''Return number of errors not read in the error buffer.
           Suggested interval: 10s'''
        return struct.unpack(">H", self.get_special(0x0c))[0]
    
    def get_next_error(self):
        '''Return next error available in the buffer as (module, error).
           If no errors to report, each byte will be 0xff.
           Suggested interval: 10s'''
        return struct.unpack("BB", self.get_special(0x0d))
    
    def get_fe_mode(self):
        '''Returns FEMC operating mode.
           In Maintenance mode, only the special RCA is available.
           In Troubleshooting mode, assume none of the software interlock is in place.
           This mode should be used *only* by trained staff.
             0: Operational
             1: Troubleshooting
             2: Maintenance
           Suggested interval: 10s'''
        return self.get_special(0x0e)[0]
    
    ########### cold cartridge electronics (SIS, LNA, DAC) SET commands ###########
    
    def set_sis_voltage(self, ca, po, sb, mv):
        '''Set SIS mixer voltage in mV for cartridge, polarization, sideband.'''
        rca_offset = self.make_rca(cartridge=ca, polarization=po, sideband=sb) | _sis_voltage
        self.set_standard_float(rca_offset, mv)
    
    def set_sis_open_loop(self, ca, po, sb, open_loop):
        '''Set SIS mixer operation mode for cartridge, polarization, sideband.
             0: Close loop (power up state)
             1: Open loop'''
        arg = 0
        if open_loop:
            arg = 1
        rca_offset = self.make_rca(cartridge=ca, polarization=po, sideband=sb) | _sis_open_loop
        self.set_standard_ubyte(rca_offset, arg)

    def set_sis_magnet_current(self, ca, po, sb, ma):
        '''Set SIS magnet current in mA for cartridge, polarization, sideband.'''
        rca_offset = self.make_rca(cartridge=ca, polarization=po, sideband=sb) | _sis_magnet_current
        self.set_standard_float(rca_offset, ma)

    def set_lna_drain_voltage(self, ca, po, sb, st, volts):
        '''Set LNA drain voltage for cartridge, polarization, sideband, stage.'''
        rca_offset = self.make_rca(cartridge=ca, polarization=po, sideband=sb, lna_stage=st) | _lna_drain_voltage
        self.set_standard_float(rca_offset, volts)
    
    def set_lna_drain_current(self, ca, po, sb, st, ma):
        '''Set LNA drain current in mA for cartridge, polarization, sideband, stage.'''
        rca_offset = self.make_rca(cartridge=ca, polarization=po, sideband=sb, lna_stage=st) | _lna_drain_current
        self.set_standard_float(rca_offset, ma)

    def set_lna_enable(self, ca, po, sb, enable):
        '''Set LNA state for cartridge, polarization, sideband.
             0: LNA off (power up state)
             1: LNA on'''
        arg = 0
        if enable:
            arg = 1
        rca_offset = self.make_rca(cartridge=ca, polarization=po, sideband=sb) | _lna_enable
        self.set_standard_ubyte(rca_offset, arg)

    def set_lna_led_enable(self, ca, po, enable):
        '''Set LNA LED status for cartridge, polarization.
             0: LED off (power up state)
             1: LED on'''
        arg = 0
        if enable:
            arg = 1
        rca_offset = self.make_rca(cartridge=ca, polarization=po) | _lna_led_enable
        self.set_standard_ubyte(rca_offset, arg)

    def set_sis_heater_enable(self, ca, po, enable):
        '''Set SIS heater status for cartridge, polarization.
             0: SIS heater off (power up state)
             1: SIS heater on
           Note the following safety feature, implemented in hardware:
           when turned on, the heater will automatically turn off after 1s
           to prevent damage to the SIS mixer.  Before turning on again,
           a 0 must be sent to reset the hardware state.
           To keep the heater on for longer than 1s, follow this procedure:
             1. Turn heater ON
             2. Monitor heater current until negligable (TODO threshold?)
             3. Turn heater OFF
             4. Goto 1
           To prevent this from being accidentally applied to band 9,
           a timer was added to allow the band 9 heater only once every 10s.
           If this timing is violated, this function will raise
           a FEMC_RuntimeError with -3, hardware blocked error.'''
        arg = 0
        if enable:
            arg = 1
        rca_offset = self.make_rca(cartridge=ca, polarization=po) | _sis_heater_enable
        self.set_standard_ubyte(rca_offset, arg)

    def set_dac_reset_strobe(self, ca, po, da):
        '''Send a reset strobe to cartridge, polarization, DAC.  Debug only. ???'''
        rca_offset = self.make_rca(cartridge=ca, polarization=po, dac=da) | _dac_reset_strobe
        self.set_standard_ubyte(rca_offset, 0)
    
    def set_dac_clear_strobe(self, ca, po, da):
        '''Send a clear strobe to cartridge, polarization, DAC.  Debug only. ???'''
        rca_offset = self.make_rca(cartridge=ca, polarization=po, dac=da) | _dac_clear_strobe
        self.set_standard_ubyte(rca_offset, 0)

    ########### cold cartridge electronics (SIS, LNA, DAC) GET commands ###########
    
    def get_sis_voltage(self, ca, po, sb):
        '''Get SIS mixer voltage in mV for cartridge, polarization, sideband.
           Suggested interval: 5s'''
        rca_offset = self.make_rca(cartridge=ca, polarization=po, sideband=sb) | _sis_voltage
        return self.get_standard_float(rca_offset)
    
    def get_sis_voltage_cmd(self, ca, po, sb):
        '''HACK: Get last commanded SIS mixer voltage in mV for cart, pol, sideband.
           Since SIS bias voltage must be ramped, and also has a setting error,
           a function like this is the only way to avoid a jump (and potential
           trapped flux) when taking over an already-running cartridge.'''
        rca_offset = self.make_rca(cartridge=ca, polarization=po, sideband=sb) | _sis_voltage
        rca_offset |= 0x10000  # 'set' mask; luckily 'get' mask is all 0s
        return self.get_standard_float(rca_offset)
    
    def get_sis_current(self, ca, po, sb):
        '''Get SIS mixer current in mA for cartridge, polarization, sideband.
           Suggested interval: 5s'''
        rca_offset = self.make_rca(cartridge=ca, polarization=po, sideband=sb) | _sis_current
        return self.get_standard_float(rca_offset)
    
    def get_sis_open_loop(self, ca, po, sb):
        '''Get SIS mixer operation mode for cartridge, polarization, sideband.
             0: Close loop (power up state)
             1: Open loop
           This is not a hardware readback; returns last commanded value.'''
        rca_offset = self.make_rca(cartridge=ca, polarization=po, sideband=sb) | _sis_open_loop
        return self.get_standard_ubyte(rca_offset)
    
    def get_sis_magnet_voltage(self, ca, po, sb):
        '''Get SIS magnet voltage for cartridge, polarization, sideband.
           Suggested interval: 5s'''
        rca_offset = self.make_rca(cartridge=ca, polarization=po, sideband=sb) | _sis_magnet_voltage
        return self.get_standard_float(rca_offset)
    
    def get_sis_magnet_current(self, ca, po, sb):
        '''Get SIS magnet current in mA for cartridge, polarization, sideband.
           Suggested interval: 5s'''
        rca_offset = self.make_rca(cartridge=ca, polarization=po, sideband=sb) | _sis_magnet_current
        return self.get_standard_float(rca_offset)

    def get_lna_drain_voltage(self, ca, po, sb, st):
        '''Get drain voltage for cartridge, polarization, sideband, stage.
           Suggested interval: 5s'''
        rca_offset = self.make_rca(cartridge=ca, polarization=po, sideband=sb, lna_stage=st) | _lna_drain_voltage
        return self.get_standard_float(rca_offset)
    
    def get_lna_drain_current(self, ca, po, sb, st):
        '''Get drain current in mA for cartridge, polarization, sideband, stage.
           Suggested interval: 5s'''
        rca_offset = self.make_rca(cartridge=ca, polarization=po, sideband=sb, lna_stage=st) | _lna_drain_current
        return self.get_standard_float(rca_offset)
    
    def get_lna_gate_voltage(self, ca, po, sb, st):
        '''Get gate voltage for cartridge, polarization, sideband, stage.
           Suggested interval: 5s'''
        rca_offset = self.make_rca(cartridge=ca, polarization=po, sideband=sb, lna_stage=st) | _lna_gate_voltage
        return self.get_standard_float(rca_offset)

    def get_lna_enable(self, ca, po, sb):
        '''Get LNA enabled status for cartridge, polarization, sideband.
             0: LNA off (power up state)
             1: LNA on
           This is not a hardware readback; returns last commanded value.'''
        rca_offset = self.make_rca(cartridge=ca, polarization=po, sideband=sb) | _lna_enable
        return self.get_standard_ubyte(rca_offset)

    def get_lna_led_enable(self, ca, po, sb):
        '''Get LNA LED enabled status for cartridge, polarization, sideband.
             0: LED off (power up state)
             1: LED on
           This is not a hardware readback; returns last commanded value.'''
        rca_offset = self.make_rca(cartridge=ca, polarization=po, sideband=sb) | _lna_led_enable
        return self.get_standard_ubyte(rca_offset)

    def get_sis_heater_current(self, ca, po):
        '''Get SIS heater current in mA for cartridge, polarization.
           NOTE: When heater is off, monitor will still report some small amount
                 of current, even if no current is actually flowing to heater (TBD).
           Suggested interval: 0.2s when heater enabled.'''
        rca_offset = self.make_rca(cartridge=ca, polarization=po) | _sis_heater_current
        return self.get_standard_float(rca_offset)
    
    ########### warm cartridge assembly (LO) SET commands ###########
    
    def set_cartridge_lo_yto_coarse_tune(self, ca, counts):
        '''Set cartridge ca YIG tunable oscillator coarse tuning to counts [0,4095].'''
        rca_offset = self.make_rca(cartridge=ca) | _lo_yto_coarse_tune
        self.set_standard_ushort(rca_offset, counts)
    
    def set_cartridge_lo_photomixer_enable(self, ca, enable):
        '''Enable (1) or disable (0) the LO photomixer in cartridge ca.'''
        rca_offset = self.make_rca(cartridge=ca) | _lo_photomixer_enable
        arg = 0
        if enable:
            arg = 1
        self.set_standard_ubyte(rca_offset, arg)
    
    def set_cartridge_lo_pll_clear_unlock_detect_latch(self, ca):
        '''Clear the unlock detect latch bit for cartridge ca.'''
        rca_offset = self.make_rca(cartridge=ca) | _lo_pll_clear_unlock_detect_latch
        self.set_standard_ubyte(rca_offset, 1)
    
    def set_cartridge_lo_pll_loop_bandwidth_select(self, ca, bandwidth):
        '''Set the PLL loop bandwidth for cartridge ca.
           This is normally set automatically when the corresponding band
           is turned on and initialized.  Bandwidth options:
             0:  7.5 MHz/V
             1: 15.0 MHz/V'''
        if bandwidth < 0 or bandwidth > 1:
            raise FEMC_ValueError("bandwidth %s not in [0,1] range" % (repr(bandwidth)))
        rca_offset = self.make_rca(cartridge=ca) | _lo_pll_loop_bandwidth_select
        self.set_standard_ubyte(rca_offset, bandwidth)
    
    def set_cartridge_lo_pll_sb_lock_polarity_select(self, ca, polarity):
        '''Set the PLL sideband lock polarity to lock below or above
           the input reference frequency, i.e. at -31.5MHz or +31.5MHz.
             0: Lock below reference (LSB)
             1: Lock above reference (USB)'''
        if polarity < 0 or polarity > 1:
            raise FEMC_ValueError("polarity %s not in [0,1] range" % (repr(polarity)))
        rca_offset = self.make_rca(cartridge=ca) | _lo_pll_sb_lock_polarity_select
        self.set_standard_ubyte(rca_offset, polarity)
    
    def set_cartridge_lo_pll_null_loop_integrator(self, ca, status):
        '''Set the state of the select bit for loop integrator operation.
           0: Operate (disables the zeroing for normal PLL operation)
           1: Null/Zero (enables the zeroing and dumps the integrator)'''
        arg = 0
        if status:
            arg = 1
        rca_offset = self.make_rca(cartridge=ca) | _lo_pll_null_loop_integrator
        self.set_standard_ubyte(rca_offset, arg)

    def set_cartridge_lo_amc_gate_a_voltage(self, ca, volts):
        '''Set AMC gate A voltage.'''
        rca_offset = self.make_rca(cartridge=ca) | _lo_amc_gate_a_voltage
        self.set_standard_float(rca_offset, volts)

    def set_cartridge_lo_amc_drain_a_voltage(self, ca, volts):
        '''Set AMC drain A voltage.'''
        rca_offset = self.make_rca(cartridge=ca) | _lo_amc_drain_a_voltage
        self.set_standard_float(rca_offset, volts)

    def set_cartridge_lo_amc_gate_b_voltage(self, ca, volts):
        '''Set AMC gate B voltage.'''
        rca_offset = self.make_rca(cartridge=ca) | _lo_amc_gate_b_voltage
        self.set_standard_float(rca_offset, volts)
        
    def set_cartridge_lo_amc_drain_b_voltage(self, ca, volts):
        '''Set AMC drain B voltage.'''
        rca_offset = self.make_rca(cartridge=ca) | _lo_amc_drain_b_voltage
        self.set_standard_float(rca_offset, volts)
    
    def set_cartridge_lo_amc_multiplier_d_voltage_counts(self, ca, counts):
        '''Set AMC multiplier voltage in counts [0,255]
           that are proportional to the actual voltage.'''
        rca_offset = self.make_rca(cartridge=ca) | _lo_amc_multiplier_d_voltage
        self.set_standard_ubyte(rca_offset, counts)
    
    def set_cartridge_lo_amc_gate_e_voltage(self, ca, volts):
        '''Set AMC gate E voltage.'''
        rca_offset = self.make_rca(cartridge=ca) | _lo_amc_gate_e_voltage
        self.set_standard_float(rca_offset, volts)
    
    def set_cartridge_lo_amc_drain_e_voltage(self, ca, volts):
        '''Set AMC drain E voltage.'''
        rca_offset = self.make_rca(cartridge=ca) | _lo_amc_drain_e_voltage
        self.set_standard_float(rca_offset, volts)

    def set_cartridge_lo_pa_pol_gate_voltage(self, ca, po, volts):
        '''Set PA gate voltage for channel po.'''
        rca_offset = self.make_rca(cartridge=ca, pa_channel=po) | _lo_pa_gate_voltage
        self.set_standard_float(rca_offset, volts)
    
    def set_cartridge_lo_pa_pol_drain_voltage_scale(self, ca, po, scale):
        '''Set unitless PA scaling factor; 0 is 0V, 5 is max drain voltage.
           If dewar 4K stage or 12K stage temperature is above 30K,
           the use of the PA is inhibited and the Hardware Blocked Error (-3)
           is raised.  Likewise if 4K/12K temperature values are unavailable.'''
        rca_offset = self.make_rca(cartridge=ca, pa_channel=po) | _lo_pa_drain_voltage
        self.set_standard_float(rca_offset, scale)
        
    ########### warm cartridge assembly (LO) GET commands ###########
    
    def get_cartridge_lo_yto_coarse_tune(self, ca):
        '''Get LO YTO coarse tuning value in counts.
           This is not a hardware readback; returns last commanded value.'''
        rca_offset = self.make_rca(cartridge=ca) | _lo_yto_coarse_tune
        return self.get_standard_ushort(rca_offset)
    
    def get_cartridge_lo_photomixer_enable(self, ca):
        '''Get photomixer enabled status for cartridge.
           This is not a hardware readback; returns last commanded value.'''
        rca_offset = self.make_rca(cartridge=ca) | _lo_photomixer_enable
        return self.get_standard_ubyte(rca_offset)
    
    def get_cartridge_lo_photomixer_voltage(self, ca):
        '''Get LO photomixer voltage for WCA installed in cartridge.
           Suggested interval: 5s'''
        rca_offset = self.make_rca(cartridge=ca) | _lo_photomixer_voltage
        return self.get_standard_float(rca_offset)

    def get_cartridge_lo_photomixer_current(self, ca):
        '''Get LO photomixer current in mA for WCA installed in cartridge.
           Suggested interval: 5s'''
        rca_offset = self.make_rca(cartridge=ca) | _lo_photomixer_current
        return self.get_standard_float(rca_offset)

    def get_cartridge_lo_pll_lock_detect_voltage(self, ca):
        '''The PLL is considered locked if this voltage is >3V.
           Suggested interval: 5s'''
        rca_offset = self.make_rca(cartridge=ca) | _lo_pll_lock_detect_voltage
        return self.get_standard_float(rca_offset)
    
    def get_cartridge_lo_pll_correction_voltage(self, ca):
        '''Get PLL correction voltage for given cartridge.
           Suggested interval: 5s'''
        rca_offset = self.make_rca(cartridge=ca) | _lo_pll_correction_voltage
        return self.get_standard_float(rca_offset)
    
    def get_cartridge_lo_pll_assembly_temp(self, ca):
        '''Get the PLL assembly temperature in C.
           Suggested interval: 30s'''
        rca_offset = self.make_rca(cartridge=ca) | _lo_pll_assembly_temp
        return self.get_standard_float(rca_offset)

    def get_cartridge_lo_yig_heater_current(self, ca):
        '''Get the YIG heater current for cartridge.
           Suggested interval: 30s'''
        rca_offset = self.make_rca(cartridge=ca) | _lo_pll_yig_heater_current
        return self.get_standard_float(rca_offset)
    
    def get_cartridge_lo_pll_ref_total_power(self, ca):
        '''Get PLL reference total power in volts.
           This voltage gives an indication of the power level
           of the FLOOG signal when the PLL is locked.
           Suggested interval: 1s when searching for LO lock, 30s otherwise.'''
        rca_offset = self.make_rca(cartridge=ca) | _lo_pll_ref_total_power
        return self.get_standard_float(rca_offset)
    
    def get_cartridge_lo_pll_if_total_power(self, ca):
        '''Get PLL IF total power in volts.
           This voltage gives an indication of the power level
           of the photomixer output when the PLL is locked.
           Suggested interval: 1s when searching for LO lock, 30s otherwise.'''
        rca_offset = self.make_rca(cartridge=ca) | _lo_pll_if_total_power
        return self.get_standard_float(rca_offset)
    
    # NOTE 0x26 is unused
    
    def get_cartridge_lo_pll_unlock_detect_latch(self, ca):
        '''Get the state of the latched unlock detect bit.
           Indicates that the LO lock is lost or has been lost since the last
           set_cartridge_lo_pll_clear_unlock_detect_latch command.
             0: PLL lock okay
             1: PLL unlock detected
           Suggested interval: 5s'''
        rca_offset = self.make_rca(cartridge=ca) | _lo_pll_unlock_detect_latch
        return self.get_standard_ubyte(rca_offset)
    
    def get_cartridge_lo_pll_loop_bandwidth_select(self, ca):
        '''Get state of selection bit for bandwidth.
             0:  7.5 MHz/V (Band 4,8,9)
             1: 15.0 MHz/V (Band 3,6,7)
           This is not a hardware readback; returns last commanded value.'''
        rca_offset = self.make_rca(cartridge=ca) | _lo_pll_loop_bandwidth_select
        return self.get_standard_ubyte(rca_offset)
    
    def get_cartridge_lo_pll_sb_lock_polarity_select(self, ca):
        '''Get state of select bit for the sideband polarity.
             0: Lock below reference (LSB)
             1: Lock above reference (USB)
           This is not a hardware readback; returns last commanded value.'''
        rca_offset = self.make_rca(cartridge=ca) | _lo_pll_sb_lock_polarity_select
        return self.get_standard_ubyte(rca_offset)
    
    def get_cartridge_lo_pll_null_loop_integrator(self, ca):
        '''Get state of select bit for the loop integrator operation.
             0: Disables zeroing, normal PLL operation
             1: Enables zeroing and dumps integrator
           This is not a hardware readback; returns last commanded value.'''
        rca_offset = self.make_rca(cartridge=ca) | _lo_pll_null_loop_integrator
        return self.get_standard_ubyte(rca_offset)
    
    def get_cartridge_lo_amc_gate_a_voltage(self, ca):
        '''Get the AMC gate A voltage for given cartridge.
           Note that while it is possible to read back the bias voltage
           and currents *produced* by these pots, it is not possible to read
           back the *actual setting* of the pots.
           Suggested interval: 30s'''
        rca_offset = self.make_rca(cartridge=ca) | _lo_amc_gate_a_voltage
        return self.get_standard_float(rca_offset)
    
    def get_cartridge_lo_amc_drain_a_voltage(self, ca):
        '''Get the AMC drain A voltage for given cartridge.
           Note that while it is possible to read back the bias voltage
           and currents *produced* by these pots, it is not possible to read
           back the *actual setting* of the pots.
           Suggested interval: 30s'''
        rca_offset = self.make_rca(cartridge=ca) | _lo_amc_drain_a_voltage
        return self.get_standard_float(rca_offset)
    
    def get_cartridge_lo_amc_drain_a_current(self, ca):
        '''Get the AMC drain A current in mA for given cartridge.
           Suggested interval: 30s'''
        rca_offset = self.make_rca(cartridge=ca) | _lo_amc_drain_a_current
        return self.get_standard_float(rca_offset)

    def get_cartridge_lo_amc_gate_b_voltage(self, ca):
        '''Get the AMC gate B voltage for given cartridge.
           Note that while it is possible to read back the bias voltage
           and currents *produced* by these pots, it is not possible to read
           back the *actual setting* of the pots.
           Suggested interval: 30s'''
        rca_offset = self.make_rca(cartridge=ca) | _lo_amc_gate_b_voltage
        return self.get_standard_float(rca_offset)
    
    def get_cartridge_lo_amc_drain_b_voltage(self, ca):
        '''Get the AMC drain B voltage for given cartridge.
           Note that while it is possible to read back the bias voltage
           and currents *produced* by these pots, it is not possible to read
           back the *actual setting* of the pots.
           Suggested interval: 30s'''
        rca_offset = self.make_rca(cartridge=ca) | _lo_amc_drain_b_voltage
        return self.get_standard_float(rca_offset)
    
    def get_cartridge_lo_amc_drain_b_current(self, ca):
        '''Get the AMC drain B current in mA for the given cartridge.
           Suggested interval: 30s'''
        rca_offset = self.make_rca(cartridge=ca) | _lo_amc_drain_b_current
        return self.get_standard_float(rca_offset)

    def get_cartridge_lo_amc_multiplier_d_voltage_counts(self, ca):
        '''Get the AMC multiplier D voltage in counts.
           This is not a hardware readback; returns last commanded value.'''
        rca_offset = self.make_rca(cartridge=ca) | _lo_amc_multiplier_d_voltage
        return self.get_standard_ubyte(rca_offset)
    
    def get_cartridge_lo_amc_gate_e_voltage(self, ca):
        '''Get the AMC gate E voltage for given cartridge.
           Note that while it is possible to read back the bias voltage
           and currents *produced* by these pots, it is not possible to read
           back the *actual setting* of the pots.
           Suggested interval: 30s'''
        rca_offset = self.make_rca(cartridge=ca) | _lo_amc_gate_e_voltage
        return self.get_standard_float(rca_offset)
    
    def get_cartridge_lo_amc_drain_e_voltage(self, ca):
        '''Get the AMC drain E voltage for given cartridge.
           Note that while it is possible to read back the bias voltage
           and currents *produced* by these pots, it is not possible to read
           back the *actual setting* of the pots.
           Suggested interval: 30s'''
        rca_offset = self.make_rca(cartridge=ca) | _lo_amc_drain_e_voltage
        return self.get_standard_float(rca_offset)
    
    def get_cartridge_lo_amc_drain_e_current(self, ca):
        '''Get the AMC drain E current in mA for the given cartridge.
           Suggested interval: 30s'''
        rca_offset = self.make_rca(cartridge=ca) | _lo_amc_drain_e_current
        return self.get_standard_float(rca_offset)
    
    def get_cartridge_lo_amc_multiplier_d_current(self, ca):
        '''Get the AMC multiplier D current in mA for the given cartridge.
           Suggested interval: 30s'''
        rca_offset = self.make_rca(cartridge=ca) | _lo_amc_multiplier_d_current
        return self.get_standard_float(rca_offset)
    
    def get_cartridge_lo_amc_supply_voltage_5v(self, ca):
        '''Get the AMC or PA 5V supply voltage for cartridge.
           Suggested interval: 30s'''
        rca_offset = self.make_rca(cartridge=ca) | _lo_amc_supply_voltage_5v
        return self.get_standard_float(rca_offset)

    def get_cartridge_lo_pa_gate_voltage(self, ca, po):
        '''Get the PA gate voltage for given polarization.
           Note that while it is possible to read back the bias voltage
           and currents *produced* by these pots, it is not possible to read
           back the *actual setting* of the pots.  The gate voltage is
           automatically set to 0V on WCA initialization that is performed
           every time the corresponding band is powered up.
           Suggested interval: 5s'''
        rca_offset = self.make_rca(cartridge=ca, pa_channel=po) | _lo_pa_gate_voltage
        return self.get_standard_float(rca_offset)
    
    def get_cartridge_lo_pa_drain_voltage(self, ca, po):
        '''Get the PA drain voltage for given polarization.
           Note that while it is possible to read back the bias voltage
           and currents *produced* by these pots, it is not possible to read
           back the *actual setting* of the pots.  The drain voltage is
           automatically set to 0V on WCA initialization that is performed
           every time the corresponding band is powered up.
           Suggested interval: 5s'''
        rca_offset = self.make_rca(cartridge=ca, pa_channel=po) | _lo_pa_drain_voltage
        return self.get_standard_float(rca_offset)
    
    def get_cartridge_lo_pa_drain_current(self, ca, po):
        '''Get the PA drain current in mA for given polarization.
           Suggested interval: 5s'''
        rca_offset = self.make_rca(cartridge=ca, pa_channel=po) | _lo_pa_drain_current
        return self.get_standard_float(rca_offset)
    
    def get_cartridge_lo_pa_supply_voltage_3v(self, ca):
        '''Get the AMC/PA 3V supply voltage.
           Suggested interval: 30s'''
        rca_offset = self.make_rca(cartridge=ca) | _lo_pa_supply_voltage_3v
        return self.get_standard_float(rca_offset)
    
    def get_cartridge_lo_pa_supply_voltage_5v(self, ca):
        '''Get the AMC/PA 5V supply voltage.
           Suggested interval: 30s'''
        rca_offset = self.make_rca(cartridge=ca) | _lo_pa_supply_voltage_5v
        return self.get_standard_float(rca_offset)
    
    def get_cartridge_lo_cartridge_temp(self, ca, te):
        '''Get temperature in K for given sensor:
             0: 4K stage
             1: 110K stage
             2: Mixer pol0
             3: Spare
             4: 15K stage
             5: Mixer pol1
           Suggested interval: 30s
           NOTE: Probably not available if using WCA only.'''
        rca_offset = self.make_rca(cartridge=ca, cartridge_temp=te) | _lo_cartridge_temp
        return self.get_standard_float(rca_offset)

    ########### power distribution SET commands ###########
    
    def set_pd_enable(self, ca, enable):
        '''Set power for cartridge.
           If the frontend is in operational or maintenance mode, only 3 bands
           can be powered at once.  If more are attempted, this function will
           raise a FEMC_RuntimeError with -3, hardware blocked.
           In troubleshooting mode any number of bands can be turned on.
           Power up initialization (in any mode) takes 5ms to complete.
           During that time, the FEMC will be unresponsive.
             0: Power off (power up state)
             1: Power on
           Note: if a major error occurred during initialization of the cartridge,
           the status byte for monitor requests will be set to -7, hardware error.
           The only allowed action will be to power off the selected module.'''
        arg = 0
        if enable:
            arg = 1
        rca_offset = self.make_rca(pd_module=ca) | _pd_enable
        self.set_standard_ubyte(rca_offset, arg)
    
    ########### power distribution GET commands ###########

    def get_pd_current(self, ca, ch):
        '''Get power supply current output in Amps for cartridge, channel.  Channels:
             0:  +6V
             1:  -6V
             2: +15V
             3: -15V
             4: +24V
             5:  +8V
           Suggested interval: 30s'''
        rca_offset = self.make_rca(pd_module=ca, pd_channel=ch) | _pd_current
        return self.get_standard_float(rca_offset)
    
    def get_pd_voltage(self, ca, ch):
        '''Get power supply voltage output for cartridge, channel.  Channels:
             0:  +6V
             1:  -6V
             2: +15V
             3: -15V
             4: +24V
             5:  +8V
           Suggested interval: 30s'''
        rca_offset = self.make_rca(pd_module=ca, pd_channel=ch) | _pd_voltage
        return self.get_standard_float(rca_offset)
    
    def get_pd_enable(self, ca):
        '''Get power supply state for cartridge.
           This is not a hardware readback; returns last commanded value.
             0: Power off (power up state)
             1: Power on
           Note: if a major error occurred during initialization of the cartridge,
           this function will raise FEMC_RuntimeError -7, hardware error.
           The only allowed action will be to power off the selected module.'''
        rca_offset = self.make_rca(pd_module=ca) | _pd_enable
        return self.get_standard_ubyte(rca_offset)
    
    def get_pd_powered_modules(self):
        '''Get the current number of powered-up modules.
        This is not a hardware readback; returns last commanded value.'''
        return self.get_standard_ubyte(_pd_powered_modules)

    ########### cryostat SET commands ###########
    
    def set_cryostat_backing_pump_enable(self, enable):
        '''Enable power to the backing pump.
             0: Power off (power up state)
             1: Power on'''
        arg = 0
        if enable:
            arg = 1
        self.set_standard_ubyte(_cryostat_backing_pump_enable, arg)
    
    def set_cryostat_turbo_pump_enable(self, enable):
        '''Enable power to the turbo pump.
             0: Power off (power up state)
             1: Power on
           If the backing pump is not enabled, this function raises
           a FEMC_RuntimeError -3 hardware blocked.  Likewise if the FETIM
           is installed and turbo pump temperature is outside [15C, 45C].'''
        arg = 0
        if enable:
            arg = 1
        self.set_standard_ubyte(_cryostat_turbo_pump_enable, arg)
    
    def set_cryostat_gate_valve_state(self, state):
        '''Open or close the gate valve.
             0: Close (power up state)
             1: Open
           If the backing pump is not enabled, this function raises
           a FEMC_RuntimeError -3 hardware blocked.  Likewise if the gate valve
           is still moving from the last set_cryostat_gate_valve_state().'''
        # maybe this should be a range check instead of allowing booleans
        arg = 0
        if state:
            arg = 1
        self.set_standard_ubyte(_cryostat_gate_valve_state, arg)
    
    def set_cryostat_solenoid_valve_state(self, state):
        '''Open or close the solenoid valve.
             0: Close (power up state)
             1: Open
           If the backing pump is not enabled, this function raises
           a FEMC_RuntimeError -3 hardware blocked.'''
        # maybe this should be a range check instead of allowing booleans
        arg = 0
        if state:
            arg = 1
        self.set_standard_ubyte(_cryostat_solenoid_valve_state, arg)
    
    def set_cryostat_vacuum_gauge_enable(self, enable):
        '''Enable power to the vacuum gauge.
             0: Power off
             1: Power on (power up state)'''
        arg = 0
        if enable:
            arg = 1
        self.set_standard_ubyte(_cryostat_vacuum_controller_enable, arg)
        
    ########### cryostat GET commands ###########
    
    def get_cryostat_temp(self, se):
        '''Get the dewar temperature in K for given sensor.
             0: 4K cryocooler
             1: 4K plate near link1
             2: 4K plate near link2
             3: 4K plate far side1
             4: 4K plate far side2
             5: 15K cryocooler
             6: 15K plate near link
             7: 15K plate far side
             8: 15K shield top
             9:  110K cryocooler
             10: 110K plate near link
             11: 110K plate far side
             12: 110K shield top
           Raises FEMC_RuntimeError -3 hardware blocked if the asynchronous
           readout is disabled.  The state of the asynchronous readout
           can be toggled using the console.
           Suggested interval: 30s'''
        rca_offset = self.make_rca(cryostat_temp=se) | _cryostat_temp
        return self.get_standard_float(rca_offset)
    
    def get_cryostat_backing_pump_enable(self):
        '''Get current state of the backing pump.
             0: Power off (power up state)
             1: Power on
           This is not a hardware readback; returns last commanded value.'''
        return self.get_standard_ubyte(_cryostat_backing_pump_enable)
    
    def get_cryostat_turbo_pump_enable(self):
        '''Get current state of the turbo pump.
             0: Power off (power up state)
             1: Power on
           Raises FEMC_RuntimeError -3 hardware blocked if the backing pump is not enabled.
           This is not a hardware readback; returns last commanded value.'''
        return self.get_standard_ubyte(_cryostat_turbo_pump_enable)

    def get_cryostat_turbo_pump_state(self):
        '''Get current error state for the turbo pump.
             0: OK
             1: Error
           Raises FEMC_RuntimeError -3 hardware blocked if the backing pump is not enabled.
           Suggested interval: 5s when backing pump is enabled, otherwise none.'''
        return self.get_standard_ubyte(_cryostat_turbo_pump_state)
    
    def get_cryostat_turbo_pump_speed(self):
        '''Get current speed state for the turbo pump.
             0: Speed low
             1: Speed OK
           Raises FEMC_RuntimeError -3 hardware blocked if the backing pump is not enabled.
           Suggested interval: 5s when backing pump is enabled, otherwise none.'''
        return self.get_standard_ubyte(_cryostat_turbo_pump_speed)
    
    def get_cryostat_gate_valve_state(self):
        '''Get current state for the gate valve.
             0: Closed
             1: Open
             2: Unknown (moving between states)
             3: Error
             4: Over Current
           If Over Current is returned, the gate valve is probably stuck.
           Refer to AD7 (TODO) for troubleshooting procedure.
           FEND-40.00.00.00-173-A-MAN, Front End Operation Manual.
           Suggested interval: 5s'''
        return self.get_standard_ubyte(_cryostat_gate_valve_state)
    
    def get_cryostat_solenoid_valve_state(self):
        '''Get current state for the solenoid valve.
             0: Closed
             1: Open
             2: Unknown (moving between states)
             3: Error
           Raises FEMC_RuntimeError -3 hardware blocked if the backing pump is not enabled.
           Suggested interval: 5s when backing pump is enabled, otherwise none.'''
        return self.get_standard_ubyte(_cryostat_solenoid_valve_state)
    
    def get_cryostat_vacuum_gauge_pressure(self, ps):
        '''Get the cryostat and vacuum port pressure in mbar.
            0: Cryostat
            1: Vacuum port
           Raises FEMC_RuntimeError -3 hardware blocked if the asynchronous
           readout is disabled.  The state of the asynchronous readout
           can be toggled using the console.
           Suggested interval: 30s for cryostat
                               30s for vacuum port when solenoid valve is open'''
        rca_offset = self.make_rca(vacuum_sensor=ps) | _cryostat_vacuum_controller_pressure
        return self.get_standard_float(rca_offset)
    
    def get_cryostat_vacuum_gauge_enable(self):
        '''Get the current enable state for the vacuum controller.
           TODO: docs wrong for this function? Test.
            0: Off
            1: On (power up state)'''
        return self.get_standard_ubyte(_cryostat_vacuum_controller_enable)
    
    def get_cryostat_vacuum_gauge_state(self):
        '''Get current error state for the vacuum controller.
             0: OK
             1: Error
           Suggested interval: 30s'''
        return self.get_standard_ubyte(_cryostat_vacuum_controller_state)
    
    def get_cryostat_supply_current_230v(self):
        '''Get the 230V AC current level in amps.
           Raises FEMC_RuntimeError -3 hardware blocked if the backing pump is not enabled,
           or if the asynchronous readout is disabled (toggle using console).
           Suggested interval: 5s when backing pump enabled, else none.'''
        return self.get_standard_float(_cryostat_supply_current_230v)

    ########### LO photonics receiver SET commands ###########
    
    # TODO: background info on LO photonics receiver.
    # what is it for, what does it do.  component descriptions:
    # temperature sensors
    # optical switch
    # erbium-doped fiber amplifer
    
    def set_lpr_opt_switch_port(self, port):
        '''Set the port selected by the LPR optical switch.
           Current mapping: selected cartridge band - 1 (so cartridge 0-9...?)
           Selecting a port will automatically disable the shutter.'''
        # TODO: range check? setting bad port ought to result in error anyway, yes?
        self.set_standard_ubyte(_lpr_opt_switch_port, port)
    
    def set_lpr_opt_switch_shutter(self):
        '''Disable the output from the LPR optical switch.
           After this the readout of the port state should return 0xFF.
           The shutter can only be enabled; to disable the shutter you must
           select a port using set_lpr_opt_switch_port command.
           
           RMB: This terminology is confusing. Enabling the shutter disables the output,
                apparently, so they could have said 'open' and 'close'.
                This function closes the shutter; to open you select a port.'''
        self.set_standard_ubyte(_lpr_opt_switch_shutter, 0)
    
    def set_lpr_opt_switch_force_shutter(self):
        '''Disable output from the LPR optical switch (forced mode).
           The forced mode will ignore the 'busy' state of the optical switch.'''
        self.set_standard_ubyte(_lpr_opt_switch_force_shutter, 0)
    
    def set_lpr_edfa_modulation_input_value(self, volts):
        '''Set the modulation input value for the EDFA.'''
        self.set_standard_float(_lpr_edfa_modulation_input_value, volts)
    
    def set_lpr_edfa_modulation_input_special_dac_reset_strobe(self):
        '''Send a reset strobe to the LPR DAC (debug only).'''
        self.set_standard_ubyte(_lpr_edfa_modulation_input_special_dac_reset_strobe, 0)
    
    ########### LO photonics receiver GET commands ###########
    
    def get_lpr_temp(self, sn):
        '''Get LPR temperature for given sensor [0,1] (TODO where/what are these?)
           Suggested interval: 30s'''
        rca_offset = self.make_rca(lpr_temp=sn) | _lpr_temp
        return self.get_standard_float(rca_offset)

    def get_lpr_opt_switch_port(self):
        '''Get current port selected by optical switch;
           a readout of 0xff means the output is disabled (shuttered).
           This is not a hardware readback; returns last commanded value.'''
        return self.get_standard_ubyte(_lpr_opt_switch_port)
    
    def get_lpr_opt_switch_shutter(self):
        '''Get current state of the shutter in the optical switch.
             0: Shutter off (laser enable)
             1: Shutter on (laser disable)(startup state)
           This is not a hardware readback; returns last commanded value.'''
        return self.get_standard_ubyte(_lpr_opt_switch_shutter)
    
    def get_lpr_opt_switch_state(self):
        '''Get current error state for the optical switch in the LPR.
             0: OK
             1: Error
           Suggested interval: 5s'''
        return self.get_standard_ubyte(_lpr_opt_switch_state)
    
    def get_lpr_opt_switch_busy(self):
        '''Get the current busy state for the optical switch in the LPR.
             0: Idle
             1: Switching
           Suggested interval: 5s'''
        return self.get_standard_ubyte(_lpr_opt_switch_busy)
    
    def get_lpr_edfa_laser_pump_temp(self):
        '''Get the EDFA temperature in K for the pump.  (???)
           Uses a 6th-order polynomial fit, only valid between 280K and 315K.
           Suggested interval: 30s'''
        return self.get_standard_float(_lpr_edfa_laser_pump_temp)
    
    def get_lpr_edfa_laser_drive_current(self):
        '''Get the EDFA laser drive current in uA.
           Suggested interval: 5s'''
        return self.get_standard_float(_lpr_edfa_laser_drive_current)
    
    def get_lpr_edfa_laser_photo_detect_current(self):
        '''Get the EDFA laser photo detect current in uA.
           This monitor point is only available starting with LPR SN.226.
           This request on previous hardware will return meaningless data.
           Suggested interval: 5s'''
        return self.get_standard_float(_lpr_edfa_laser_photo_detect_current)
    
    def get_lpr_edfa_photo_detector_current(self):
        '''Get the LPR EDFA photo detector current in mA.
           Suggested interval: 5s'''
        return self.get_standard_float(_lpr_edfa_photo_detector_current)
    
    def get_lpr_edfa_photo_detector_power(self):
        '''Get the LPR EDFA photo detector power in mW.
           Suggested interval: 5s'''
        return self.get_standard_float(_lpr_edfa_photo_detector_power)
    
    def get_lpr_edfa_modulation_input_value(self):
        '''Get the LPR EDFA modulation input voltage.
           This is not a hardware readback; returns last commanded value.'''
        return self.get_standard_float(_lpr_edfa_modulation_input_value)
    
    def get_lpr_edfa_driver_temperature_alarm(self):
        '''Get the LPR EDFA laser pump temperature alarm.
           This is triggered when the temperature (which can be monitored with
           get_lpr_edfa_laser_pump_temp) rises above 37-40C.  When this alarm
           is triggered, the optical output power is switched off by the
           LPR hardware.  The firmware will set the modulation input to 0.0
           to prevent on/off oscillation.
             0: OK
             1: Error
           Suggested interval: 30s'''
        return self.get_standard_ubyte(_lpr_edfa_driver_state)

    

def test_threaded_esns(num_threads=10):
    '''
    This test spawns multiple threads, each creating a separate FEMC instance
    (with a separate SocketCAN socket), and attempts to get the ESN list
    from each.  The ESN list is one of the few overlapping RCAs if the
    cartridge monitoring/control is divided up into separate processes.
    
    After making the following changes to the FEMC class,
    this function succeeds even for many (100+) threads:
     - get_rca ignores reads with no data (outgoing 'get' commands)
     - set_rca retries send to account for small transmit queue
     - clear socket buffer before send, vs after recv error
    '''
    import threading
    import traceback
    def threadfunc(thread_number):
        try:
            f = FEMC()
            tries = 10
            for i in range(tries):
                try:
                    esns = f.get_esns()
                    break
                except FEMC_RuntimeError:
                    if i+1 == tries:
                        raise
                    sleep_secs = 0.001*(thread_number)
                    print("thread %d sleeping %gs to try again..." % (thread_number, sleep_secs))
                    time.sleep(sleep_secs)
            print("%d esns: %s" % (thread_number, esns))
        except:
            e = traceback.format_exc()
            print("thread %d: %s" % (thread_number, e), file=sys.stderr)
    print("creating %d threads..." % (num_threads))
    threads = [threading.Thread(target=threadfunc, args=(i,)) for i in range(num_threads)]
    print("starting threads...")
    for t in threads:
        t.start()
    print("joining threads...")
    for t in threads:
        t.join()
    print("test_threaded_esns done.")
    

