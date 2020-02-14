#!/local/python3/bin/python3
'''
20190620 RMB

RTS client task, frontend to Namakanui engineering control task.
The task name will be set from the command line, and will likely be one of

FE_ALAIHI
FE_UU
FE_AWEOWEO

TODO: Fast frequency switching.  How does it work?  Can it be simplified?

'''
import jac_sw
import drama
import drama.rts
import sys
import pprint
import time
import namakanui.sim
import numpy

# taskname argument is required
taskname = sys.argv[1]

import drama.log
drama.log.setup(taskname)  # save to file in /jac_logs
import logging
#logging.getLogger('drama.rts').setLevel(logging.DEBUG)
log = logging.getLogger(taskname)
#log.setLevel(logging.DEBUG)
log.info('startup')

g_band = 0
if '3' in taskname or 'ALAIHI' in taskname.upper():
    g_band = 3
elif '6' in taskname or 'UU' in taskname.upper():
    g_band = 6
elif '7' in taskname or 'AWEOWEO' in taskname.upper():
    g_band = 7
else:
    log.error('unexpected taskname %s, cannot determine band', taskname)
    log.error('exit(1)')
    sys.exit(1)

ANTENNA_TASK = 'PTCS'
NAMAKANUI_TASK = 'NAMAKANUI'
CART_TASK = None  # set by INITIALISE

# import error codes as global vars, e.g. WRAP__WRONG_INSTRUMENT_NAME
wrapper_err_h = '/jac_sw/itsroot/install/wrappers/include/wrapper_err.h'
wrapper_err_d = drama.errors_from_header(wrapper_err_h)
globals().update(wrapper_err_d)
# error number to name lookup -- yagni?
wrapper_err_n = {}
for name,number in wrapper_err_d.items():
    wrapper_err_n[number] = name

# the STATE structure for every frame; field order chosen to match fesim
g_state = { 
#"NUMBER":numpy.int32(0), cannot include here or will override RTS
"DOPPLER":1.0,
"LINE_SOURCE":"OFF",
"LINE_FREQUENCY":250.5,
"LINE_POWER":0.0,
"FREQ_OFFSET":0.0,
"LO_FREQUENCY":0.0,
"LAST_FREQ":numpy.int32(0),  # set for last frame in current state table index, 4-byte int
"LOCKED":"NO",
"LOAD":"SKY",
"FE_STATE":"OFFSETZERO",
# TEMP: need some real values for these
"TEMP_TSPILL":200.786,
"TEMP_AMBIENT":300.0,
"TEMP_LOAD2":250.0,
}

# fill in initial RECEPTOR values; may be modified by INITIALISE
# TODO: maybe at this point these should just be empty strings
if g_band == 3:
    g_state['RECEPTOR_ID1'] = 'NA0'
    g_state['RECEPTOR_ID2'] = 'NA1'
if g_band == 6:
    g_state['RECEPTOR_ID1'] = 'NU0L'
    g_state['RECEPTOR_ID2'] = 'NU0U'
    g_state['RECEPTOR_ID3'] = 'NU1L'
    g_state['RECEPTOR_ID4'] = 'NU1U'
if g_band == 7:
    g_state['RECEPTOR_ID1'] = 'NW0L'
    g_state['RECEPTOR_ID2'] = 'NW0U'
    g_state['RECEPTOR_ID3'] = 'NW1L'
    g_state['RECEPTOR_ID4'] = 'NW1U'
g_state['RECEPTOR_VAL1'] = 'ON'
g_state['RECEPTOR_VAL2'] = 'ON'
if g_band in [6,7]:
    g_state['RECEPTOR_VAL3'] = 'ON'
    g_state['RECEPTOR_VAL4'] = 'ON'

g_sideband = 'USB'
g_rest_freq = 230.538
g_center_freq = 4.0
g_doppler = 1.0
# TODO need an overview of how fast frequency switching works
g_freq_mult = 1.0
g_freq_off_scale = 0.0
# TODO this distinction is meaningless for namakanui
g_mech_tuning = 'NEVER'
g_elec_tuning = 'NEVER'
g_group = 0  # used by SETUP_SEQUENCE if mech/elec_tuning is "GROUP"

