#!/local/python3/bin/python3
'''
att_table.py
RMB 20191121

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
import logging

logging.root.setLevel(logging.DEBUG)
logging.root.addHandler(logging.StreamHandler())

binpath = os.path.dirname(os.path.realpath(sys.argv[0])) + '/'
# HACK, should crawl up
if 'install' in binpath:
    datapath = os.path.realpath(binpath + '../../data') + '/'
else:
    datapath = os.path.realpath(binpath + '../data') + '/'

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


agilent = namakanui.agilent.Agilent(datapath+'agilent.ini', time.sleep, mypub, simulate=0)
agilent.log.setLevel(logging.INFO)
agilent.set_dbm(agilent.safe_dbm)
agilent.set_output(1)

photonics = namakanui.photonics.Photonics(datapath+'photonics.ini', time.sleep, mypub, simulate=0)
photonics.log.setLevel(logging.INFO)
photonics.set_attenuation(photonics.max_att)

ifswitch = namakanui.ifswitch.IFSwitch(datapath+'ifswitch.ini', time.sleep, mypub, simulate=0)
ifswitch.set_band(args.band)
ifswitch.close()  # done with ifswitch

cart = namakanui.cart.Cart(args.band, datapath+'band%d.ini'%(args.band), time.sleep, mypub, simulate=0)
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


def adjust_att(lo_ghz):
    
    # sanity check, config values as of 20191121:
    # b3, ala'ihi: 73.266 -  88.578 GHz
    # b6, u'u:    219.996 - 265.842 GHz
    # b7 aweoweo: 281.088 - 366.750 GHz
    lo_ghz_range = {3:[73.3,88.5], 6:[220.1,265.8], 7:[281.1,366.7]}[args.band]
    if lo_ghz < lo_ghz_range[0] or lo_ghz > lo_ghz_range[1]:
        logging.error('skipping lo_ghz %g, outside range %s for band %d', lo_ghz, lo_ghz_range, args.band)
        return
    
    delay = .05
    fyig = lo_ghz / (cart.cold_mult * cart.warm_mult)
    fsig = (fyig*cart.warm_mult + floog) / agilent.harmonic
    #agilent.set_hz(fsig*1e9)  # might not be safe here
    hz = fsig*1e9
    #dbm = agilent.interp_dbm(args.band, lo_ghz)
    dbm = agilent.interp_dbm(0, fsig)  # use photonics table
    logging.info('lo_ghz %g, ref ghz %.6f, dbm %g', lo_ghz, fsig, dbm)
    
    # get starting att value
    att = args.att
    if use_ini:
        att += photonics.interp_attenuation(args.band, lo_ghz)
    
    if att < 0:
        att = 0
    elif att > photonics.max_att:
        att = photonics.max_att
    
    # try to do this safely without going all the way back to max_att.
    # if increasing power output, set the frequency first.
    # if decreasing power output, set the attenuation first.
    if att < photonics.state['attenuation']:
        agilent.set_hz_dbm(hz, dbm)
        photonics.set_attenuation(att)
    else:
        photonics.set_attenuation(att)
        agilent.set_hz_dbm(hz, dbm)
    
    # increase power output until we find an initial lock.
    # assuming this is a 6-bit 31.5 dB attenuator, 4 counts = 2 dB steps.
    att += 4
    while att > 0:
        att -= 4
        if att < 0:
            att = 0
        logging.info('lo_ghz %g, att %g', lo_ghz, att)
        photonics.set_attenuation(att)
        time.sleep(delay)
        try:
            cart.tune(lo_ghz, 0.0)
            break
        except RuntimeError as e:
            logging.error('tune error: %s, IF power: %g', e, cart.state['pll_if_power'])
    
    time.sleep(delay)
    cart.update_all()
    if cart.state['pll_unlock']:
        photonics.set_attenuation(photonics.max_att)
        agilent.set_dbm(agilent.safe_dbm)
        logging.error('failed to lock at %g', lo_ghz)
        return
    logging.info('LOCKED, att=%d, pll_if_power=%g', att, cart.state['pll_if_power'])
    
    # quickly reduce power if initial lock is too strong, 2 counts = 1 dB steps.
    while cart.state['pll_if_power'] <= -1.5 and att < photonics.max_att and not cart.state['pll_unlock']:
        att += 2
        if att > photonics.max_att
            att = photonics.max_att
        photonics.set_attenuation(att)
        time.sleep(delay)
        cart.update_all()
        logging.info('lowering power, att=%d, pll_if_power=%g', att, cart.state['pll_if_power'])
        if cart.state['pll_unlock']:
            logging.error('lost lock, relocking...')
            try:
                cart.tune(lo_ghz, 0.0)
                time.sleep(delay)
                cart.update_all()
            except RuntimeError as e:
                logging.error('tune error: %s', e)
                break   
    
    # slowly increase power to target, 1 count = .5 dB steps.
    while cart.state['pll_if_power'] > -1.5 and att > 0 and not cart.state['pll_unlock']:
        att -= 1
        photonics.set_attenuation(att)
        time.sleep(delay)
        cart.update_all()
        logging.info('raising power, att=%d, pll_if_power=%g', att, cart.state['pll_if_power'])
        if cart.state['pll_unlock']:
            logging.error('lost lock, relocking...')
            try:
                cart.tune(lo_ghz, 0.0)
                time.sleep(delay)
                cart.update_all()
            except RuntimeError as e:
                logging.error('tune error: %s', e)
                break
    
    if cart.state['pll_unlock']:
        photonics.set_attenuation(photonics.max_att)
        agilent.set_dbm(agilent.safe_dbm)
        logging.error('lost lock at %g', lo_ghz)
        return
    #print(lo_ghz, att, cart.state['pll_if_power'])
    sys.stdout.write('%.3f %d %.3f %.3f %.3f\n' % (lo_ghz, att, cart.state['pll_if_power'], cart.state['pa_drain_s'][0], cart.state['pa_drain_s'][1]))
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
        agilent.set_dbm(agilent.safe_dbm)
        logging.error('final retune exception: %s', e)

# show the last dbm and attenuation setting
agilent.update()
logging.info('final dbm: %.2f', agilent.state['dbm'])
photonics.update()
logging.info('final att: %d', photonics.state['attenuation'])

logging.info('done.')





