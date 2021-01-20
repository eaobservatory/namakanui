#!/local/python3/bin/python3
'''
att_table.py    RMB 20191121

Build an attenuation table for a receiver by tuning a range of frequencies
and adjusting the attenuator to achieve sufficient PLL IF power
in the [-.7, -3]V range, ideally around -1.5V.

This script instantiates a Cart instance directly, rather than
communicating with a running engineering task via DRAMA.  The two
probably shouldn't run at the same time.

The <att> parameter gives the starting attenuator setting at each frequency.
You can also give "ini+X" for this parameter to start with the value
interpolated from the table in the photonics.ini file, plus X counts.

Usage:
att_table.py <band> <LO_GHz_start> <LO_GHz_end> <LO_GHz_step> <lock_polarity> <att>


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
import namakanui.ifswitch
import namakanui.photonics
import namakanui.util
import logging

logging.root.setLevel(logging.DEBUG)
logging.root.addHandler(logging.StreamHandler())

binpath, datapath = namakanui.util.get_paths()

parser = argparse.ArgumentParser()
parser.add_argument('band', type=int, choices=[3,6,7])
parser.add_argument('LO_GHz_start', type=float)
parser.add_argument('LO_GHz_end', type=float)
parser.add_argument('LO_GHz_step', type=float)
parser.add_argument('lock_polarity', choices=['below','above'])
parser.add_argument('att')
args = parser.parse_args()
#print(args.band, args.LO_GHz_start, args.LO_GHz_end, args.LO_GHz_step)

if args.LO_GHz_step < 0.01:
    logging.error('invalid step, must be >= 0.01 GHz')
    sys.exit(1)
if args.LO_GHz_start > args.LO_GHz_end:
    logging.error('start/end out of order')
    sys.exit(1)

use_ini = False
try:
    args.att = int(args.att)
except:
    if not args.att.startswith('ini'):
        logging.error('invalid att, must be a number or "ini"')
        sys.exit(1)
    use_ini = True
    args.att = int(args.att[3:] or '0')

#sys.exit(0)

def mypub(n,s):
    pass


agilent = namakanui.agilent.Agilent(datapath+'agilent.ini', time.sleep, mypub)
agilent.log.setLevel(logging.INFO)
agilent.set_dbm(agilent.safe_dbm)
agilent.set_output(1)

photonics = namakanui.photonics.Photonics(datapath+'photonics.ini', time.sleep, mypub)
photonics.log.setLevel(logging.INFO)
photonics.set_attenuation(photonics.max_att)

ifswitch = namakanui.ifswitch.IFSwitch(datapath+'ifswitch.ini', time.sleep, mypub)
ifswitch.set_band(args.band)
ifswitch.close()  # done with ifswitch

cart = namakanui.cart.Cart(args.band, datapath+'band%d.ini'%(args.band), time.sleep, mypub)
cart.power(1)
cart.femc.set_cartridge_lo_pll_sb_lock_polarity_select(cart.ca, {'below':0, 'above':1}[args.lock_polarity])
floog = agilent.floog * {'below':1.0, 'above':-1.0}[args.lock_polarity]



# check to make sure this receiver is selected.
rp = cart.state['pll_ref_power']
if rp < -3.0:
    logging.error('PLL reference power (FLOOG, 31.5 MHz) is too strong (%.2f V).  Please attenuate.', rp)
    sys.exit(1)
if rp > -0.5:
    logging.error('PLL reference power (FLOOG, 31.5 MHz) is too weak (%.2f V).', rp)
    logging.error('Please make sure the IF switch has band %d selected.', args.band)
    sys.exit(1)

# zero out cart mixers, we only care about the PLL
cart._set_lna_enable(0)
cart._set_pa([0]*4)
cart._ramp_sis_bias_voltages([0]*4)
cart._ramp_sis_magnet_currents([0]*4)


def adjust_att(lo_ghz):
    # sanity check, skip impossible freqs
    lo_min = cart.yig_lo * cart.cold_mult * cart.warm_mult
    lo_max = cart.yig_hi * cart.cold_mult * cart.warm_mult
    if lo_ghz < lo_min or lo_ghz > lo_max:
        logging.error('skipping lo_ghz %g, outside range [%.3f, %.3f] for band %d',
                      lo_ghz, lo_min, lo_max, args.band)
        return
    # RMB 20200316: use new utility function
    if namakanui.util.tune(cart, agilent, photonics, lo_ghz, pll_range=[-1.4,-1.6],
                           att_ini=use_ini, att_start=args.att, att_min=-photonics.max_att,
                           dbm_ini=True, dbm_start=0, dbm_max=0, lock_only=True):
        sys.stdout.write('%.3f %d %.3f %.3f %.3f\n' % (lo_ghz, photonics.state['attenuation'], cart.state['pll_if_power'], cart.state['pa_drain_s'][0], cart.state['pa_drain_s'][1]))
        sys.stdout.flush()


def try_adjust_att(lo_ghz):
    try:
        adjust_att(lo_ghz)
    except Exception as e:
        photonics.set_attenuation(photonics.max_att)
        agilent.set_dbm(agilent.safe_dbm)
        logging.error('unhandled exception: %s', e)
        raise


sys.stdout.write('#lo_ghz att pll_if_power pa_0 pa_1\n')  # topcat ascii
lo_ghz = args.LO_GHz_start
while lo_ghz < args.LO_GHz_end:
    try_adjust_att(lo_ghz)
    lo_ghz += args.LO_GHz_step
lo_ghz = args.LO_GHz_end
try_adjust_att(lo_ghz)

# since this script is also used to tune the receiver, retune once we've
# found the optimal IF power to servo the PA.
cart.update_all()
if cart.state['lo_ghz'] == lo_ghz and not cart.state['pll_unlock']:
    logging.info('retuning at %g to adjust PA...', lo_ghz)
    try:
        cart.tune(lo_ghz, 0.0)
        time.sleep(0.1)
        cart.update_all()
        if cart.state['pll_unlock']:
            photonics.set_attenuation(photonics.max_att)
            agilent.set_dbm(agilent.safe_dbm)
            logging.error('lost lock at %g', lo_ghz)
        logging.info('band %d tuned to %g GHz, IF power: %g', args.band, lo_ghz, cart.state['pll_if_power'])
    except Exception as e:
        photonics.set_attenuation(photonics.max_att)
        agilent.set_dbm(agilent.safe_dbm)
        logging.error('final retune exception: %s', e)

# show the last dbm and attenuation setting
agilent.update()
logging.info('final dbm: %.2f', agilent.state['dbm'])
photonics.update()
logging.info('final att: %d', photonics.state['attenuation'])

logging.info('done.')