# for eSMA/VLBI/EHT the receiver will be tuned manually.
# this setting overrides tuning in configure and setup_sequence.
g_esma_mode = 0


# TODO: do we need this?  no cold load (yet)
t_cold_freq = []
t_cold_temp = []
def interpolate_t_cold(freq):
    if not t_cold_freq:
        return 0.0
    if freq <= t_cold_freq[0]:
        return t_cold_temp[0]
    if freq >= t_cold_freq[-1]:
        return t_cold_temp[-1]
    import bisect
    b = bisect.bisect(t_cold_freq, freq)
    a = b-1
    f = (freq - t_cold_freq[a]) / (t_cold_freq[b] - t_cold_freq[a])
    return t_cold_temp[a] + f*(t_cold_temp[b] - t_cold_temp[a])


def set_state_table(name):
    '''Copy first state table with matching name into MY_STATE_TABLE.'''
    st = drama.get_param('INITIALISE')['frontend_init']['FE_statetable']
    #if not isinstance(st, list):  # or numpy array
    if isinstance(st, dict):
        st = [st]
    mst = [x for x in st if x['name'] == name][0]
    drama.set_param('MY_STATE_TABLE', mst)
    

def check_message(msg, target):
    '''Check msg after a wait() and raise errors if needed.'''
    if msg.reason == drama.REA_RESCHED:
        raise drama.BadStatus(drama.APP_TIMEOUT, f'Timeout waiting for {target}')
    elif msg.reason != drama.REA_COMPLETE:
        raise drama.BadStatus(drama.UNEXPMSG, f'Unexpected reply to {target}: {msg}')
    elif msg.status != 0:
            raise drama.BadStatus(msg.status, f'Bad status from {target}')


