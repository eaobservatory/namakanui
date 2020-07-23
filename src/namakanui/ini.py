'''
namakanui/ini.py    RMB 20181228

IncludeParser is a ConfigParser derivative that supports an [include] section.
Handles nested inclusions with absolute or relative paths.

This module also provides functions for reading and interpolating tables,
including those in topcat ascii format.


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
import configparser
import collections
import bisect


class IncludeParser(configparser.ConfigParser):
    def __init__(self, inifilename):
        '''
        Parse given .ini file, handling [include] sections.
        NOTE: This is the only overridden method. Using read(), read_string(),
              or other ConfigParser methods will not [include] properly.
        '''
        configparser.ConfigParser.__init__(self)
        inifilename = os.path.realpath(inifilename.strip())
        inidone = set()
        include = {inifilename}
        while inidone < include:
            fname = next(iter(include - inidone))
            inidir = os.path.dirname(fname) + '/'
            inistr = open(fname).read()
            self.read_string(inistr, source='<%s>'%(fname))
            inidone.add(fname)
            if 'include' in self:
                for fname in self['include']:
                    fname = fname.strip()
                    if fname.startswith('/'):
                        fname = os.path.realpath(fname)
                    else:
                        fname = os.path.realpath(inidir + fname)
                    include.add(fname)


def read_table(config_section, name, dtype, fnames):
    '''
    Return a table from a section of the config file.  Arguments:
        config_section: ConfigParser or dict instance to read from
        name: Table name, must match config as shown below
        dtype: Type to cast each table value as
        fnames: List of field names
    The table will be a list of namedtuples holding values of dtype.
    The config file for "Name" should look like this:
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


def read_ascii(filename):
    '''
    Return a table from the given topcat-ascii filename.
    The table will be a list of namedtuples holding values of type float.
    If the table is unsorted (ascending first column), raise RuntimeError.
    '''
    header = ''
    ttype = None
    table = []
    prev = None
    for line in open(filename):
        line = line.strip()
        if not line:
            continue
        if line.startswith('#'):
            if ttype:
                continue
            line = line[1:].strip()
            if not line:
                continue
            header = line
            continue
        if not ttype:
            # name (and field names) must be valid python identifiers
            name = filename.split('/')[-1].split('.')[0].strip()
            #print('ttype args:', name, header)  # debug
            ttype = collections.namedtuple(name, header)
        tup = ttype(*[float(x) for x in line.split()])
        if prev is not None and tup[0] < prev:
            raise RuntimeError('%s table values are out of order' % (filename))
        prev = tup[0]
        table.append(tup)
    return table


def read_table_or_ascii(config_section, name, dtype, fnames, datapath):
    '''Try read_table, falling back to read_ascii(datapath+config_section[name]).'''
    try:
        return read_table(config_section, name, dtype, fnames)
    except:
        return read_ascii(datapath + config_section[name])


def interp_table(table, x):
    '''
    Return a linearly-interpolated row in table at given x,
    where x corresponds to the first column in the table.
    If outside the table bounds, return the first or last row.
    If table is empty, return None.
    
    NOTE: Only works for lists of collections.namedtuple.
    '''
    if not table:
        return None
    if x <= table[0][0]:
        return table[0]
    if x >= table[-1][0]:
        return table[-1]
    j = bisect.bisect(table, (x,))
    i = j-1
    if table[i][0] == table[j][0]:
        return table[i]  # arbitrary, else divide by zero below
    f = (x - table[i][0]) / (table[j][0] - table[i][0])
    ttype = type(table[i])
    return ttype(*[a + f*(b-a) for a,b in zip(table[i], table[j])])

