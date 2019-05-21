'''
RMB 20190520
Defines the SIMULATE bits for Namakanui.
Provides methods for getting cartridge band bits and for converting to text.

Previously each class instance had a set() holding text strings, which,
while readable, would have been less compatible with the rest of our systems.
'''

SIM_B3_FEMC   = 1<<0
SIM_B3_WARM   = 1<<1
SIM_B3_COLD   = 1<<2
SIM_B6_FEMC   = 1<<3
SIM_B6_WARM   = 1<<4
SIM_B6_COLD   = 1<<5
SIM_B7_FEMC   = 1<<6
SIM_B7_WARM   = 1<<7
SIM_B7_COLD   = 1<<8
SIM_CRYO_FEMC = 1<<9
SIM_LOAD      = 1<<10
SIM_AGILENT   = 1<<11

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
SIM_AGILENT   : "SIM_AGILENT",
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
"SIM_AGILENT"   : SIM_AGILENT,
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
    '''Return a bitmask for given SIM fields in space-separated string s.'''
    s = s.replace(',',' ').split()  # or comma-separated, I suppose
    b = 0
    for k in s:
        b |= str_to_bit_dict[k]
    return b