def initialise(msg):
    '''
    Callback for the INITIALISE action.
    '''
    log.info('initialise: msg=%s', msg)
    
    if msg.reason == drama.REA_OBEY:
        
        xmlname = msg.arg['INITIALISE']
        initxml = drama.obj_from_xml(xmlname)
        drama.set_param('INITIALISE', initxml)
        if log.isEnabledFor(logging.DEBUG):  # expensive formatting
            log.debug("INITIALISE:\n%s", pprint.pformat(initxml))
        
        global g_esma_mode
        g_esma_mode = int(bool(msg.arg.get('ESMA_MODE', 0)))
        drama.set_param('ESMA_MODE', numpy.int32(g_esma_mode))
        
        initxml = initxml['frontend_init']
        inst = initxml['INSTRUMENT']
        name = inst['NAME']
        if name != taskname:
            raise drama.BadStatus(WRAP__WRONG_INSTRUMENT_NAME,
                'got INSTRUMENT.NAME=%s instead of %s' % (name, taskname))
        
        for i,r in enumerate(inst['receptor']):
            ID = r['id']
            VAL = r['health']  # ON or OFF
            valid_ids = {3: ['NA0', 'NA1'],
                         6: ['NU0L', 'NU1L', 'NU0U', 'NU1U'],
                         7: ['NW0L', 'NW1L', 'NW0U', 'NW1U']}
            if ID not in valid_ids[g_band]:
                raise drama.BadStatus(WRAP__WRONG_RECEPTOR_IN_INITIALISE,
                    'bad INSTRUMENT.receptor.id %s' % (ID))
            g_state['RECEPTOR_ID%d'%(i+1)] = ID
            g_state['RECEPTOR_VAL%d'%(i+1)] = VAL
        
        # fill in the static bits for first cell of STATE table
        cal = initxml['CALIBRATION']
        t_cold = float(cal['T_COLD'])  # K?
        t_spill = float(cal['T_SPILL'])
        t_hot = float(cal['T_HOT'])
        g_state['TEMP_LOAD2'] = t_cold
        g_state['TEMP_TSPILL'] = t_spill
        g_state['TEMP_AMBIENT'] = t_hot
        
        global t_cold_freq, t_cold_temp
        t_cold_table = cal['T_COLD_TABLE']
        t_cold_freq = [float(x['FREQ']) for x in t_cold_table]
        t_cold_temp = [float(x['TEMP']) for x in t_cold_table]
        assert t_cold_freq == sorted(t_cold_freq)
        
        # TODO remove, not used
        manual = inst.get('TUNING','').startswith('MANUAL')
        
        # skipping waveBand stuff
        
        # get name and path to our cartridge task
        global CART_TASK
        msg = drama.get(NAMAKANUI_TASK, 'TASKNAMES').wait(5)
        check_message(msg, f'get({NAMAKANUI_TASK},TASKNAMES)')
        CART_TASK = msg.arg['TASKNAMES'][f'B{g_band}']
        drama.cache_path(CART_TASK)
        
        # get SIMULATE value and mask out the bits we don't care about
        msg = drama.get(NAMAKANUI_TASK, 'SIMULATE').wait(5)
        check_message(msg, f'get({NAMAKANUI_TASK},SIMULATE)')
        simulate = msg.arg['SIMULATE']
        otherbands = [3,6,7]
        otherbands.remove(g_band)
        otherbits = 0
        for band in otherbands:
            for bit in namakanui.sim.bits_for_band(band):
                otherbits |= bit
        simulate &= ~otherbits
        drama.set_param('SIMULATE', numpy.int32(simulate))  # might need to be 4-byte int
        
        # send load to AMBIENT, will fail if not already homed
        pos = f'b{g_band}_hot'
        log.info('moving load to %s...', pos)
        msg = drama.obey(NAMAKANUI_TASK, 'LOAD_MOVE', pos).wait(30)
        check_message(msg, f'obey({NAMAKANUI_TASK},LOAD_MOVE,{pos})')
        g_state['LOAD'] = 'AMBIENT'
        
        # power up the cartridge if necessary. this might take a little while.
        log.info('powering up band %d cartridge...', g_band)
        msg = drama.obey(NAMAKANUI_TASK, 'CART_POWER', g_band, 1).wait(30)
        check_message(msg, f'obey({NAMAKANUI_TASK},CART_POWER,{g_band},1)')
        
        # publish initial parameters; not sure if really needed.
        drama.set_param('LOAD', g_state['LOAD'])
        drama.set_param('STATE', [{'NUMBER':numpy.int32(0), **g_state}])
        drama.set_param('TUNE_PAUSE', numpy.int32(0))  # TODO use this?
        drama.set_param('MECH_TUNE', numpy.int32(0))
        drama.set_param('ELEC_TUNE', numpy.int32(0))
        drama.set_param('LOCK_STATUS', numpy.int32(0))
        drama.set_param('COMB_ON', numpy.int32(0))  # fesim only?
        drama.set_param('LO_FREQ', g_state['LO_FREQUENCY'])
        drama.set_param('REST_FREQUENCY', 0.0)
        drama.set_param('SIDEBAND', 'USB')
        drama.set_param('TEMP_TSPILL', t_spill)
        #drama.set_param('SB_MODE', {3:'SSB',6:'2SB',7:'2SB'}[g_band])
        drama.set_param('SB_MODE', 'SSB')  # debug
        
        # obey
        
    log.info('initialise done.')
    # initialise


