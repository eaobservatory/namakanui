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
    f = logging.Formatter('%(asctime)s %(levelname)s:%(name)s: %(message)s')
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


def get_band_lo_range(band, config=None):
    '''Get valid LO range for given band, as an interval.'''
    if config is None:
        config = get_config()
    b = str(band)
    cc = config[config[b]['cold']]
    wc = config[config[b]['warm']]
    mult = int(cc['Mult']) * int(wc['Mult'])
    floyig = float(wc['FLOYIG'])
    fhiyig = float(wc['FHIYIG'])
    return interval(floyig*mult, fhiyig*mult)


def init_rfsma_pmeters_49():
    '''
    Set both RFSMAs to send 4-9 GHz IFs to their first power meters.
    Return PMeter2 instances (rfsma_p1, rfsma_p3), set to 6.5 GHz.
    rfsma_p1: A14, EHT#1 (USB), chA=POL0, chB=POL1
    rfsma_p3: A17, EHT#2 (LSB), chA=POL0, chB=POL1
    '''
    import namakanui.rfsma
    import namakanui.pmeter2
    config = get_config('rfsma.ini')  # holds pmeter config also
    rfsma_a14 = namakanui.rfsma.RFSMA(config, 'rfsma_a14', level=logging.DEBUG)
    rfsma_a17 = namakanui.rfsma.RFSMA(config, 'rfsma_a17', level=logging.DEBUG)
    rfsma_a14.set_pmeter_49()
    rfsma_a17.set_pmeter_49()
    rfsma_p1 = namakanui.pmeter2.PMeter2(config, 'rfsma_p1')
    rfsma_p3 = namakanui.pmeter2.PMeter2(config, 'rfsma_p3')
    rfsma_p1.set_ghz(6.5)
    rfsma_p3.set_ghz(6.5)
    return (rfsma_p1, rfsma_p3)


def read_rfsma_pmeters(pmeters):
    '''
    Return readings for both channels of all pmeters as a flat list.
    If pmeters = [rfsma_p1, rfsma_p3] (from init_rfsma_pmeters_49),
    then return = [usb_p0, usb_p1, lsb_p0, lsb_p1].
    '''
    # for multiple meters, separate read_init should be faster than read_power
    for m in pmeters:
        m.read_init()
    return [p for m in pmeters for p in m.read_fetch()]

