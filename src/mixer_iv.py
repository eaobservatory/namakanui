#!/local/python3/bin/python3
'''
mixer_iv.py     RMB 20190806

Build an IV curve for a mixer and print to stdout as topcat ascii.

This script instantiates a Cart instance directly, rather than
communicating with a running engineering task via DRAMA.  The two
probably shouldn't run at the same time.

Usage:
mixer_iv.py <band> <mv_min> <mv_max> <mv_step>

TODO: tune first.
TODO: set magnet currents.


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

import jac_sw
import sys
import os
import time
import argparse
import namakanui.cart
import namakanui.agilent
import namakanui.femc
import namakanui.util
import logging

logging.root.setLevel(logging.DEBUG)
logging.root.addHandler(logging.StreamHandler())

binpath, datapath = namakanui.util.get_paths()

parser = argparse.ArgumentParser()
parser.add_argument('band', type=int, choices=[6,7])
parser.add_argument('mv_min', type=float)
parser.add_argument('mv_max', type=float)
parser.add_argument('mv_step', type=float)
parser.add_argument('avg_n', type=int, nargs='?', default=10)
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
if args.band==6 and (args.mv_min < -15.0 or args.mv_max > 15.0):
    logging.error('band 6 mv min/max outside [-15, 15] range')
    sys.exit(1)
if args.band==7 and (args.mv_min < -5.0 or args.mv_max > 5.0):
    logging.error('band 7 mv min/max outside [-5, 5] range')
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

# construct the list of mV settings; avoid sampling 0 since it looks bad
mvs = [args.mv_min]
mv = args.mv_min + args.mv_step*.5
while mv < args.mv_max:
    mvs.append(mv)
    mv += args.mv_step
mvs.append(args.mv_max)

#cart._ramp_sis_bias_voltages([mvs[0]]*4)
def ramp(x, offset=[0,0,0,0]):
    for po in range(2):
        for sb in range(2):
            mv = x - offset[po*2 + sb]
            try:
                cmd = femc.get_sis_voltage_cmd(ca, po, sb)
            except:
                cmd = 0.0
            logging.info('%d,%d, ramping from %g to %g...', po, sb, cmd, mv)
            step = .05
            if mv < cmd:
                step *= -1.0
            steps = arange(cmd,mv,step)
            for s in steps:
                femc.set_sis_voltage(ca, po, sb, s)
            femc.set_sis_voltage(ca, po, sb, mv)
    logging.info('ramps done.')


# if hot, skip offset calculation
try:
    k = femc.get_cartridge_lo_cartridge_temp(ca, 2)  # first mixer
except:
    k = 0.0

test_mv = 2.2
if args.band == 6:
    test_mv = 9.0
bias_offset = [0.0]*4
curr_offset = [0.0]*4
n = 50

if 0.0 < k < 30.0:
    logging.info('calculate bias voltage offsets...')
    ramp(test_mv)
    for i in range(n):
        for po in range(2):
            for sb in range(2):
                bias_offset[po*2 + sb] += femc.get_sis_voltage(ca, po, sb) - test_mv
    test_mv *= -1
    ramp(test_mv)
    for i in range(n):
        for po in range(2):
            for sb in range(2):
                bias_offset[po*2 + sb] += femc.get_sis_voltage(ca, po, sb) - test_mv
    for i in range(4):
        bias_offset[i] /= n*2
    logging.info('bias voltage offsets: %s', bias_offset)

    logging.info('calculate mixer current offsets...')
    ramp(test_mv, bias_offset)
    for i in range(n):
        for po in range(2):
            for sb in range(2):
                curr_offset[po*2 + sb] += femc.get_sis_current(ca,po,sb)*1e3
    test_mv *= -1
    ramp(test_mv, bias_offset)
    for i in range(n):
        for po in range(2):
            for sb in range(2):
                curr_offset[po*2 + sb] += femc.get_sis_current(ca,po,sb)*1e3
    for i in range(4):
        curr_offset[i] /= n*2
    logging.info('current offsets: %s', curr_offset)

    # refine bias voltage offsets by looking for zero-crossing.
    # start with n=10 and use n=100 once we get close.
    # the zero-crossing is more prominent with UNpumped LO.
    logging.info('bias voltage zero crossing...')
    def avg_curr(po, sb, n):
        c = 0.0
        for i in range(n):
            c += femc.get_sis_current(ca,po,sb)*1e3 - curr_offset[po*2 + sb]
        return c/n
    test_mv = -.05
    ramp(test_mv, bias_offset)
    zero_crossing = [0.0]*4
    for po in range(2):
        for sb in range(2):
            mv = test_mv
            curr = avg_curr(po, sb, 10)
            while curr < 0.0 and mv < 0.05:
                mv += 0.01
                femc.set_sis_voltage(ca, po, sb, mv - bias_offset[po*2 + sb])
                curr = avg_curr(po, sb, 10)
            while curr > 0.0 and mv > -0.05:
                mv -= .001
                femc.set_sis_voltage(ca, po, sb, mv - bias_offset[po*2 + sb])
                curr = avg_curr(po, sb, 10)
            # go back and forth 3x here since we might skip first loop due to n10 noise.
            curr = avg_curr(po, sb, 100)
            while curr < 0.0 and mv < .05:
                mv += .003
                femc.set_sis_voltage(ca, po, sb, mv - bias_offset[po*2 + sb])
                curr = avg_curr(po, sb, 100)
            while curr > 0.0 and mv > -.05:
                mv -= .002
                femc.set_sis_voltage(ca, po, sb, mv - bias_offset[po*2 + sb])
                curr = avg_curr(po, sb, 100)
            while curr < 0.0 and mv < .05:
                mv += .001
                femc.set_sis_voltage(ca, po, sb, mv - bias_offset[po*2 + sb])
                curr = avg_curr(po, sb, 100)
            zero_crossing[po*2 + sb] = mv - 0.0005
    logging.info('bias zero crossings: %s', zero_crossing)
    # note the sign change here.
    # bias_offset is (get - set); here get=0 and set=zero_crossing.
    for i in range(4):
        bias_offset[i] -= zero_crossing[i]
    logging.info('new bias offsets: %s', bias_offset)

    # note that the best measure would be a high-quality pumped/unpumped crossing point;
    # which would give us simultaneous bias voltage and mixer current offsets.
    # might be worth a try? PA can be enabled/disabled quickly.


## test of back-to-back current readings -- yes, they do differ
#test_curr = []
#for i in range(10):
    #test_curr.append(femc.get_sis_current(ca,0,0)*1e3)
#logging.info('test curr: %s', test_curr)

def sample(what=''):
    ramp(args.mv_min, bias_offset)
    logging.info('sampling %s...', what)
    # also output to stdout for topcat
    sys.stdout.write('#mV_%s mV01 uA01 mV02 uA02 mV11 uA11 mV12 uA12\n'%(what))
    # progress every second is about every 50th sample
    #progress_step = 50
    secs_per_step = .008 * args.avg_n
    progress_secs = 10
    progress_step = int(progress_secs / secs_per_step)+1
    progress = progress_step
    mv = [[], [], [], []]
    ua = [[], [], [], []]
    for j,smv in enumerate(mvs):
        for po in range(2):
            for sb in range(2):
                femc.set_sis_voltage(ca, po, sb, smv - bias_offset[po*2 + sb])
        sys.stdout.write('%.3f ' % (smv))
        time.sleep(.001)  # each smv takes ~20ms to sample anyway
        #for po in range(2):
            #for sb in range(2):
                #avg_mv = 0.0
                #avg_ua = 0.0
                #n = 10
                #for i in range(n):
                    #avg_ua += femc.get_sis_current(ca,po,sb)*1e3 - curr_offset[po*2 + sb]
                    #avg_mv += femc.get_sis_voltage(ca, po, sb)
                #avg_ua /= n
                #avg_mv /= n
                #sys.stdout.write('%.3f %.3f ' % (avg_mv, avg_ua))
                #mv[po*2 + sb].append(smv)  # TODO try avg_mv
                #ua[po*2 + sb].append(avg_ua)
        
        # hoping that rearranging this loop reduces uA noise --
        # by increasing time (4ms) between samples for each mixer:  not really.
        # by increasing number of samples: yes, n=100 reduces a fair bit.
        # note n=1 is pretty noisy, +-1.5 uA.  
        #n = 10
        n = args.avg_n
        avg_mv = [0.0]*4
        avg_ua = [0.0]*4
        for i in range(n):
            for po in range(2):
                for sb in range(2):
                    avg_ua[po*2 + sb] += femc.get_sis_current(ca,po,sb)*1e3 - curr_offset[po*2 + sb]
                    avg_mv[po*2 + sb] += femc.get_sis_voltage(ca, po, sb)
                    if i == n-1:
                        avg_ua[po*2 + sb] /= n
                        avg_mv[po*2 + sb] /= n
                        sys.stdout.write('%.3f %.3f ' % (avg_mv[po*2 + sb], avg_ua[po*2 + sb]))
                        mv[po*2 + sb].append(smv)
                        ua[po*2 + sb].append(avg_ua[po*2 + sb])
        sys.stdout.write('\n')
        sys.stdout.flush()
        if j == progress:
            logging.info('sampling %s %.1f%%', what, j*100.0/len(mvs))
            progress += progress_step
    logging.info('sampling %s done.', what)
    ramp(0.0, bias_offset)
    for po in range(2):
        for sb in range(2):
            plot(mv[po*2+sb], ua[po*2+sb], '-', label='%d%d_%s'%(po,sb+1,what))



# if hot, just take one sample 
try:
    k = femc.get_cartridge_lo_cartridge_temp(ca, 2)  # first mixer
except:
    k = 0.0

if k <= 0.0 or k >= 30.0:
    sample('%.2fK'%(k))
else:
    sample('pa_on')  # we assume
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







