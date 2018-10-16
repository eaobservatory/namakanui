#!/local/python/bin/python3
'''
20181016 RMB

Drama control task for the Namakanui receivers:
Ala'ihi: 86 GHz
U'u: 230 GHz
Aweoweo: 345 GHz

The specific receiver is selected by the taskname (argv[1]):
ALAIHI, UU, or AWEOWEO.

I haven't decided yet whether this script will only be an
engineering control task or if it will act as the frontend
wrapper (with INITIALISE, CONFIGURE, SEQUENCE etc) as well.
'''
import jac_sw
import drama