def configure(msg, wait_set, done_set):
    '''
    Callback for the CONFIGURE action.
    '''
    log.debug('configure: msg=%s, wait_set=%s, done_set=%s', msg, wait_set, done_set)
    
    global g_sideband, g_rest_freq, g_center_freq, g_doppler
    global g_freq_mult, g_freq_off_scale
    global g_mech_tuning, g_elec_tuning, g_group, g_esma_mode
    
    if msg.reason == drama.REA_OBEY:
        config = drama.get_param('CONFIGURATION')
        if log.isEnabledFor(logging.DEBUG):  # expensive formatting
            log.debug("CONFIGURATION:\n%s", pprint.pformat(config))
        
        config = config['OCS_CONFIG']
        fe = config['FRONTEND_CONFIG']
        init = drama.get_param('INITIALISE')
        init = init['frontend_init']
        inst = init['INSTRUMENT']
        
        # init/config must have same number/order of receptors
        for i,(ir,cr) in enumerate(zip(inst['receptor'],fe['RECEPTOR_MASK'])):
            iid = ir['id']
            cid = cr['RECEPTOR_ID']
            if iid != cid:
                raise drama.BadStatus(WRAP__WRONG_RECEPTOR_IN_CONFIGURE,
                    f'configure RECEPTOR_MASK[{i}].RECEPTOR_ID={cid} but initialise receptor[{i}].id={iid}')
            ival = ir['health']
            cval = cr['VALUE']
            if cval == 'NEED' and ival != 'ON':
                raise drama.BadStatus(WRAP__NEED_BAD_RECEPTOR,
                    f'{cid}: configure RECEPTOR_MASK.VALUE={cval} but initialise receptor.health={ival}')
            if cval == 'ON' and ival == 'OFF':
                raise drama.BadStatus(WRAP__ON_RECEPTOR_IS_OFF,
                    f'{cid}: configure RECEPTOR_MASK.VALUE={cval} but initialise receptor.health={ival}')
            if cval == 'OFF':
                g_state['RECEPTOR_VAL%d'%(i+1)] = 'OFF'
            else:
                g_state['RECEPTOR_VAL%d'%(i+1)] = ival
        
        g_sideband = fe['SIDEBAND']
        if g_sideband not in ['USB','LSB']:
            raise drama.BadStatus(WRAP__UNKNOWN_SIDEBAND, f'SIDEBAND={g_sideband}')
        g_rest_freq = float(fe['REST_FREQUENCY'])
        g_freq_mult = {'USB':1.0, 'LSB':-1.0}[g_sideband]
        # use IF_CENTER_FREQ from config file instead of initialise
        #g_center_freq  = float(inst['IF_CENTER_FREQ'])
        g_center_freq = float(config['INSTRUMENT']['IF_CENTER_FREQ'])
        g_freq_off_scale = float(fe['FREQ_OFF_SCALE'])  # MHz
        dtrack = fe['DOPPLER_TRACK']
        g_mech_tuning = dtrack['MECH_TUNING']
        g_elec_tuning = dtrack['ELEC_TUNING']
        
        drama.set_param('MECH_TUNE', numpy.int32({'NEVER':0, 'NONE':0}.get(g_mech_tuning,1)))
        drama.set_param('ELEC_TUNE', numpy.int32({'NEVER':0, 'NONE':0}.get(g_elec_tuning,1)))
        drama.set_param('REST_FREQUENCY', g_rest_freq)
        drama.set_param('SIDEBAND', g_sideband)
        drama.set_param('SB_MODE', fe['SB_MODE'])
        #drama.set_param('SB_MODE', 'SSB')  # debug
        
        og = ['ONCE', 'GROUP']
        if g_esma_mode:
            configure.tune = False
            wait_set.add(ANTENNA_TASK)
        elif g_mech_tuning in og or g_elec_tuning in og:
            configure.tune = True
            wait_set.add(ANTENNA_TASK)
        else:
            configure.tune = False
            drama.cache_path(ANTENNA_TASK)
        
        # we can save a bit of time by moving the load to AMBIENT
        # while waiting for the ANTENNA_TASK to supply the doppler value.
        # TODO: is this really necessary?
        if configure.tune:
            pos = f'b{g_band}_hot'
            g_state['LOAD'] = ''  # TODO unknown/invalid value; drama.set_param
            log.info('moving load to %s...', pos)
            configure.load_tid = drama.obey(NAMAKANUI_TASK, 'LOAD_MOVE', pos)
            configure.load_target = f'obey({NAMAKANUI_TASK},LOAD_MOVE,{pos})'
            configure.load_timeout = time.time() + 30
            drama.reschedule(configure.load_timeout)
            return
        else:
            configure.load_tid = None
        # obey
    elif msg.reason == drama.REA_RESCHED:  # load must have timed out
        raise drama.BadStatus(drama.APP_TIMEOUT, f'Timeout waiting for {configure.load_target}')
    elif configure.load_tid is not None:
        if msg.transid != configure.load_tid:
            drama.reschedule(configure.load_timeout)
            return
        elif msg.reason != drama.REA_COMPLETE:
            raise drama.BadStatus(drama.UNEXPMSG, f'Unexpected reply to {configure.load_target}: {msg}')
        elif msg.status != 0:
            raise drama.BadStatus(msg.status, f'Bad status from {configure.load_target}')
        g_state['LOAD'] = 'AMBIENT'
        drama.set_param('LOAD', g_state['LOAD'])
        configure.load_tid = None
    
    # TODO: figure out how to generalize this pattern to more obeys.
        
    if ANTENNA_TASK not in wait_set and ANTENNA_TASK not in done_set:
        done_set.add(ANTENNA_TASK)  # once only
        g_doppler = 1.0
    elif ANTENNA_TASK in wait_set and ANTENNA_TASK in done_set:
        wait_set.remove(ANTENNA_TASK)  # once only
        msg = drama.get(ANTENNA_TASK, 'RV_BASE').wait(5)
        check_message(msg, f'get({ANTENNA_TASK},RV_BASE)')
        rv_base = msg.arg['RV_BASE']
        g_doppler = float(rv_base['DOPPLER'])
    else:
        # this is okay to wait on a single task...
        return
    
    g_state['DOPPLER'] = g_doppler
    
    if configure.tune:
        # tune the receiver.
        # TODO: target control voltage for fast frequency switching.
        lo_freq = g_doppler*g_rest_freq - g_center_freq*g_freq_mult
        voltage = 0.0
        g_state['LOCKED'] = 'NO'
        drama.set_param('LOCK_STATUS', numpy.int32(0))
        log.info('tuning receiver LO to %.9f GHz, %.3f V...', lo_freq, voltage)
        msg = drama.obey(NAMAKANUI_TASK, 'CART_TUNE', g_band, lo_freq, voltage).wait(30)
        check_message(msg, f'obey({NAMAKANUI_TASK},CART_TUNE,{g_band},{lo_freq},{voltage})')
        g_state['LOCKED'] = 'YES'
        drama.set_param('LOCK_STATUS', numpy.int32(1))
    else:
        # ask the receiver for its current status.
        # NOTE: no lo_ghz, or being unlocked, is not necessarily an error here.
        msg = drama.get(CART_TASK, 'DYN_STATE').wait(3)
        check_message(msg, f'get({CART_TASK},DYN_STATE)')
        dyn_state = msg.arg['DYN_STATE']
        lo_freq = dyn_state['lo_ghz']
        locked = int(not dyn_state['pll_unlock'])
        g_state['LOCKED'] = ['NO', 'YES'][locked]
        drama.set_param('LOCK_STATUS', numpy.int32(locked))
    
    g_state['LO_FREQUENCY'] = lo_freq
    drama.set_param('LO_FREQ', lo_freq)
    
    # TODO: remove, we don't have a cold load
    t_cold = interpolate_t_cold(lo_freq) or g_state['TEMP_LOAD2']
    g_state['TEMP_LOAD2'] = t_cold
    
    # TODO: do something with g_group?
    # it seems silly to potentially retune immediately in SETUP_SEQUENCE.
    
    log.info('configure done.')
    # configure


