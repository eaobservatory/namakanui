'''
namakanui/util/__init__.py   RMB 20200227

This file contains some basic utility functions.


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

import sys
import os
import logging
import time
import namakanui.ini

log = logging.getLogger('util')
log.setLevel(logging.INFO)  # be quiet even if root is DEBUG


def setup_logging(level=logging.INFO):
    '''Perform basic logging setup for scripts.'''
    f = logging.Formatter('%(levelname)s:%(name)s: %(message)s')
    s = logging.StreamHandler()
    s.setFormatter(f)
    logging.root.addHandler(s)
    logging.root.setLevel(level)
    # setup_logging


def get_description(s):
    '''
    Get script description (for -h) from given docstring s.
    Assumes all docstrings start with filename and end with copyright notice.
    '''
    return s[s.find('\n',s.find('.py')):s.find('Copyright')].strip()
    # get_description


def get_paths():
    '''Return binpath and datapath for this script.'''
    if sys.argv[0]:
        binpath = os.path.dirname(os.path.realpath(sys.argv[0])) + '/'
    else:
        binpath = os.path.realpath('') + '/'
    # crawl up parent directories looking for data dir
    #crawl = binpath[:-1]
    modpath = os.path.dirname(__file__)
    crawl = modpath
    while crawl:
        datapath = crawl + '/data/'
        if os.path.exists(datapath):
            break
        crawl = crawl.rpartition('/')[0]
    if not crawl:  # we don't accept /data at root
        raise RuntimeError('no data path found from module path %s'%(modpath))
    return binpath, datapath
    # get_paths


def get_config(filename='instrument.ini'):
    '''Return an IncludeParser instance for given filename.'''
    binpath, datapath = get_paths()
    return namakanui.ini.IncludeParser(datapath + filename)
    # get_config


def get_bands(config, simulated=None, has_sis_mixers=None):
    '''
    Get list of available receiver bands from given config.
    If optional arguments are given (as True/False),
    only return bands that match the requested condition.
    '''
    bands = sorted([int(x) for x in config['bands']])
    if simulated is not None:
        simulated = bool(simulated)
        femc_sim = bool(config['femc']['simulate'].strip())
        for i,b in enumerate(bands):
            band_sim = femc_sim or bool(config[str(b)]['simulate'].strip())
            if band_sim != simulated:
                del bands[i]
    if has_sis_mixers is not None:
        has_sis_mixers = bool(has_sis_mixers)
        for i,b in enumerate(bands):
            cold = config[str(b)]['cold']
            band_sis = 'MixerParam' in config[cold] or ('MixerParams' in config[cold] and int(config[cold]['MixerParams']) != 0)
            if band_sis != has_sis_mixers:
                del bands[i]
    return bands
    # get_bands
    

def parse_range(s, maxlen=0, maxstep=0):
    '''
    Parse string s in "first:last:step" format and return array of values.
    The "last" and "step" are optional:
        "first" -> [first]
        "first:last" -> [first, last]
    If first > last, automatic negative step.
    '''
    s = s.split(':')
    first = float(s[0])
    if len(s) == 1:
        return [first]
    last = float(s[1])
    #if len(s) == 2:
    #    return [first, last]
    diff = last - first
    if diff == 0.0:
        return [first]
    if len(s) == 2:
        step = 0.0
    else:
        step = abs(float(s[2]))
    if step == 0.0 or step > abs(diff):
        step = abs(diff)
    if maxstep and step > maxstep:
        raise ValueError('step %g > maxstep %g'%(step, maxstep))
    if diff < 0.0:
        step = -step
    alen = int(round(diff/step + 1))
    if maxlen and alen > maxlen:
        raise ValueError('step %g too small, array len %d > maxlen %d'%(step,alen,maxlen))
    arr = []
    val = first
    while (step > 0 and val < last) or (step < 0 and val > last):
        arr.append(val)
        val += step
    if abs(arr[-1] - last) < abs(step)*1e-6:
        arr[-1] = last
    else:
        arr.append(last)
    return arr
    # parse_range


def get_dcms(rx):
    '''Given receiver name rx, return array of DCM numbers from cm_wire_file.txt'''
    dcms = []
    for line in open('/jac_sw/hlsroot/acsis_prod/wireDir/acsis/cm_wire_file.txt'):
        line = line.strip()
        if not line:
            continue
        if line.startswith('#'):
            continue
        line = line.split()
        if rx in line:
            dcms.append(int(line[0]))
    return dcms


def clip(value, minimum, maximum):
    '''Return value restricted to [minimum, maximum] range'''
    if value < minimum:
        return minimum
    if value > maximum:
        return maximum
    return value


class interval(object):
    '''Class defining a range of values, used for argparse choices.'''
    def __init__(self, start, end):
        self.start = start
        self.end = end
        self.min = min(start,end)
        self.max = max(start,end)
    def __eq__(self, other):
        return self.min <= other <= self.max
    def __contains__(self, item):
        return self.__eq__(item)
    def __iter__(self):
        yield self
    def __str__(self):
        return f'{self.start:g}:{self.end:g}'
    def __repr__(self):
        return self.__str__()
    


# The following functions are only defined if drama is already imported.
if 'drama' in sys.modules:
    import drama


    def iftask_check_msg(action, msg):
        '''Helper used by iftask_* functions to check obey replies.'''
        if msg.reason != drama.REA_COMPLETE:
            raise drama.BadStatus(drama.UNEXPMSG, f'{action} bad reply: {msg}')
        if msg.status == 261456746:  # ACSISIF__ATTEN_ZERO
            log.warning(f'{action} low attenuator setting')
        elif msg.status != 0:
            raise drama.BadStatus(msg.status, f'{action} bad status')


    def iftask_setup(adjust, bw_mhz=1000, if_ghz=6, dcms=None):
        '''
        DRAMA function, must be called from an action.
        Calls IFTASK.TEST_SETUP to configure ACSIS for the Namakanui receivers.
        Arguments:
            adjust: LEVEL_ADJUST 0=setup_only, 1=setup_and_level, 2=level_only
            bw_mhz: BAND_WIDTH one of [250, 1000]
            if_ghz: IF_FREQ one of [4, 5, 6, 7]
            dcms: List of DCMs for BIT_MASK.  If None (default), use all 32 DCMs.
        '''
        adjust_valid = [0,1,2]
        bw_mhz_valid = [250,1000]
        if_ghz_valid = [4,5,6,7]
        if adjust not in adjust_valid:
            raise ValueError(f'adjust {adjust} not in {adjust_valid}')
        if bw_mhz not in bw_mhz_valid:
            raise ValueError(f'bw_mhz {bw_mhz} not in {bw_mhz_valid}')
        if if_ghz not in if_ghz_valid:
            raise ValueError(f'if_ghz {if_ghz} not in {if_ghz_valid}')
        if dcms is None:
            dcms = range(0,32)
        bitmask = 0
        for dcm in dcms:
            bitmask |= 1<<dcm
        setup_type = ['setup_only', 'setup_and_level', 'level_only'][adjust]
        log.info('iftask_setup(%s, bw_mhz=%d, if_ghz=%d, bitmask=0x%x',
                setup_type, bw_mhz, if_ghz, bitmask)
        msg = drama.obey('IFTASK@if-micro', 'TEST_SETUP',
                        NASM_SET='R_CABIN', BAND_WIDTH=bw_mhz, QUAD_MODE=4,
                        IF_FREQ=if_ghz, LEVEL_ADJUST=adjust, BIT_MASK=bitmask).wait(90)
        iftask_check_msg('IFTASK.TEST_SETUP', msg, log)
        # iftask_setup


    def iftask_set_bw(bw_mhz):
        '''
        DRAMA function, must be called from an action.
        Calls IFTASK.SET_DCM_BW.
        Arguments:
            bw_mhz: MHZ one of [250, 1000]
        '''
        bw_mhz_valid = [250,1000]
        if bw_mhz not in bw_mhz_valid:
            raise ValueError(f'bw_mhz {bw_mhz} not in {bw_mhz_valid}')
        log.info('iftask_set_bw(%d)', bw_mhz)
        msg = drama.obey('IFTASK@if-micro', 'SET_DCM_BW', DCM=-1, MHZ=bw_mhz).wait(10)
        iftask_check_msg('IFTASK.SET_DCM_BW', msg, log)
        # iftask_set_bw


    def iftask_set_lo2(lo2_mhz):
        '''
        DRAMA function, must be called from an action.
        Calls IFTASK.SET_LO2_FREQ.
        Can be quite slow, ~20s to set freqs + ~20s to set coax switches.
        Arguments:
            lo2_mhz: MHZ in range [6000, 10000]
        '''
        lo2_mhz_valid = interval(6000, 10000)
        if lo2_mhz not in lo2_mhz_valid:
            raise ValueError(f'lo2_mhz {lo2_mhz} not in {lo_mhz_valid}')
        log.info('iftask_set_lo2(%g)', lo2_mhz)
        msg = drama.obey('IFTASK@if-micro', 'SET_LO2_FREQ', LO2=-1, MHZ=lo2_mhz).wait(90)
        iftask_check_msg('IFTASK.SET_LO2_FREQ', msg, log)
        # iftask_set_lo2


    def iftask_get_tp2(dcms, itime=0.1):
        '''
        DRAMA function, must be called from an action.
        Calls IFTASK.WRITE_TP2 and returns list of power readings.
        Arguments:
            dcms: List of DCMs to return power readings for
            itime: Integration time, seconds
        '''
        wtime = itime + 5
        msg = drama.obey("IFTASK@if-micro", "WRITE_TP2", FILE="NONE", ITIME=itime).wait(wtime)
        iftask_check_msg('IFTASK.WRITE_TP2', msg, log)
        tps = []
        for dcm in dcms:
            tps.append(msg.arg['POWER%d'%(dcm)])
        return tps
        # iftask_get_tp2


    def iftask_get_att(dcms):
        '''
        DRAMA function, must be called from an action.
        Calls IFTASK.GET_DCM_ATTEN and returns list of attenuator counts.
        Arguments:
            dcms: List of DCMs to return attenuator counts for
        '''
        msg = drama.obey('IFTASK@if-micro', 'GET_DCM_ATTEN', DCM=-1).wait(5)
        iftask_check_msg('IFTASK.GET_DCM_ATTEN', msg, log)
        att = []
        for dcm in dcms:
            att.append(msg.arg['ATTEN%d'%(dcm)])
        return att
        # iftask_get_att

