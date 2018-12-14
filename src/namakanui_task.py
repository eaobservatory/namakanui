#!/local/python3/bin/python3
'''
20181016 RMB

 86 GHz: Ala'ihi
230 GHz: U'u
345 GHz: Aweoweo

TODO.  Since I've decided to break up the cartridge control into
individual tasks, it might make sense to have a supervisor task.
However, the duties of such a task would be pretty minimal, little
more than a TUNE action that sets the IF switch and signal generator
before sending a tune command to the individual cartridges.

I haven't decided yet whether this script will only be an
engineering control task or if it will act as the frontend
wrapper (with INITIALISE, CONFIGURE, SEQUENCE etc) as well.
'''
import jac_sw
import drama

