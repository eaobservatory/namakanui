'''
RMB 20181228
ConfigParser derivative that supports an [include] section.
Handles nested inclusions with absolute or relative paths.
'''

import sys
import os
import configparser

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