def setup_sequence(msg, wait_set, done_set):
    '''
    Callback for SETUP_SEQUENCE action.
    '''
    log.debug('setup_sequence: msg=%s, wait_set=%s, done_set=%s', msg, wait_set, done_set)
    
    global g_sideband, g_rest_freq, g_center_freq, g_doppler
    global g_freq_mult, g_freq_off_scale
    global g_mech_tuning, g_elec_tuning, g_group, g_esma_mode
    
    if msg.reason == drama.REA_OBEY:
        # TODO these can probably be skipped
        init = drama.get_param('INITIALISE')
        init = init['frontend_init']
        cal = init['CALIBRATION']
        t_hot = float(cal['T_HOT'])
        t_cold = float(cal['T_COLD'])
        
        # TODO fast frequency switching
        state_table_name = msg.arg.get('FE_STATE', g_state['FE_STATE'])
        set_state_table(state_table_name)
        g_state['FE_STATE'] = state_table_name
        
        st = drama.get_param('MY_STATE_TABLE')
        state_index_size = int(st['size'])
        fe_state = st['FE_state']
        if not isinstance(fe_state, dict):
            fe_state = fe_state[0]
        offset = float(fe_state['offset'])
        # for now, slow offset only
        if st['name'].startswith('OFFSET'):
            g_state['FREQ_OFFSET'] = offset
        else:
            g_state['FREQ_OFFSET'] = 0.0
        
        setup_sequence.tune = False
        new_group = msg.arg.get('GROUP', g_group)
        if new_group != g_group and 'GROUP' in [g_mech_tuning, g_elec_tuning]:
            setup_sequence.tune = True
        g_group = new_group
        cd = ['CONTINUOUS', 'DISCRETE']
        if g_mech_tuning in cd or g_elec_tuning in cd:
            setup_sequence.tune = True
        
        if g_esma_mode:
            setup_sequence.tune = False
        
        # if PTCS is in TASKS, get updated DOPPLER value --
        # regardless of whether or not we're tuning the receiver.
        if ANTENNA_TASK in drama.get_param("TASKS").split():
            wait_set.add(ANTENNA_TASK)
        else:
            drama.cache_path(ANTENNA_TASK)  # shouldn't actually need this here
        
        # save time by moving load while waiting on doppler from ANTENNA_TASK
        load = msg.arg.get('LOAD', g_state['LOAD'])
        if load == 'LOAD2':
            # TODO: should this raise drama.BadStatus instead?
            # NOTE: LOAD in SDP/STATE still remains "LOAD2",
            #       since otherwise the reducers will hang forever
            #       waiting on LOAD2 data.
            log.warning('no LOAD2, setting to SKY instead')
            pos = 'b%d_sky'%(g_band)
        else:
            pos = 'b%d_%s'%(g_band, {'AMBIENT':'hot', 'SKY':'sky'}[load])
        g_state['LOAD'] = ''  # TODO unknown/invalid value
        log.info('moving load to %s...', pos)
        setup_sequence.load = load
        setup_sequence.load_tid = drama.obey(NAMAKANUI_TASK, 'LOAD_MOVE', pos)
        setup_sequence.load_target = f'obey({NAMAKANUI_TASK},LOAD_MOVE,{pos})'
        setup_sequence.load_timeout = time.time() + 30
        drama.reschedule(setup_sequence.load_timeout)
        
        return {'MULT': numpy.int32(state_index_size)}  # for JOS_MULT
        # obey
    elif msg.reason == drama.REA_RESCHED:  # load must have timed out
        raise drama.BadStatus(drama.APP_TIMEOUT, f'Timeout waiting for {setup_sequence.load_target}')
    elif setup_sequence.load_tid is not None:
        if msg.transid != setup_sequence.load_tid:
            drama.reschedule(setup_sequence.load_timeout)
            return
        elif msg.reason != drama.REA_COMPLETE:
            raise drama.BadStatus(drama.UNEXPMSG, f'Unexpected reply to {setup_sequence.load_target}: {msg}')
        elif msg.status != 0:
            raise drama.BadStatus(msg.status, f'Bad status from {setup_sequence.load_target}')
        g_state['LOAD'] = setup_sequence.load
        # sdp should already hold the desired value, so no set_param here
        setup_sequence.load_tid = None
    
    if ANTENNA_TASK not in wait_set and ANTENNA_TASK not in done_set:
        done_set.add(ANTENNA_TASK)  # once only
        g_doppler = 1.0
    elif ANTENNA_TASK in wait_set and ANTENNA_TASK in done_set:
        wait_set.remove(ANTENNA_TASK)  # once only
        msg = drama.get(ANTENNA_TASK, 'RV_BASE').wait(5)
        check_message(msg, f'get({ANTENNA_TASK},RV_BASE)')
        rv_base = msg.arg['RV_BASE']
        g_doppler = float(rv_base['DOPPLER'])
    else:
        # this is okay to wait on a single task...
        return
    
    g_state['DOPPLER'] = g_doppler
    
    if setup_sequence.tune:
        # tune the receiver.
        # TODO: target control voltage for fast frequency switching.
        lo_freq = (g_doppler*g_rest_freq) - (g_center_freq*g_freq_mult) + (g_freq_off_scale*g_state['FREQ_OFFSET']*1e-3)
        voltage = 0.0
        g_state['LOCKED'] = 'NO'
        drama.set_param('LOCK_STATUS', numpy.int32(0))
        log.info('tuning receiver LO to %.9f GHz, %.3f V...', lo_freq, voltage)
        msg = drama.obey(NAMAKANUI_TASK, 'CART_TUNE', g_band, lo_freq, voltage).wait(30)
        check_message(msg, f'obey({NAMAKANUI_TASK},CART_TUNE,{g_band},{lo_freq},{voltage})')
        g_state['LO_FREQUENCY'] = lo_freq
        drama.set_param('LO_FREQ', lo_freq)
        g_state['LOCKED'] = 'YES'
        drama.set_param('LOCK_STATUS', numpy.int32(1))
    else:
        # make sure rx is tuned and locked.  better to fail here than in SEQUENCE.
        msg = drama.get(CART_TASK, 'DYN_STATE').wait(3)
        check_message(msg, f'get({CART_TASK},DYN_STATE)')
        dyn_state = msg.arg['DYN_STATE']
        lo_freq = dyn_state['lo_ghz']
        locked = int(not dyn_state['pll_unlock'])
        g_state['LO_FREQUENCY'] = lo_freq
        drama.set_param('LO_FREQ', lo_freq)
        g_state['LOCKED'] = ['NO', 'YES'][locked]
        drama.set_param('LOCK_STATUS', numpy.int32(locked))
        if not lo_freq or not locked:
            raise drama.BadStatus(WRAP__RXNOTLOCKED, 'receiver unlocked in setup_sequence')
    
    # TODO: remove, we don't have a cold load
    t_cold = interpolate_t_cold(lo_freq) or g_state['TEMP_LOAD2']
    g_state['TEMP_LOAD2'] = t_cold
    
    # TODO: get TEMP_TSPILL from NAMAKANUI and/or ENVIRO
    msg = drama.get(NAMAKANUI_TASK, 'LAKESHORE').wait(5)
    check_message(msg, f'get({NAMAKANUI_TASK},LAKESHORE)')
    g_state['TEMP_AMBIENT'] = msg.arg['LAKESHORE']['temp5']
    
    log.info('setup_sequence done.')
    # setup_sequence


