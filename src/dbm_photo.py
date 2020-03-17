#!/local/python3/bin/python3
'''
RMB 20191227

Create a table for the Agilent/Keysight signal generator
with the necessary output power setting to produce the desired
input power level for the photonics transmission system
at each frequency.

The signal generator output must be connected to a power meter, N1913A,
which is connected directly to LAN and uses SCPI commands.

TODO: custom starting power level?  i'm assuming that loss is minimal
      and the power setting is fairly accurate, so i just set the initial
      level to the target and adjust a few times.
'''

import jac_sw
import namakanui.agilent
import sys
import os
import argparse
import socket
import time

binpath = os.path.dirname(os.path.realpath(sys.argv[0])) + '/'
# HACK, should crawl up
if 'install' in binpath:
    datapath = os.path.realpath(binpath + '../../data') + '/'
else:
    datapath = os.path.realpath(binpath + '../data') + '/'


parser = argparse.ArgumentParser()
#parser.add_argument('IP', help='prologix adapter IP address')
#parser.add_argument('GPIB', type=int, help='power meter GPIB address')
parser.add_argument('IP', help='N1913A power meter IP address')
parser.add_argument('dbm', type=float, help='target dBm')
parser.add_argument('GHz_start', type=float)
parser.add_argument('GHz_end', type=float)
parser.add_argument('GHz_step', type=float)
args = parser.parse_args()

#if args.GPIB < 0 or args.GPIB > 30:
    #sys.stderr.write('error: GPIB address %d outside [0, 30] range\n'%(args.GPIB))
    #sys.exit(1)

if args.dbm < -20.0 or args.dbm > 14.0:
    sys.stderr.write('error: target dBm %g outside [-20, 14] range\n'%(args.dbm))
    sys.exit(1)

# TODO might want to relax this for more generalized testing
if args.GHz_start > args.GHz_end \
    or args.GHz_start < 16.0 or args.GHz_start > 32.0 \
    or args.GHz_end < 16.0 or args.GHz_end > 32.0:
    sys.stderr.write('error: frequency out of range\n')
    sys.exit(1)

if args.GHz_step <= 0.0:
    args.GHz_step = (args.GHz_end - args.GHz_start) + 1.0

# sanity check
steps = (args.GHz_end - args.GHz_start) / args.GHz_step
if steps > 10e3:
    sys.stderr.write('error: step size too small for this range\n')
    sys.exit(1)

agilent = namakanui.agilent.Agilent(datapath+'agilent.ini', time.sleep, namakanui.nop, simulate=0)
agilent.log.setLevel(logging.INFO)
agilent.set_dbm(agilent.safe_dbm)
agilent.set_output(1)

#prologix = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
#prologix.settimeout(1)
#prologix.connect((args.IP, 1234))
#prologix.send(b'++savecfg 0\n')  # don't save settings to prologix EPROM
#prologix.send(b'++addr %d\n'%(args.GPIB))

# TODO: is it worth making a class for the N1913A?
pmeter = socket.socket()
pmeter.settimeout(1)
pmeter.connect((args.IP, 5025))
pmeter.send(b'*idn?\n')
idn = pmeter.recv(256)
if b'N1913A' not in idn:
    sys.stderr.write('error: expected power meter model N1913A, but got %s\n'%(idn))
    sys.exit(1)
# just assume all this succeeds
pmeter.send(b'*cls\n')  # clear errors
pmeter.send(b'unit:power dbm\n')  # dBm readings
pmeter.send(b'init:cont on\n')  # free run mode
pmeter.send(b'mrate normal\n')  # 20 reads/sec
pmeter.send(b'calc:hold:stat off\n')  # no min/max stuff
pmeter.send(b'aver:count:auto on\n')  # auto filter settings
pmeter.send(b'syst:err?\n')
err = pmeter.recv(256)
if not err.startswith(b'+0,"No error"'):
    sys.stderr.write('error: N1913A setup failure: %s\n'%(err))
    sys.exit(1)



def read_power():
    '''Return power reading in dBm.'''
    #raise RuntimeError('TODO')
    pmeter.send(b'fetch?\n')
    return float(pmeter.recv(256))


def do_ghz(ghz):
    '''Optimize power output for given frequency.'''
    sys.stderr.write('%.6f: '%(ghz))
    sys.stderr.flush()
    delay = 0.1  # generous sleep since pmeter takes 50ms/read
    dbm = args.dbm
    agilent.set_hz_dbm(ghz*1e9, dbm)
    pmeter.send(b'freq %gGHz\n'%(ghz))  # for power sensor calibration tables
    # assuming meter and generator are both reasonably accurate,
    # we only need to iterate a few times to get close to optimal setting.
    for i in range(3):
        time.sleep(delay)
        power = read_power()
        err = args.dbm - power
        sys.stderr.write('(%.2f, %.2f) '%(dbm, power))
        sys.stderr.flush()
        dbm += err
        # NOTE: even if we rail, don't bail out early -- might have overshot
        if dbm < agilent.safe_dbm:
            dbm = agilent.safe_dbm
        if dbm > agilent.max_dbm:
            dbm = agilent.max_dbm
        agilent.set_dbm(dbm)
    time.sleep(delay)
    power = read_power()
    sys.stderr.write('(%.2f, %.2f)\n'%(dbm, power))
    print('%.6f %.2f %.2f'%(ghz, dbm, power))

print('#ghz dbm pow')
ghz = args.GHz_start
while ghz < (args.GHz_end - 1e-12):
    do_ghz(ghz)
    ghz += args.GHz_step
ghz = args.GHz_end
do_ghz(ghz)

agilent.set_dbm(agilent.safe_dbm)
sys.stderr.write('done.\n')



