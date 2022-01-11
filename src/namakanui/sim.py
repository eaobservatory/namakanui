'''
namakanui/sim.py    RMB 20190520

Defines the SIMULATE bits for Namakanui.
Provides methods for getting cartridge band bits and for converting to text.

Previously each class instance had a set() holding text strings, which,
while readable, would have been less compatible with the rest of our systems.


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

SIM_B3_FEMC    = 1<<0
SIM_B3_WARM    = 1<<1
SIM_B3_COLD    = 1<<2
SIM_B6_FEMC    = 1<<3
SIM_B6_WARM    = 1<<4
SIM_B6_COLD    = 1<<5
SIM_B7_FEMC    = 1<<6
SIM_B7_WARM    = 1<<7
SIM_B7_COLD    = 1<<8
SIM_CRYO_FEMC  = 1<<9  # obsolete, but keeping as a placeholder
SIM_LOAD       = 1<<10
SIM_REFERENCE  = 1<<11
SIM_IFSW_6260  = 1<<12
SIM_IFSW_6024  = 1<<13
SIM_PHOTONICS  = 1<<14
SIM_FEMC       = 1<<15
SIM_COMPRESSOR = 1<<16
SIM_LAKESHORE  = 1<<17
SIM_VACUUM     = 1<<18
SIM_STSR       = 1<<19

SIM_IFSW = SIM_IFSW_6260 | SIM_IFSW_6024

bit_to_str_dict = {
SIM_B3_FEMC   : "SIM_B3_FEMC",
SIM_B3_WARM   : "SIM_B3_WARM",
SIM_B3_COLD   : "SIM_B3_COLD",
SIM_B6_FEMC   : "SIM_B6_FEMC",
SIM_B6_WARM   : "SIM_B6_WARM",
SIM_B6_COLD   : "SIM_B6_COLD",
SIM_B7_FEMC   : "SIM_B7_FEMC",
SIM_B7_WARM   : "SIM_B7_WARM",
SIM_B7_COLD   : "SIM_B7_COLD",
SIM_CRYO_FEMC : "SIM_CRYO_FEMC",
SIM_LOAD      : "SIM_LOAD",
SIM_REFERENCE : "SIM_REFERENCE",
SIM_IFSW_6260 : "SIM_IFSW_6260",
SIM_IFSW_6024 : "SIM_IFSW_6024",
SIM_PHOTONICS : "SIM_PHOTONICS",
SIM_FEMC      : "SIM_FEMC",
SIM_COMPRESSOR: "SIM_COMPRESSOR",
SIM_LAKESHORE : "SIM_LAKESHORE",
SIM_VACUUM    : "SIM_VACUUM",
SIM_STSR      : "SIM_STSR",
}

str_to_bit_dict = {
"SIM_B3_FEMC"   : SIM_B3_FEMC,
"SIM_B3_WARM"   : SIM_B3_WARM,
"SIM_B3_COLD"   : SIM_B3_COLD,
"SIM_B6_FEMC"   : SIM_B6_FEMC,
"SIM_B6_WARM"   : SIM_B6_WARM,
"SIM_B6_COLD"   : SIM_B6_COLD,
"SIM_B7_FEMC"   : SIM_B7_FEMC,
"SIM_B7_WARM"   : SIM_B7_WARM,
"SIM_B7_COLD"   : SIM_B7_COLD,
"SIM_CRYO_FEMC" : SIM_CRYO_FEMC,
"SIM_LOAD"      : SIM_LOAD,
"SIM_REFERENCE" : SIM_REFERENCE,
"SIM_IFSW_6260" : SIM_IFSW_6260,
"SIM_IFSW_6024" : SIM_IFSW_6024,
"SIM_PHOTONICS" : SIM_PHOTONICS,
"SIM_FEMC"      : SIM_FEMC,
"SIM_IFSW"      : SIM_IFSW,
"SIM_COMPRESSOR": SIM_COMPRESSOR,
"SIM_LAKESHORE" : SIM_LAKESHORE,
"SIM_VACUUM"    : SIM_VACUUM,
"SIM_STSR"      : SIM_STSR,
}


def bits_for_band(band):
    '''Return (FEMC, WARM, COLD) sim bits for given band.'''
    if band == 3:
        return SIM_B3_FEMC, SIM_B3_WARM, SIM_B3_COLD
    elif band == 6:
        return SIM_B6_FEMC, SIM_B6_WARM, SIM_B6_COLD
    elif band == 7:
        return SIM_B7_FEMC, SIM_B7_WARM, SIM_B7_COLD
    else:
        raise ValueError('band %s not one of [3,6,7]' % band)


def bits_to_str(bits):
    '''Return a space-separated string of nonzero SIM fields in given bits.'''
    s = []
    for k,v in bit_to_str_dict.items():
        if bits & k:
            s.append(v)
    return ' '.join(s)


def str_to_bits(s):
    '''Return a bitmask for given SIM fields in string s.'''
    s = s.replace(',',' ')
    s = s.replace('|',' ').split()
    b = 0
    for k in s:
        b |= str_to_bit_dict[k]
    return b


def other_bands(band):
    '''Return SIM_FEMC mask for other bands.'''
    sim_femc_bits = {3:SIM_B3_FEMC, 6:SIM_B6_FEMC, 7:SIM_B7_FEMC}
    if band in sim_femc_bits:
        del sim_femc_bits[band]
    else:
        sim_femc_bits[0] = SIM_FEMC  # invalid band given, so sim FEMC too
    mask = 0
    for b in sim_femc_bits.values():
        mask |= b
    return mask


