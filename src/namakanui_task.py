#!/local/python3/bin/python3
'''
namakanui_task.py   20181016 RMB

Engineering control task for the Namakanui instrument.

 86 GHz: Ala'ihi
230 GHz: U'u
345 GHz: Aweoweo


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
import drama
import sys
import os
import time
import json
import redis
from datetime import datetime as dt
from functools import wraps
import namakanui.instrument
import namakanui.util

# definitely want this, so import it here.
# other scripts are imported by their actions.
import namakanui_tune

import argparse
parser = argparse.ArgumentParser()
parser.add_argument('taskname')
args = parser.parse_args()
taskname = args.taskname

import drama.log
drama.log.setup(taskname)  # save to file in /jac_logs
import logging
log = logging.getLogger(taskname)
#logging.getLogger('drama').setLevel(logging.DEBUG)

import redis
import json
from datetime import datetime as dt

redis_client = None
redis_pubsub = None
redis_prefix = ''

def publish(name, value):
    '''Combined publish to both DRAMA and Redis.'''
    score = float(dt.utcnow().timestamp())
    # insert score into value to ensure uniqueness
    value['utc_stamp'] = score
    drama.set_param(name, value)
    redis_client.zadd(redis_prefix + name, {json.dumps(value): score})

def redis_callback(fd):
    '''
    Process Redis pubsub messages.
    When the temp_mon.py service updates the Redis database,
    it will also publish on a channel of the same name.
    So when we see a message here, we must still query the associated key.
    '''
    # just in case we get called when connection closes
    if not redis_client or not redis_pubsub:
        return
    # read all immediately-available messages;
    # for each message, get the highest-score (most recent) data from zset.
    # this will trigger for type=subscribe too, which is fine.
    msg = redis_pubsub.get_message()
    while msg:
        for name in ['LAKESHORE', 'VACUUM', 'COMPRESSOR']:
            if name in msg['channel']:
                # NOTE: we publish score as msg['data'], so could use it
                #       to index the zset instead of just taking highest
                s = redis_client.zrange(redis_prefix + name, -1, -1)[0]
                value = json.loads(s)
                drama.set_param(name, value)
        msg = redis_pubsub.get_message()
    return
    # redis_callback
    


binpath, datapath = namakanui.util.get_paths()

initialised = False
inifile = datapath + 'task.ini'
instrument = None


def try_kick(task, action):
    '''Kick an action, ignoring DramaException.'''
    log.debug('try_kick(%s, %s)', task, action)
    try:
        drama.kick(task, action).wait()
    except drama.DramaException:
        pass


def INITIALISE(msg):
    '''Create and initialise instrument.
       Arguments:
        INITIALISE: The ini file path
        SIMULATE: Mask, bitwise ORed with config settings.
    '''
    global initialised, inifile, instrument
    global redis_client, redis_pubsub, redis_prefix
    
    log.debug('INITIALISE(%s)', msg.arg)
    
    args,kwargs = drama.parse_argument(msg.arg)
    
    initialised = False
    
    if 'INITIALISE' in kwargs:
        inifile = kwargs['INITIALISE']
    
    simulate = 0
    if 'SIMULATE' in kwargs:
        simulate = int(kwargs['SIMULATE'])
    
    # kill the UPDATE actions while we fire things up
    try_kick(taskname, "UPDATE_HW")
    try_kick(taskname, "UPDATE_CARTS")
    try_kick(taskname, "UPDATE_BAND")
    
    # inifile is probably not a preparsed config, but check anyway
    if not hasattr(inifile, 'items'):
        inifile = IncludeParser(inifile)
    
    # (re)connect redis client and subscribe to temp_mon.py channels
    if redis_pubsub:
        if redis_pubsub.connection and hasattr(redis_pubsub.connection, '_sock'):
            # with callback=None, unregisters this file descriptor
            drama.register_callback(redis_pubsub.connection._sock, None)
        redis_pubsub.unsubscribe()
        redis_pubsub.close()
        redis_pubsub = None
    if redis_client:
        redis_client.close()
        redis_client = None
    rconfig = inifile['redis']
    redis_prefix = rconfig['prefix']
    redis_client = redis.Redis(host=rconfig['host'], port=int(rconfig['port']),
                               db=int(rconfig['db']), decode_responses=True)
    redis_pubsub = redis_client.pubsub()
    redis_pubsub.subscribe(redis_prefix + 'LAKESHORE',
                           redis_prefix + 'VACUUM',
                           redis_prefix + 'COMPRESSOR')
    drama.register_callback(redis_pubsub.connection._sock, redis_callback)
    
    # (re)initialise the instrument instance
    if instrument:
        instrument.initialise(inifile, simulate)
    else:
        instrument = namakanui.instrument.Instrument(inifile, drama.wait, publish, simulate)
    
    # publish the load.positions table for the GUI
    drama.set_param('LOAD_TABLE', instrument.load.positions)
    
    # redundant, but might as well publish this top-level
    drama.set_param('SIMULATE', instrument.simulate)
    
    # restart the update loops
    drama.blind_obey(taskname, "UPDATE_HW")
    drama.blind_obey(taskname, "UPDATE_CARTS")
    drama.blind_obey(taskname, "UPDATE_BAND")
    
    initialised = True
    log.info('initialised.')
    # INITIALISE


def check_init():
    '''Raise an exception if INITIALISE not called yet.'''
    if not initialised:
        raise drama.BadStatus(drama.APP_ERROR, 'task needs INITIALISE')


def update_action(delay):
    '''
    Decorator for UPDATE_* actions to handle common overhead.
    Parameters:
      delay: Initial reschedule delay after first OBEY
    '''
    def decorator(f):
        @wraps(f)
        def wrapper(*args):
            msg = args[-1]  # allow for 'self' if f is a method
            act = f.__name__  # could ask drama instead
            if msg.reason == drama.REA_KICK:
                log.debug('%s kicked', act)
                return
            check_init()
            if msg.reason == drama.REA_OBEY:
                log.debug('%s started', act)
                drama.reschedule(delay)
                return
            elif msg.reason == drama.REA_RESCHED:
                log.debug('%s resched', act)
                f(*args)
            else:
                # unexpected msg will kill the action
                log.error('%s unexpected msg: %s', act, msg)
            return
        return wrapper
    return decorator
    # update_action


@update_action(3.0)
def UPDATE_HW(msg):
    '''Update non-receiver hardware with 10s period.'''
    delay = 10.0 / (len(instrument.hardware) or 1.0)
    try:
        instrument.update_one_hw()
    except:
        log.exception('UPDATE_HW exception')
    drama.reschedule(delay)
    # UPDATE_HW


@update_action(2.0)
def UPDATE_CARTS(msg):
    '''Update all carts with 20s period.'''
    carts = list(instrument.carts.values())
    nfuncs = len(carts[0].update_functions) if carts else 0
    delay = 20.0 / (len(carts)*nfuncs or 1.0)
    try:
        instrument.update_one_cart()
    except:
        log.exception('UPDATE_CARTS exception')
    drama.reschedule(delay)
    # UPDATE_CARTS


@update_action(1.0)
def UPDATE_BAND(msg):
    '''Update currently-selected band with 5s period.'''
    delay = 1.5
    try:
        band = instrument.stsr.state['band']
        if band in instrument.carts:
            cart = instrument.carts[band]
            nfuncs = len(cart.update_functions)
            delay = 5.0 / nfuncs
            cart.update_one()
    except:
        log.exception('UPDATE_BAND exception')
    drama.reschedule(delay)
    # UPDATE_BAND



# TODO: my naming scheme isn't very consistent

def set_sg_dbm_args(dbm):
    return float(dbm)

def SET_SG_DBM(msg):
    '''Set Reference output power in dBm.'''
    log.debug('SET_SG_DBM(%s)', msg.arg)
    check_init()
    args,kwargs = drama.parse_argument(msg.arg)
    dbm = set_sg_dbm_args(*args,**kwargs)
    log.info('setting reference dbm to %g', dbm)
    instrument.reference.set_dbm(dbm)
    instrument.reference.update(publish_only=True)

def set_sg_hz_args(hz):
    return float(hz)

def SET_SG_HZ(msg):
    '''Set Reference output frequency in Hz.'''
    log.debug('SET_SG_HZ(%s)', msg.arg)
    check_init()
    args,kwargs = drama.parse_argument(msg.arg)
    hz = set_sg_hz_args(*args,**kwargs)
    if hz < 9e3 or hz > 32e9:
        raise ValueError(f'hz {hz} outside [9 KHz, 32 GHz] range')
    log.info('setting reference hz to %g', hz)
    instrument.reference.set_hz(hz)
    instrument.reference.update(publish_only=True)

def set_sg_out_args(out):
    return int(bool(out))

def SET_SG_OUT(msg):
    '''Set Reference output on (1) or off (0).'''
    log.debug('SET_SG_OUT(%s)', msg.arg)
    check_init()
    args,kwargs = drama.parse_argument(msg.arg)
    out = set_sg_out_args(*args,**kwargs)
    log.info('setting reference output to %d', out)
    instrument.reference.set_output(out)
    instrument.reference.update(publish_only=True)


def set_att_args(att):
    return int(att)

def SET_ATT(msg):
    '''Set Photonics attenuator counts.'''
    log.debug('SET_ATT(%s)', msg.arg)
    check_init()
    args,kwargs = drama.parse_argument(msg.arg)
    att = set_att_args(*args,**kwargs)
    log.info('setting attenuator counts to %d', att)
    instrument.photonics.set_attenuation(att)  # calls update()    


def set_band_args(band):
    return int(band)

def SET_BAND(msg):
    '''Set STSR to given band.  If this would change the selection,
       sets reference signal to a safe level to avoid high power to mixer.'''
    log.debug('SET_BAND(%s)', msg.arg)
    check_init()
    args,kwargs = drama.parse_argument(msg.arg)
    band = set_band_args(*args,**kwargs)
    instrument.set_band(band)


def LOAD_HOME(msg):
    '''Home the load stage.  No arguments.
       NOTE: This can twist up any wires running to the load stage,
             e.g. for a tone source. Supervise as needed.
    '''
    log.debug('LOAD_HOME')
    check_init()
    if msg.reason == drama.REA_OBEY:
        log.info('homing load...')
        instrument.load.home()
        log.info('load homed.')
    else:
        log.error('LOAD_HOME stopping load due to unexpected msg %s', msg)
        instrument.load.stop()
    # LOAD_HOME


def load_move_args(position):
    return position

def LOAD_MOVE(msg):
    '''Move the load.  Arguments:
            position:  Named position or absolute encoder counts.
    '''
    log.debug('LOAD_MOVE(%s)', msg.arg)
    check_init()
    load = instrument.load
    if msg.reason == drama.REA_OBEY:
        args,kwargs = drama.parse_argument(msg.arg)
        pos = load_move_args(*args,**kwargs)
        log.info('moving load to %s...', pos)
        load.move(pos)
        log.info('load at %d, %s.', load.state['pos_counts'], load.state['pos_name'])
    else:
        log.error('LOAD_MOVE stopping load due to unexpected msg %s', msg)
        load.stop()
    # LOAD MOVE


def cart_power_args(band, enable):
    band = int(band)
    if hasattr(enable, 'lower'):
        enable = enable.lower().strip()
        enable = {'0':0, 'off':0, '1':1, 'on':1}[enable]
    else:
        enable = int(bool(enable))
    return band, enable
    
def CART_POWER(msg):
    '''Power a cartridge on or off.  Arguments:
            band: One of 3,6,7
            enable: Can be 1/0, on/off
    '''
    log.debug('CART_POWER(%s)', msg.arg)
    check_init()
    args,kwargs = drama.parse_argument(msg.arg)
    band,enable = cart_power_args(*args,**kwargs)
    bands = instrument.bands
    if band not in bands:
        raise ValueError(f'band {band} not in {bands}')
    onoff = ['off','on'][enable]
    log.info('band %d powering %s...', band, onoff)
    instrument.carts[band].power(enable)
    log.info('band %d powered %s.', band, onoff)
    # CART_POWER


def TUNE(msg):
    '''Tune a cartridge, after setting reference frequency.
       See namakanui_tune.py for arguments.
    '''
    log.debug('TUNE(%s)', msg.arg)
    check_init()
    args,kwargs = drama.parse_argument(msg.arg)
    namakanui_tune.tune(instrument, *args, **kwargs)
    # TUNE


def DEFLUX(msg):
    '''Deflux a cartridge by demagnetizing and heating.
       See namakanui_deflux.py for arguments.
    '''
    log.debug('DEFLUX(%s)', msg.arg)
    check_init()
    args,kwargs = drama.parse_argument(msg.arg)
    import namakanui_deflux
    namakanui_deflux.deflux(instrument, *args, **kwargs)
    # DEFLUX


def IS_ACTIVE(msg):
    '''Check if given action is active.
       For external tasks, this should be quicker than using HELP.
    '''
    log.debug('IS_ACTIVE(%s)', msg.arg)
    args,kwargs = drama.parse_argument(msg.arg)
    def IS_ACTIVE_ARGS(action):
        return action
    action = IS_ACTIVE_ARGS(*args,**kwargs)
    return drama.is_active(taskname, action)



try:
    log.info('%s starting drama.', taskname)
    drama.init(taskname,
               tidefile = datapath+'namakanui.tide',
               buffers = [64000, 8000, 8000, 2000],
               actions=[INITIALISE,
                        UPDATE_HW, UPDATE_CARTS, UPDATE_BAND,
                        SET_SG_DBM, SET_SG_HZ, SET_SG_OUT,
                        SET_ATT,
                        SET_BAND,
                        LOAD_HOME, LOAD_MOVE,
                        CART_POWER,
                        TUNE,
                        DEFLUX,
                        IS_ACTIVE])
    log.info('%s entering main loop.', taskname)
    drama.run()
except:
    log.exception('%s fatal exception', taskname)
    sys.exit(1)
finally:
    drama.stop()
    log.info('%s done.', taskname)

