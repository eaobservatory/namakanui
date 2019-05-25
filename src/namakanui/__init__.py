'''
Ryan Berthold 20181016

This file does very little;
the namakanui module mainly just serves as a namespace for the submodules.
'''

from namakanui.version import __version__

# default publish function, does nothing
def nop(*args, **kwargs):
    '''
    This function does nothing.
    It can be used as a 'publish' function for testing Namakanui classes.
    '''
    pass