def sequence(msg):
    '''
    Callback called for every entry to the SEQUENCE action.
    This lets us place monitors on the Namakanui engineering tasks
    without starting a background action from CONFIGURE or SETUP_SEQUENCE.
    '''
    log.debug('sequence: msg=%s', msg)
    
    if msg.reason == drama.REA_OBEY:
        sequence.start = drama.get_param('START')
        sequence.end = drama.get_param('END')
        sequence.dwell = drama.get_param('DWELL')
        sequence.step_counter = sequence.start
        sequence.state_table_index = 0
        sequence.dwell_counter = 0
        
        # start monitor on CART_TASK to track lock status.
        # TODO: do we need a faster update during obs? 5s is pretty slow.
        sequence.cart_tid = drama.monitor(CART_TASK, 'DYN_STATE')
        
        # start monitor on NAMAKANUI.LAKESHORE to get TEMP_AMBIENT
        sequence.lakeshore_tid = drama.monitor(NAMAKANUI_TASK, 'LAKESHORE')
    
    elif msg.reason == drama.REA_TRIGGER and msg.transid == sequence.cart_tid:
        if msg.status == drama.MON_STARTED:
            pass  # lazy, just let the drama dispatcher clean up after us
        elif msg.status == drama.MON_CHANGED:
            # TODO: do we need to check other parameters also?
            if msg.arg['pll_unlock']:
                raise drama.BadStatus(WRAP__RXNOTLOCKED, 'lost lock during sequence')
        else:
            raise drama.BadStatus(msg.status, f'unexpected message for {CART_TASK}.DYN_STATE monitor: {msg}')
    
    elif msg.reason == drama.REA_TRIGGER and msg.transid == sequence.lakeshore_tid:
        if msg.status == drama.MON_STARTED:
            pass  # lazy, just let the drama dispatcher clean up after us
        elif msg.status == drama.MON_CHANGED:
            g_state['TEMP_AMBIENT'] = msg.arg['temp5']
        else:
            raise drama.BadStatus(msg.status, f'unexpected message for {NAMAKANUI_TASK}.LAKESHORE monitor: {msg}')
    
    # sequence


