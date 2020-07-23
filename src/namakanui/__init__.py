'''
namakanui/__init__.py   RMB 20181016

This file does very little;
the namakanui module mainly just serves as a namespace for the submodules.


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

# __version__.py is created by build system and may not be present
try:
    from namakanui.version import __version__
except:
    pass


# default publish function, does nothing
def nop(*args, **kwargs):
    '''
    This function does nothing.
    It can be used as a 'publish' function for testing Namakanui classes.
    '''
    pass



