#!/local/python3/bin/python3
'''
mixer_iv.py
RMB 20190806

Build an IV curve for a mixer and print to stdout as topcat ascii.

This script instantiates a Cart instance directly, rather than
communicating with a running engineering task via DRAMA.  The two
probably shouldn't run at the same time.

Usage:
mixer_iv.py <band> <mv_min> <mv_max> <mv_step>

TODO: tune first.
TODO: set magnet currents.
TODO: matplotlib.
'''

import jac_sw
import sys
import os
import time
import argparse
import namakanui.cart
import namakanui.agilent
import namakanui.femc
import logging

logging.root.setLevel(logging.DEBUG)
logging.root.addHandler(logging.StreamHandler())

binpath = os.path.dirname(os.path.realpath(sys.argv[0])) + '/'
datapath = os.path.realpath(binpath + '../../data') + '/'

parser = argparse.ArgumentParser()
parser.add_argument('band', type=int)
parser.add_argument('mv_min', type=float)
parser.add_argument('mv_max', type=float)
parser.add_argument('mv_step', type=float)
args = parser.parse_args()

# TODO allow reverse stepping
if args.mv_step < 0.001:
    logging.error('invalid step, must be >= 0.001 mV')
    sys.exit(1)
if args.mv_step > 0.05:
    logging.warning('setting mv_step to 0.05 mV to avoid ramping')
    mv_step = 0.05
if args.mv_min > args.mv_max:
    logging.error('start/end out of order')
    sys.exit(1)

#sys.exit(0)

def mypub(n,s):
    pass

# connecting to a cart will zero the PAs and such during initialise,
# so we'll just talk directly to the FEMC instead.
#cart = namakanui.cart.Cart(args.band, datapath+'band%d.ini'%(args.band), time.sleep, mypub, simulate=0)
#cart.power(1)
femc = namakanui.femc.FEMC()
ca = args.band - 1

#def do_mv(mv):
    #for po in range(2):
        #for sb in range(2):
            #cart.femc.set_sis_voltage(cart.ca, po, sb, mv)
    #sys.stdout.write('%.3f ' % (mv))
    #for po in range(2):
        #for sb in range(2):
            #mv = cart.femc.get_sis_voltage(cart.ca, po, sb)
            #ma = cart.femc.get_sis_current(cart.ca, po, sb)
            #sys.stdout.write('%.3f %.3f ' % (mv, ma*1e3))
    #sys.stdout.write('\n')
    #sys.stdout.flush()

#sys.stdout.write('#mV mV01 uA01 mV02 uA02 mV11 uA11 mV12 uA12')

#cart._ramp_sis_bias_voltages([args.mv_min]*4)
#mv = args.mv_min
#while mv < args.mv_max:
    #do_mv(mv)
    #mv += args.mv_step
#mv = args.mv_max
#do_mv(mv)
#cart._ramp_sis_bias_voltages([0.0]*4)
#sys.exit(0)

# matplotlib version
logging.info('importing pylab...')
from pylab import *
mvs = []
mv = args.mv_min
while mv < args.mv_max:
    mvs.append(mv)
    mv += args.mv_step
mvs.append(args.mv_max)

mv = [[], [], [], []]
ua = [[], [], [], []]

#cart._ramp_sis_bias_voltages([mvs[0]]*4)
def ramp(x):
    for po in range(2):
        for sb in range(2):
            try:
                cmd = femc.get_sis_voltage_cmd(ca, po, sb)
            except:
                cmd = 0.0
            logging.info('%d,%d, ramping from %g to %g...', po, sb, cmd, x)
            step = .05
            if x < cmd:
                step *= -1.0
            steps = arange(cmd,x,step)
            for s in steps:
                femc.set_sis_voltage(ca, po, sb, s)
            femc.set_sis_voltage(ca, po, sb, x)
    logging.info('ramps done.')

def sample(what=''):
    ramp(args.mv_min)
    logging.info('sampling...')
    mv = [[], [], [], []]
    ua = [[], [], [], []]
    for smv in mvs:
        for po in range(2):
            for sb in range(2):
                femc.set_sis_voltage(ca, po, sb, smv)
        #time.sleep(.001)
        for po in range(2):
            for sb in range(2):
                avg_curr = 0.0
                n = 10
                for i in range(n):
                    avg_curr += femc.get_sis_current(ca,po,sb)*1e3
                avg_curr /= n
                mv[po*2 + sb].append(smv)#femc.get_sis_voltage(ca, po, sb))
                ua[po*2 + sb].append(avg_curr)#femc.get_sis_current(ca, po, sb)*1e3)
    logging.info('sampling done.')
    ramp(0.0)
    for po in range(2):
        for sb in range(2):
            plot(mv[po*2+sb], ua[po*2+sb], '-', label='%d%d_%s'%(po,sb+1,what))

sample('pa_on')
femc.set_cartridge_lo_pa_pol_drain_voltage_scale(ca, 0, 0.0)
femc.set_cartridge_lo_pa_pol_drain_voltage_scale(ca, 1, 0.0)
femc.set_cartridge_lo_pa_pol_gate_voltage(ca, 0, 0.0)
femc.set_cartridge_lo_pa_pol_gate_voltage(ca, 1, 0.0)
sample('pa_off')
title('band %d IV' % (args.band))
xlabel('mV')
ylabel('uA')
grid()
legend(loc='best')
show()







