'''
RMB 20181130
This module provides a base class for Namakanui monitor and control classes.
'''

import sys
import os
import time
import configparser

class Base(object):
    '''
    Base class for monitor and control classes.
    These have certain common features:
      - sleep and publish functions that can tie into an event loop
      - update functions, called periodically to update/publish a state dict
      - simulate set (property) for testing or disabling functionality
      - configuration from an INI file
    
    Derived classes must provide the following members:
        _simulate: set of strings for simulated components.
            init to full set (complete simulation)
            before first assignment to self.simulate.
        name: string used by publish
        state: dict used by publish
        publish(str, dict): publish state dict as name str.
        sleep(seconds): pause for a number of seconds (event loop)
        update_functions: list of update member functions
            to be called by update_all() and cycled through by update_one()
    
    Derived classes should implement the following member functions:
        initialise: create connections and fill out state dict.
            invoked by assignment to self.simulate.
    
    This base class creates a self._update_index member that derived classes
    should not alter.
    '''
    def get_simulate(self): return self._simulate
    def del_simulate(self): del self._simulate
    def set_simulate(self, s):
        '''Invoked on assignment to self.simulate property.'''
        if hasattr(s, 'split'):  # string
            s = s.split()
        s = set(x.lower() for x in s)
        # save current settings for rollback on failure
        save_simulate = self._simulate
        save_publish = self.publish
        save_sleep = self.sleep
        self.publish = lambda *a, **k: None  # disable publish until done updating.
        self.sleep = time.sleep  # event loop might not be ready yet
        try:
            self._simulate = s
            self.initialise()
        except:
            # roll back and re-update (in case we failed on a partial update)
            self._simulate = save_simulate
            self.initialise()
            raise
        finally:
            self.publish = save_publish
            self.sleep = save_sleep
            self.publish(self.name, self.state)
    
    simulate = property(get_simulate, set_simulate, del_simulate,
                        doc="set of strings for simulated components")

    def __init__(self, inifilename):
        self._update_index = -1
        
        # the config parsing below also pulls in all [include] files.
        self.config = None
        if inifilename:
            self.config = configparser.ConfigParser()
            inifile = os.path.realpath(inifilename.strip())
            inidir = os.path.dirname(inifile) + '/'
            inidone = set()
            include = {inifile}
            while inidone < include:
                fname = next(iter(include - inidone))
                inistr = open(fname).read()
                self.config.read_string(inistr, source='<%s>'%(fname))
                inidone.add(fname)
                if 'include' in self.config:
                    for fname self.config['include']:
                        fname = fname.strip()
                        if fname.startswith('/'):
                            fname = os.path.realpath(fname)
                        else:
                            fname = os.path.realpath(inidir + fname)
                        include.add(fname)
        # Base.__init__
    
    def initialise(self):
        '''
        Invoked by set_simulate on assignment to self.simulate property.
        Derived classes should tweak the value of self._simulate as needed,
        reinitialise member variables (e.g. FEMC), and call update_all().
        Only use self._simulate here (note the leading underscore) --
        do NOT assign to self.simulate or you'll get an infinite loop.
        '''
        pass

    def update_all(self):
        '''Call all functions in self.update_functions.'''
        for f in self.update_functions:
            f()
    
    def update_one(self):
        '''Call the next function in self.update_functions.'''
        self._update_index = (self._update_index + 1) % len(self.update_functions)
        self.update_functions[self._update_index]()