def sequence_frame(frame):
    '''
    Callback for every frame structure in RTS.STATE (endInt).
    Modify the passed frame in-place or return a dict to publish.
    
    Note that we assume a single-element STATE structure,
    so we just copy g_state into every frame.  Even in batch mode
    this would still be correct, but excessive.
    
    TODO: How do we support fast frequency switching?
          The passed-in frame actually provides the following:
            NUMBER
            TAI_START
            TAI_END
            LAST_INTEG
          So we could keep g_state as a timeseries, and figure
          out the appropriate value for each frame.
          Some frames would have LOCKED=NO while the receiver tunes.
          Could probably support batch processing for free in that case,
          though I'd need to double-check the RTS/ACSIS code for how the 
          feed-forward works -- does it only interpolate from the first frame,
          or from the last complete frame it saw?
          
          LAST_FREQ wouldn't necessarily be accurate either; there could
          be a few more frames on the current frequency depending on lag.
          Do we still need the LAST_FREQ field?  Who uses it and how?
    '''
    log.debug('sequence_frame: frame=%s', frame)
    
    # could compare this to start/end for first/last integration handling
    sequence.step_counter = frame['NUMBER']
    
    # update frame with values that were used for this integration
    frame.update(g_state)
    
    # if state will change next frame, set up for it here.
    mst = drama.get_param('MY_STATE_TABLE')
    fe_state = mst['FE_state']
    if isinstance(fe_state, dict):
        fe_state = [fe_state]
    
    old_sti = sequence.state_table_index
    sequence.dwell_counter += 1
    if sequence.dwell_counter == sequence.dwell:
        sequence.dwell_counter = 0
        sequence.state_table_index = (sequence.state_table_index+1) % len(fe_state)
    
    # set LAST_FREQ if this was the last frame at this state table index
    if old_sti != sequence.state_table_index:
        frame['LAST_FREQ'] = numpy.int32(1)
    else:
        frame['LAST_FREQ'] = numpy.int32(0)
    
    # no tuning (fast frequency switching) in ESMA_MODE
    global g_esma_mode
    if g_esma_mode:
        return frame
    
    # skip the rest of this since fast frequency switching isn't supported yet.
    return frame
    
    if old_sti != sequence.state_table_index:
        # TODO: if we're tuning anyway, should we update doppler first?
        offset = float(fe_state[sequence.state_table_index]['offset'])
        g_state['FREQ_OFFSET'] = offset
        lo_freq = (g_doppler*g_rest_freq) - (g_center_freq*g_freq_mult) + (g_freq_off_scale*offset*1e-3)
        # TODO: target control voltage for fast frequency switching.
        voltage = 0.0
        g_state['LOCKED'] = 'NO'
        drama.set_param('LOCK_STATUS', numpy.int32(0))
        drama.set_param('LO_FREQ', lo_freq)
        log.info('tuning receiver LO to %.9f GHz, %.3f V...', lo_freq, voltage)
        msg = drama.obey(NAMAKANUI_TASK, 'CART_TUNE', g_band, lo_freq, voltage).wait(30)
        check_message(msg, f'obey({NAMAKANUI_TASK},CART_TUNE,{g_band},{lo_freq},{voltage})')
        g_state['LO_FREQUENCY'] = lo_freq
        g_state['LOCKED'] = 'YES'
        drama.set_param('LOCK_STATUS', numpy.int32(1))
        # TODO: remove, we don't have a cold load
        t_cold = interpolate_t_cold(lo_freq) or g_state['TEMP_LOAD2']
        g_state['TEMP_LOAD2'] = t_cold
    
    # sequence_frame


def sequence_batch(batch):
    '''
    Callback before publishing a list of frames.  NOP for us.
    '''
    pass


try:
    drama.init(taskname, actions=[])
    drama.rts.init(initialise, configure, setup_sequence, sequence, sequence_frame, sequence_batch)
    # publish initial parameters
    drama.set_param('STATE', [{'NUMBER':numpy.int32(0), **g_state}])
    log.info('entering main loop.')
    drama.run()
finally:
    drama.stop()
    log.info('done.')

