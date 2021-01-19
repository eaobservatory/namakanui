'''
namakanui/util/__init__.py   RMB 20200227

This file contains some basic utility functions.

The rest of this package directory contains modules that can be invoked
by the namakanui_util.py script, or as actions by namakanui_task.py.


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


def get_paths():
    '''Return binpath and datapath for this script.'''
    if sys.argv[0]:
        binpath = os.path.dirname(os.path.realpath(sys.argv[0])) + '/'
    else:
        binpath = os.path.realpath('') + '/'
    # crawl up parent directories looking for data dir
    crawl = binpath[:-1]
    while crawl:
        datapath = crawl + '/data/'
        if os.path.exists(datapath):
            break
        crawl = crawl.rpartition('/')[0]
    if not crawl:  # we don't accept /data at root
        raise RuntimeError('no data path found from bin path %s'%(binpath))
    return binpath, datapath
    

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


