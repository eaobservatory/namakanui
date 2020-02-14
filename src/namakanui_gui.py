#!/local/python3/bin/python3
'''
namakanui_gui.py
RMB 20190828

Tkinter GUI for Namakanui DRAMA tasks.

need retry monitors on the following:

NAMAKANUI.LOAD
NAMAKANUI.IFSWITCH
NAMAKANUI.AGILENT
<BANDx3>.DYN_STATE

state update handler can basically be identical for each band, with just
a few minor differences.  so maybe make a BandTab class to hold all the
widgets and state variables.  pass it DYN_STATE updates.

each band still needs a separate action entry point so the RESCHED timeout
thing works as it should.  if a RetryMonitor shares an action with another,
it might never see a RESCHED at all.  it ought to be okay to share with
other monitors for the same task, however.
'''

import jac_sw
import drama
import drama.retry

from tkinter import ttk  # for Notebook (tabbed interface)
import tkinter as tk
from tkinter.scrolledtext import ScrolledText

import sys
import os
import time
taskname = 'NG_%d'%(os.getpid())

# TODO add some way to change debug levels
import drama.log
import logging
drama.log.setup()
log = logging.getLogger(taskname)
log.setLevel(logging.INFO)
#logging.root.setLevel(logging.DEBUG)
#drama.retry.log.setLevel(logging.DEBUG)
#drama.__drama__._log.setLevel(logging.DEBUG)


# add a new log handler to log to the messages text area.
# instantiated by the App.
class TextboxHandler(logging.Handler):
    def __init__(self, textbox):
        self.textbox = textbox
        textbox.tag_config("d", foreground='gray')
        textbox.tag_config("i", foreground='green')
        textbox.tag_config("w", foreground='yellow')
        textbox.tag_config("e", foreground='red')
        self.tagdict = {logging.DEBUG:'d', logging.INFO:'i', logging.WARNING:'w', logging.ERROR:'e'}
        super().__init__()
        
    def emit(self, record):
        try:
            msg = self.format(record)
            tag = self.tagdict.get(record.levelno, 'd')
            vbar_pos = self.textbox.vbar.get()[1]  # startfrac, endfrac
            at_bottom = (vbar_pos==0) or (vbar_pos==1)  # 0 means empty
            self.textbox.insert('end', msg, tag)
            if at_bottom:
                self.textbox.see('end')  # scroll to bottom
            #if record.levelno < _logging.WARNING:  # TODO green/red
        except tk.TclError:
            # ignore; the window was probably closed.
            pass
        except (KeyboardInterrupt, SystemExit):
            raise
        except:
            self.handleError(record)


namakanui_taskname = 'NAMAKANUI'

state_bg_key = {'normal':'bg', 'disabled':'disabledbackground', 'readonly':'readonlybackground'}
bg_values = ['red', '']

class SetMixin(object):
    '''Mixin class to provide a 'set' function for Label and Entry widgets.'''
    
    def __init__(self, *args, **kwargs):
        self.textvariable = kwargs.get('textvariable', tk.StringVar())
        kwargs['textvariable'] = self.textvariable
        super().__init__(*args, **kwargs)
        # for now, assume state won't change to save time in set()
        self.bg_key = state_bg_key[self['state']]
    
    def set(self, value, okay=None):
        '''
        Set widget text to value, and background color from bool(okay).
        Examples:
            widget.set('0x%x'%(state['simulate']), not state['simulate'])
            widget.set('%.2f'%(state['temperature']), 10.0 <= state['temperature'] <= 30.0)
        '''
        self.textvariable.set(value)
        if okay is not None:
            self[self.bg_key] = bg_values[int(bool(okay))]
    
    def bg(self, color):
        '''Set background color for assumed state.'''
        self[self.bg_key] = color
        

class SetLabel(SetMixin, tk.Label):
    pass

class SetEntry(SetMixin, tk.Entry):
    pass

## add a "set" method to tkinter.Label
#class SetLabel(tk.Label):
    #def bg(self, color):
        #self[state_bg_key[self['state']]] = color
    
    #def set(self, s):
        #self['text'] = s

## add a "set" method to tkinter.Entry with internal textvariable,
## since delete + insert doesn't seem to work without an explicit update.
#class SetEntry(tk.Entry):
    #def __init__(self, *args, **kwargs):
        #super().__init__(*args, **kwargs)
        ##print('%r.__init__(%s, %s)'%(self,args,kwargs))
        #if self['textvariable']:
            #print('already has textvariable')
            #self.textvariable = kwargs['textvariable']
        #else:
            #self.textvariable = tk.StringVar()
            #self['textvariable'] = self.textvariable
    
    #def bg(self, color):
        #self[state_bg_key[self['state']]] = color
    
    #def set(self, s):
        ##self.delete(0, tk.END)
        ##self.insert(0, s)
        ##print('%r.set(%s)'%(self,s))
        #self.textvariable.set(s)


def grid_value(parent, row, column, sticky='', label=False, width=8):
    '''
    Create a SetLabel or SetEntry at row/col and return the widget.
    Note you must still grid_columnconfigure and grid_rowconfigure yourself.
    
    tk.Label widgets can't be selected for copying/pasting,
    so by default we use a 'readonly' Entry widget instead.
    '''
    if label:
        widget = SetLabel(parent)
        widget.grid(row=row, column=column, sticky=sticky)
    else:
        widget = SetEntry(parent, width=width, justify='right', state='readonly')
        widget.grid(row=row, column=column, sticky='nsew')#sticky=sticky)
    return widget


def grid_label(parent, text, row, width=8, label=False):
    '''
    Set up a [text: value] row and return the textvariable.
    Note you must still grid_columnconfigure and grid_rowconfigure yourself.
    TODO: probably want to save these labels so we can turn them red.
    '''
    tk.Label(parent, text=text).grid(row=row, column=0, sticky='nw')
    return grid_value(parent, row=row, column=1, sticky='ne', width=width, label=label)
    

class CryoFrame(tk.Frame):
    def __init__(self, master=None):
        super().__init__(master)
        self.master = master
        self.setup()
    
    def setup(self):
        self.pack(fill='x')
        self.edwards = grid_label(self, 'edwards', 0, label=True)
        self.edwards.set('NO', False)
        #self.edwards.bg('red')
        #tk.Label(self, text='edwards').grid(row=0, column=0, sticky='nw')
        #self.edwards = tk.Label(self, text="NO", bg='red')
        #self.edwards.grid(row=0, column=1, sticky='ne')
        tk.Label(self, text='lakeshore').grid(row=1, column=0, sticky='nw')
        self.lakeshore = tk.Label(self, text="NO", bg='red')
        self.lakeshore.grid(row=1, column=1, sticky='ne')
        self.v_vacuum_unit = grid_value(self, 2, 0, 'nw', label=True)
        self.v_vacuum_s1 = grid_value(self, 2, 1, 'ne')
        self.v_temp1 = grid_label(self, 'coldhead', 3)
        self.v_temp2 = grid_label(self, '4K', 4)
        self.v_temp3 = grid_label(self, '15K', 5)
        self.v_temp4 = grid_label(self, '90K', 6)
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(6, weight=1)
    
    def vacuum_changed(self, state):
        #print(state)
        #print(type(self.v_vacuum_unit))
        #self.edwards['text'] = "YES"
        #self.edwards['bg'] = 'green'
        self.edwards.set("YES")
        self.edwards.bg('green')
        pressure_unit = state['unit']
        if not pressure_unit or pressure_unit == 'none':
            pressure_unit = 'pressure'
        self.v_vacuum_unit.set(pressure_unit)
        self.v_vacuum_s1.set(state['s1'])
        try:
            s1 = float(state['s1'])
            if not 0.0 < s1 < 1e-6:
                raise ValueError
            self.v_vacuum_s1.bg('')
        except (ValueError, TypeError):
            self.v_vacuum_s1.bg('red')
    
    def lakeshore_changed(self, state):
        #print(state)
        #print(type(self.v_temp1))
        self.lakeshore['text'] = "YES"
        self.lakeshore['bg'] = 'green'
        self.v_temp1.set('%.3f'%(state['temp1']), 0.0 < state['temp1'] < 4.0)
        self.v_temp2.set('%.3f'%(state['temp2']), 0.0 < state['temp2'] < 5.0)
        self.v_temp3.set('%.3f'%(state['temp3']), 0.0 < state['temp3'] < 25.0)
        self.v_temp4.set('%.3f'%(state['temp4']), 0.0 < state['temp4'] < 115.0)


class LoadFrame(tk.Frame):
    def __init__(self, master=None):
        super().__init__(master)
        self.master = master
        self.setup()
    
    def setup(self):
        # number simulate sim_text pos_counts pos_name busy homed
        self.pack(fill='x', expand=1)
        status_frame = tk.Frame(self)
        status_frame.pack(fill='x')
        tk.Label(status_frame, text='connected').grid(row=0, column=0, sticky='nw')
        self.connected = tk.Label(status_frame, text="NO", bg='red')
        self.connected.grid(row=0, column=1, sticky='ne')
        self.v_number = grid_label(status_frame, 'number', 1)
        self.v_simulate = grid_label(status_frame, 'simulate', 2)  # TODO sim_text as tooltip
        self.v_pos_counts = grid_label(status_frame, 'pos_counts', 3)
        self.v_pos_name = grid_label(status_frame, 'pos_name', 4)
        self.v_busy = grid_label(status_frame, 'busy', 5)
        self.v_homed = grid_label(status_frame, 'homed', 6)
        status_frame.grid_columnconfigure(0, weight=1)
        status_frame.grid_columnconfigure(1, weight=1)
        status_frame.grid_rowconfigure(6, weight=1)
        cmd_frame = tk.Frame(self)
        cmd_frame.pack(side='right')#fill='x')
        move_frame = tk.Frame(cmd_frame)
        move_frame.pack(fill='x')
        self.combo = ttk.Combobox(move_frame, width=8)
        self.combo.pack(side='left')
        self.move_button = tk.Button(move_frame, text='MOVE')
        self.move_button.pack(side='right')
        def move_callback():
            drama.blind_obey(taskname, "LOAD_MOVE", POSITION=self.combo.get())
        self.move_button['command'] = move_callback
        home_frame = tk.Frame(cmd_frame)
        home_frame.pack(fill='x')
        self.home_button = tk.Button(home_frame, text='HOME')
        self.home_button.pack(side='left')
        def home_callback():
            drama.blind_obey(taskname, "LOAD_HOME")
        self.home_button['command'] = home_callback
        kick_button = tk.Button(home_frame, text='KICK')
        kick_button.pack(side='right')
        def kick_callback():
            drama.blind_kick(namakanui_taskname, "LOAD_HOME")
            drama.blind_kick(namakanui_taskname, "LOAD_MOVE")
        kick_button['command'] = kick_callback
        # LoadFrame.setup
        
    def mon_changed(self, state):
        self.connected['text'] = "YES"
        self.connected['bg'] = 'green'
        self.v_number.set('%d'%(state['number']))
        self.v_simulate.set('0x%x'%(state['simulate']), state['simulate']==0)  # TODO tooltip
        self.v_pos_counts.set('%d'%(state['pos_counts']))
        self.v_pos_name.set(state['pos_name'])
        self.v_busy.set('%d'%(state['busy']))
        if state['busy']:
            self.v_busy.bg('yellow')
        else:
            self.v_busy.bg('')
        self.v_homed.set('%d'%(state['homed']), state['homed'])
    
    def table_changed(self, state):
        # update the position select combo box
        self.combo['values'] = list(state.keys())
        
    # LoadFrame


class AgilentFrame(tk.Frame):
    def __init__(self, master=None):
        super().__init__(master)
        self.master = master
        self.setup()
    
    def setup(self):
        # number simulate sim_text hz dbm output
        self.pack(fill='x')
        status_frame = tk.Frame(self)
        status_frame.pack(fill='x')
        tk.Label(status_frame, text='connected').grid(row=0, column=0, sticky='nw')
        self.connected = tk.Label(status_frame, text="NO", bg='red')
        self.connected.grid(row=0, column=1, sticky='ne')
        self.v_number = grid_label(status_frame, 'number', 1)
        self.v_simulate = grid_label(status_frame, 'simulate', 2)  # TODO sim_text as tooltip
        self.v_dbm = grid_label(status_frame, 'dbm', 3)
        self.v_hz = grid_label(status_frame, 'hz', 4, width=13)
        self.v_output = grid_label(status_frame, 'output', 5)
        status_frame.grid_columnconfigure(0, weight=1)
        status_frame.grid_columnconfigure(1, weight=1)
        status_frame.grid_rowconfigure(5, weight=1)
        # set DBM, HZ, OUTPUT
        cmd_frame = tk.Frame(self)
        cmd_frame.pack(side='right')
        dh_frame = tk.Frame(cmd_frame)
        dh_frame.pack(fill='x')
        #tk.Label(dh_frame, text='dBm: ').grid(row=0, column=0, sticky='w')
        dbm_entry = tk.Entry(dh_frame, width=13, bg='white')
        dbm_entry.grid(row=0, column=1)
        self.dbm_button = tk.Button(dh_frame, text='DBM')
        self.dbm_button.grid(row=0, column=2)
        def dbm_callback():
            drama.blind_obey(taskname, "SET_SG_DBM", float(dbm_entry.get()))
        self.dbm_button['command'] = dbm_callback
        #tk.Label(dh_frame, text='Hz: ').grid(row=1, column=0, sticky='w')
        hz_entry = tk.Entry(dh_frame, width=13, bg='white')
        hz_entry.grid(row=1, column=1)
        self.hz_button = tk.Button(dh_frame, text='HZ')
        self.hz_button.grid(row=1, column=2, sticky='nsew')
        def hz_callback():
            drama.blind_obey(taskname, "SET_SG_HZ", float(hz_entry.get()))
        self.hz_button['command'] = hz_callback
        dh_frame.grid_columnconfigure(0, weight=1)
        dh_frame.grid_columnconfigure(1, weight=1)
        dh_frame.grid_columnconfigure(2, weight=1)
        dh_frame.grid_rowconfigure(2, weight=1)
        out_frame = tk.Frame(cmd_frame)
        out_frame.pack(fill='x')
        #tk.Label(out_frame, text='Output:   ').pack(side='left')
        self.on_button = tk.Button(out_frame, text='ON')
        self.on_button.pack(side='left')
        #tk.Label(out_frame, text='   ').pack(side='left')  # spacer
        self.off_button = tk.Button(out_frame, text='OFF')
        self.off_button.pack(side='right')
        def on_callback():
            drama.blind_obey(taskname, "SET_SG_OUT", 1)
        def off_callback():
            drama.blind_obey(taskname, "SET_SG_OUT", 0)
        self.on_button['command'] = on_callback
        self.off_button['command'] = off_callback
        # AgilentFrame.setup
        
    def mon_changed(self, state):
        self.connected['text'] = "YES"
        self.connected['bg'] = 'green'
        self.v_number.set('%d'%(state['number']))
        self.v_simulate.set('0x%x'%(state['simulate']), state['simulate']==0)  # TODO tooltip
        self.v_hz.set('%.1f'%(state['hz']))
        self.v_dbm.set('%.2f'%(state['dbm']))  # TODO warning?  how?
        self.v_output.set('%d'%(state['output']), state['output'])
    
    # AgilentFrame


class IFSwitchFrame(tk.Frame):
    def __init__(self, master=None):
        super().__init__(master)
        self.master = master
        self.setup()
    
    def setup(self):
        # number simulate sim_text DO AI
        # TODO: supply higher-level status so we don't have to guess
        self.pack(fill='x')
        status_frame = tk.Frame(self)
        status_frame.pack(fill='x')
        tk.Label(status_frame, text='connected').grid(row=0, column=0, sticky='nw')
        self.connected = tk.Label(status_frame, text="NO", bg='red')
        self.connected.grid(row=0, column=1, sticky='ne')
        self.v_number = grid_label(status_frame, 'number', 1)
        self.v_simulate = grid_label(status_frame, 'simulate', 2)  # TODO sim_text as tooltip
        self.v_do = grid_label(status_frame, 'DO', 3)
        self.v_ai = grid_label(status_frame, 'AI', 4)
        status_frame.grid_columnconfigure(0, weight=1)
        status_frame.grid_columnconfigure(1, weight=1)
        status_frame.grid_rowconfigure(4, weight=1)
        cmd_frame = tk.Frame(self)
        cmd_frame.pack(side='right')
        tk.Label(cmd_frame, text='Band: ').pack(side='left')
        def b3_callback():
            drama.blind_obey(taskname, "SET_BAND", 3)
        def b6_callback():
            drama.blind_obey(taskname, "SET_BAND", 6)
        def b7_callback():
            drama.blind_obey(taskname, "SET_BAND", 7)
        self.b3_button = tk.Button(cmd_frame, text='3', command=b3_callback)
        self.b6_button = tk.Button(cmd_frame, text='6', command=b6_callback)
        self.b7_button = tk.Button(cmd_frame, text='7', command=b7_callback)
        self.b3_button.pack(side='left')
        self.b6_button.pack(side='left')
        self.b7_button.pack(side='left')
    
    def mon_changed(self, state):
        self.connected['text'] = "YES"
        self.connected['bg'] = 'green'
        self.v_number.set('%d'%(state['number']))
        self.v_simulate.set('0x%x'%(state['simulate']), state['simulate']==0)  # TODO tooltip
        do = ''.join([str(x) for x in state['DO']])
        okay = do in ('100100', '010010', '001001')
        self.v_do.set(do, okay)
        self.v_ai.set('%.3f'%(state['AI'][0]), 4.0 < state['AI'][0] < 6.0)
    
    # IFSwitchFrame
        

class BandFrame(tk.Frame):
    def __init__(self, band, master=None):
        super().__init__(master)
        self.band = int(band)
        self.master = master
        self.tnames = ['4k', '110k', 'p0', 'spare', '15k', 'p1']
        self.tokay = [(0,5), (70,115), (0,5), (-2,2), (5,30), (0,5)]
        if self.band == 3:
            self.tnames = ['spare', '110k', 'p01', 'spare', '15k', 'wca']
            self.tokay = [(-2,2), (70,115), (0,30), (-2,2), (0,30), (253,323)]
        self.setup()
    
    def setup(self):
        self.pack()
        
        # column frames for organizing the subframes
        c0 = tk.Frame(self)
        c1 = tk.Frame(self)
        c2 = tk.Frame(self)
        c0.pack(side='left', fill='y')
        c1.pack(side='left', fill='y')
        c2.pack(side='left', fill='y')
        
        # status subframe
        status_frame = tk.LabelFrame(c0, text='Status')
        tk.Label(status_frame, text='connected').grid(row=0, column=0, sticky='nw')
        self.connected = tk.Label(status_frame, text="NO", bg='red')
        self.connected.grid(row=0, column=1, sticky='ne')
        self.v_number = grid_label(status_frame, 'number', 1)
        self.v_simulate = grid_label(status_frame, 'simulate', 2)  # TODO sim_text as tooltip
        self.v_fe_mode = grid_label(status_frame, 'fe_mode', 3)  # TODO warn?
        self.v_ppcomm_time = grid_label(status_frame, 'ppcomm_time', 4)
        status_frame.grid_columnconfigure(0, weight=1)
        status_frame.grid_columnconfigure(1, weight=1)
        status_frame.grid_rowconfigure(4, weight=1)
        
        # power subframe
        power_frame = tk.LabelFrame(c0, text='Power')
        power_status = tk.Frame(power_frame)
        power_status.pack(fill='x')
        self.v_pd_enable = grid_label(power_status, 'pd_enable', 0)
        self.v_amc_5v = grid_label(power_status, 'AMC 5v', 1)
        self.v_pa_3v = grid_label(power_status, 'PA 3v', 2)
        self.v_pa_5v = grid_label(power_status, 'PA 5v', 3)
        power_status.grid_columnconfigure(0, weight=1)
        power_status.grid_columnconfigure(1, weight=1)
        power_status.grid_rowconfigure(3, weight=1)
        power_buttons = tk.Frame(power_frame)
        power_buttons.pack(side='right')
        self.power_on_button = tk.Button(power_buttons, text='Enable')#, state='disabled')
        self.power_off_button = tk.Button(power_buttons, text='Disable')#, state='disabled')
        self.power_on_button.pack(side='left')
        self.power_off_button.pack(side='left')
        def power_on_callback():
            drama.blind_obey(taskname, "POWER", BAND=self.band, ENABLE=1)
        def power_off_callback():
            drama.blind_obey(taskname, "POWER", BAND=self.band, ENABLE=0)
        self.power_on_button['command'] = power_on_callback
        self.power_off_button['command'] = power_off_callback
        self.power_action = False  # true if POWER action is active
            
        
        # PA
        pa_frame = tk.LabelFrame(c0, text='PA')
        tk.Label(pa_frame, text='P0').grid(row=0, column=1, sticky='e')
        tk.Label(pa_frame, text='P1').grid(row=0, column=2, sticky='e')
        tk.Label(pa_frame, text='Vs').grid(row=1, column=0, sticky='e')
        tk.Label(pa_frame, text='Vd').grid(row=2, column=0, sticky='e')
        tk.Label(pa_frame, text='Id').grid(row=3, column=0, sticky='e')
        tk.Label(pa_frame, text='Vg').grid(row=4, column=0, sticky='ne')
        self.v_pa_drain_s = []
        self.v_pa_drain_v = []
        self.v_pa_drain_c = []
        self.v_pa_gate_v = []
        for i in range(2):
            self.v_pa_drain_s.append(grid_value(pa_frame, 1, i+1, 'e'))
            self.v_pa_drain_v.append(grid_value(pa_frame, 2, i+1, 'e'))
            self.v_pa_drain_c.append(grid_value(pa_frame, 3, i+1, 'e'))
            self.v_pa_gate_v.append(grid_value(pa_frame, 4, i+1, 'ne'))
        pa_frame.grid_columnconfigure(0, weight=1)
        pa_frame.grid_columnconfigure(1, weight=1)
        pa_frame.grid_columnconfigure(2, weight=1)
        pa_frame.grid_rowconfigure(4, weight=1)
        
        # AMC, presented in a table with friendlier labels.
        # might save a little space by putting 5v in the LabelFrame.
        amc_frame = tk.LabelFrame(c0, text='AMC')
        tk.Label(amc_frame, text='Vd').grid(row=0, column=1, sticky='e')
        tk.Label(amc_frame, text='Id').grid(row=0, column=2, sticky='e')  # can they all be NE?
        tk.Label(amc_frame, text='Vg').grid(row=0, column=3, sticky='e')
        tk.Label(amc_frame, text='A').grid(row=1, column=0, sticky='e')
        self.v_amc_drain_a_v = grid_value(amc_frame, 1, 1, 'e')
        self.v_amc_drain_a_c = grid_value(amc_frame, 1, 2, 'e')
        self.v_amc_gate_a_v = grid_value(amc_frame, 1, 3, 'e')
        tk.Label(amc_frame, text='B').grid(row=2, column=0, sticky='e')
        self.v_amc_drain_b_v = grid_value(amc_frame, 2, 1, 'e')
        self.v_amc_drain_b_c = grid_value(amc_frame, 2, 2, 'e')
        self.v_amc_gate_b_v = grid_value(amc_frame, 2, 3, 'e')
        tk.Label(amc_frame, text='E').grid(row=3, column=0, sticky='e')
        self.v_amc_drain_e_v = grid_value(amc_frame, 3, 1, 'e')
        self.v_amc_drain_e_c = grid_value(amc_frame, 3, 2, 'e')
        self.v_amc_gate_e_v = grid_value(amc_frame, 3, 3, 'e')
        tk.Label(amc_frame, text='D').grid(row=4, column=0, sticky='ne')
        self.v_amc_mult_d_v = grid_value(amc_frame, 4, 1, 'ne')
        self.v_amc_mult_d_c = grid_value(amc_frame, 4, 2, 'ne')
        amc_frame.grid_columnconfigure(0, weight=1)
        amc_frame.grid_columnconfigure(1, weight=1)
        amc_frame.grid_columnconfigure(2, weight=1)
        amc_frame.grid_columnconfigure(3, weight=1)
        amc_frame.grid_rowconfigure(4, weight=1)
        
        # cart temperatures, broken out (including pll).  TODO skip spares.
        temp_frame = tk.LabelFrame(c1, text='Temperature (K)')
        self.v_pll_temp = grid_label(temp_frame, 'pll', 0)
        self.v_cart_temp = []
        for i,n in enumerate(self.tnames):
            self.v_cart_temp.append(grid_label(temp_frame, n, i+1))
        temp_frame.grid_columnconfigure(0, weight=1)
        temp_frame.grid_columnconfigure(1, weight=1)
        temp_frame.grid_rowconfigure(i+1, weight=1)
        
        # PLL, including LO, YIG
        pll_frame = tk.LabelFrame(c1, text='PLL')
        self.v_lo_ghz = grid_label(pll_frame, 'LO GHz', 0, width=14)
        self.v_yig_ghz = grid_label(pll_frame, 'YTO GHz', 1)
        self.v_yto_coarse = grid_label(pll_frame, 'YTO counts', 2)
        self.v_yig_heater_c = grid_label(pll_frame, 'YTO heater', 3)
        self.v_pll_loop_bw = grid_label(pll_frame, 'loop BW', 4)
        self.v_pll_sb_lock = grid_label(pll_frame, 'lock SB', 5)
        self.v_pll_null_int = grid_label(pll_frame, 'null intg.', 6)
        self.v_pll_lock_v = grid_label(pll_frame, 'lock V', 7)
        self.v_pll_corr_v = grid_label(pll_frame, 'corr V', 8)
        self.v_pll_unlock = grid_label(pll_frame, 'unlocked', 9)
        self.v_pll_ref_power = grid_label(pll_frame, 'ref power', 10)
        self.v_pll_if_power = grid_label(pll_frame, 'IF power', 11)
        pll_frame.grid_columnconfigure(0, weight=1)
        pll_frame.grid_columnconfigure(1, weight=1)
        pll_frame.grid_rowconfigure(11, weight=1)
        
        # LNA.  TODO band 3/6 only have a single stage.
        # config file order is Vd, Id, Vg.
        lna_frame = tk.LabelFrame(c2, text='LNA')
        tk.Label(lna_frame, text='P0/S1').grid(row=0, column=1, sticky='e')
        tk.Label(lna_frame, text='P0/S2').grid(row=0, column=2, sticky='e')
        tk.Label(lna_frame, text='P1/S1').grid(row=0, column=3, sticky='e')
        tk.Label(lna_frame, text='P1/S2').grid(row=0, column=4, sticky='e')
        tk.Label(lna_frame, text='Enable').grid(row=1, column=0, sticky='e')
        tk.Label(lna_frame, text='Vd0').grid(row=2, column=0, sticky='e')
        tk.Label(lna_frame, text='Vd1').grid(row=3, column=0, sticky='e')
        tk.Label(lna_frame, text='Vd2').grid(row=4, column=0, sticky='e')
        tk.Label(lna_frame, text='Id0').grid(row=5, column=0, sticky='e')
        tk.Label(lna_frame, text='Id1').grid(row=6, column=0, sticky='e')
        tk.Label(lna_frame, text='Id2').grid(row=7, column=0, sticky='e')
        tk.Label(lna_frame, text='Vg0').grid(row=8, column=0, sticky='e')
        tk.Label(lna_frame, text='Vg1').grid(row=9, column=0, sticky='e')
        tk.Label(lna_frame, text='Vg2').grid(row=10, column=0, sticky='ne')
        # there's got to be a better way
        self.v_lna_enable = []
        self.v_lna_vd0 = []
        self.v_lna_vd1 = []
        self.v_lna_vd2 = []
        self.v_lna_id0 = []
        self.v_lna_id1 = []
        self.v_lna_id2 = []
        self.v_lna_vg0 = []
        self.v_lna_vg1 = []
        self.v_lna_vg2 = []
        for i in range(4):
            self.v_lna_enable.append(grid_value(lna_frame, 1, i+1, 'e'))
            self.v_lna_vd0.append(grid_value(lna_frame, 2, i+1, 'e'))
            self.v_lna_vd1.append(grid_value(lna_frame, 3, i+1, 'e'))
            self.v_lna_vd2.append(grid_value(lna_frame, 4, i+1, 'e'))
            self.v_lna_id0.append(grid_value(lna_frame, 5, i+1, 'e'))
            self.v_lna_id1.append(grid_value(lna_frame, 6, i+1, 'e'))
            self.v_lna_id2.append(grid_value(lna_frame, 7, i+1, 'e'))
            self.v_lna_vg0.append(grid_value(lna_frame, 8, i+1, 'e'))
            self.v_lna_vg1.append(grid_value(lna_frame, 9, i+1, 'e'))
            self.v_lna_vg2.append(grid_value(lna_frame, 10, i+1, 'ne'))
        lna_frame.grid_columnconfigure(0, weight=1)
        lna_frame.grid_columnconfigure(1, weight=1)
        lna_frame.grid_columnconfigure(2, weight=1)
        lna_frame.grid_columnconfigure(3, weight=1)
        lna_frame.grid_columnconfigure(4, weight=1)
        lna_frame.grid_rowconfigure(10, weight=1)
        
        # SIS table.  TODO not for band 3
        sis_frame = tk.LabelFrame(c2, text='SIS')
        tk.Label(sis_frame, text='P0/S1').grid(row=0, column=1, sticky='e')
        tk.Label(sis_frame, text='P0/S2').grid(row=0, column=2, sticky='e')
        tk.Label(sis_frame, text='P1/S1').grid(row=0, column=3, sticky='e')
        tk.Label(sis_frame, text='P1/S2').grid(row=0, column=4, sticky='e')
        tk.Label(sis_frame, text='open loop').grid(row=1, column=0, sticky='e')
        tk.Label(sis_frame, text='mixer mV').grid(row=2, column=0, sticky='e')
        tk.Label(sis_frame, text='mixer uA').grid(row=3, column=0, sticky='e')
        tk.Label(sis_frame, text='magnet V').grid(row=4, column=0, sticky='e')
        tk.Label(sis_frame, text='magnet mA').grid(row=5, column=0, sticky='ne')
        self.v_sis_open_loop = []
        self.v_sis_v = []
        self.v_sis_c = []
        self.v_sis_mag_v = []
        self.v_sis_mag_c = []
        for i in range(4):
            self.v_sis_open_loop.append(grid_value(sis_frame, 1, i+1, 'e'))
            self.v_sis_v.append(grid_value(sis_frame, 2, i+1, 'e'))
            self.v_sis_c.append(grid_value(sis_frame, 3, i+1, 'e'))
            self.v_sis_mag_v.append(grid_value(sis_frame, 4, i+1, 'e'))
            self.v_sis_mag_c.append(grid_value(sis_frame, 5, i+1, 'ne'))
        sis_frame.grid_columnconfigure(0, weight=1)
        sis_frame.grid_columnconfigure(1, weight=1)
        sis_frame.grid_columnconfigure(2, weight=1)
        sis_frame.grid_columnconfigure(3, weight=1)
        sis_frame.grid_columnconfigure(4, weight=1)
        sis_frame.grid_rowconfigure(5, weight=1)
        
        # TUNE command entry and button.  fixed at VOLTAGE=0.
        tune_frame = tk.LabelFrame(c2, text='Tune')
        self.tune_button = tk.Button(tune_frame, text='TUNE B%d'%(self.band))
        self.tune_button.pack(side='right')
        tune_entry = tk.Entry(tune_frame, width=14, bg='white')
        tune_entry.pack(side='right')
        tk.Label(tune_frame, text='LO GHz: ').pack(side='right')
        def tune_callback():
            drama.blind_obey(taskname, "TUNE", BAND=self.band, LO_GHZ=float(tune_entry.get()), VOLTAGE=0.0)
        self.tune_button['command'] = tune_callback
        
        # TODO: better arrangement?
        
        status_frame.pack(fill='x')
        power_frame.pack(fill='x')
        pa_frame.pack(fill='x')
        amc_frame.pack(fill='both', expand=1)
        
        temp_frame.pack(fill='x')
        pll_frame.pack(fill='x')#both', expand=1)
        
        lna_frame.pack(fill='x')
        sis_frame.pack(fill='x')
        tune_frame.pack(fill='both', expand=1)
        
        # BandFrame.setup
        
        
    # TODO: maybe ignore 'okay' for all other fields if simulated.
    def mon_changed(self, state):
        self.connected['text'] = "YES"
        self.connected['bg'] = 'green'
        self.v_number.set('%d'%(state['number']))
        self.v_simulate.set('0x%x'%(state['simulate']), state['simulate']==0)  # TODO tooltip, warning
        # more or less alphabetical order
        self.v_amc_5v.set('%.3f'%(state['amc_5v']), 4.0 < state['amc_5v'] < 6.0)  # TODO tighten up
        # TODO warnings for AMC values?
        self.v_amc_drain_a_c.set('%.3f'%(state['amc_drain_a_c']))
        self.v_amc_drain_a_v.set('%.3f'%(state['amc_drain_a_v']))
        self.v_amc_drain_b_c.set('%.3f'%(state['amc_drain_b_c']))
        self.v_amc_drain_b_v.set('%.3f'%(state['amc_drain_b_v']))
        self.v_amc_drain_e_c.set('%.3f'%(state['amc_drain_e_c']))
        self.v_amc_drain_e_v.set('%.3f'%(state['amc_drain_e_v']))
        self.v_amc_gate_a_v.set('%.3f'%(state['amc_gate_a_v']))
        self.v_amc_gate_b_v.set('%.3f'%(state['amc_gate_b_v']))
        self.v_amc_gate_e_v.set('%.3f'%(state['amc_gate_e_v']))
        self.v_amc_mult_d_c.set('%.3f'%(state['amc_mult_d_c']))
        self.v_amc_mult_d_v.set('%.3f'%(state['amc_mult_d_v']))
        
        self.v_pll_temp.set('%.3f'%(state['pll_temp']+273.15), -20.0 < state['pll_temp'] < 45.0)
        if 40 <= state['pll_temp'] < 45.0:
            self.v_pll_temp.bg('yellow')
        for i,v in enumerate(state['cart_temp']):
            okay = self.tokay[i][0] < v < self.tokay[i][1]
            self.v_cart_temp[i].set('%.3f'%(v), okay)
        
        # TODO need a way to set this, and it really should default to 0 for cold system.
        self.v_fe_mode.set('%d'%(state['fe_mode']))
        
        for i in range(4):  # p0s1 ... p1s2
            self.v_lna_enable[i].set('%d'%(state['lna_enable'][i]), state['lna_enable'][i])
            # TODO okay values for these?
            self.v_lna_vd0[i].set('%.3f'%(state['lna_drain_v'][i*3+0]))
            self.v_lna_vd1[i].set('%.3f'%(state['lna_drain_v'][i*3+1]))
            self.v_lna_vd2[i].set('%.3f'%(state['lna_drain_v'][i*3+2]))
            self.v_lna_id0[i].set('%.3f'%(state['lna_drain_c'][i*3+0]))
            self.v_lna_id1[i].set('%.3f'%(state['lna_drain_c'][i*3+1]))
            self.v_lna_id2[i].set('%.3f'%(state['lna_drain_c'][i*3+2]))
            self.v_lna_vg0[i].set('%.3f'%(state['lna_gate_v'][i*3+0]))
            self.v_lna_vg1[i].set('%.3f'%(state['lna_gate_v'][i*3+1]))
            self.v_lna_vg2[i].set('%.3f'%(state['lna_gate_v'][i*3+2]))
        
        self.v_lo_ghz.set('%.9f'%(state['lo_ghz']), 70 < state['lo_ghz'] < 370)  # TODO band-specific
        
        # TODO tighten these up
        self.v_pa_3v.set('%.3f'%(state['pa_3v']), 2 < abs(state['pa_3v']) < 4)
        self.v_pa_5v.set('%.3f'%(state['pa_5v']), 4 < state['pa_5v'] < 6)
        
        # TODO warning?  at least pa_drain_v?
        for i in range(2):
            self.v_pa_drain_s[i].set('%.3f'%(state['pa_drain_s'][i]))
            self.v_pa_drain_v[i].set('%.3f'%(state['pa_drain_v'][i]))
            self.v_pa_drain_c[i].set('%.3f'%(state['pa_drain_c'][i]))
            self.v_pa_gate_v[i].set('%.3f'%(state['pa_gate_v'][i]))
        
        self.v_pd_enable.set('%d'%(state['pd_enable']), state['pd_enable'])
        if not self.power_action:
            if state['pd_enable']:
                self.power_on_button['state'] = 'disabled'
                self.power_off_button['state'] = 'normal'
            else:
                self.power_on_button['state'] = 'normal'
                self.power_off_button['state'] = 'disabled'
        
        self.v_pll_lock_v.set('%.3f'%(state['pll_lock_v']), 3 < state['pll_lock_v'])
        # for now we will always want correction voltage close to zero;
        # this might change later if we do fancy frequency switching stuff.
        self.v_pll_corr_v.set('%.3f'%(state['pll_corr_v']), -5 < state['pll_corr_v'] < 5)
        self.v_pll_if_power.set('%.3f'%(state['pll_if_power']), -3.0 < state['pll_if_power'] < -0.5)
        self.v_pll_ref_power.set('%.3f'%(state['pll_ref_power']), -3.0 < state['pll_ref_power'] < -0.5)
        
        self.v_pll_loop_bw.set('%d'%(state['pll_loop_bw']))  # TODO warn?
        self.v_pll_null_int.set('%d'%(state['pll_null_int']), state['pll_null_int']==0)
        self.v_pll_sb_lock.set('%d'%(state['pll_sb_lock']))
        self.v_pll_unlock.set('%d'%(state['pll_unlock']), state['pll_unlock']==0)
        
        # TODO what is the typical ping time in practice?
        self.v_ppcomm_time.set('%.6f'%(state['ppcomm_time']), 0 < state['ppcomm_time'] < 0.002)
        
        for i in range(4):
            # TODO warnings, band-specific
            self.v_sis_open_loop[i].set('%d'%(state['sis_open_loop'][i]))
            self.v_sis_c[i].set('%.3f'%(state['sis_c'][i]*1e3))  # mA to uA
            self.v_sis_v[i].set('%.3f'%(state['sis_v'][i]))
            self.v_sis_mag_c[i].set('%.3f'%(state['sis_mag_c'][i]))
            self.v_sis_mag_v[i].set('%.3f'%(state['sis_mag_v'][i]))
        
        self.v_yig_ghz.set('%.9f'%(state['yig_ghz']), 11 < state['yig_ghz'] < 22)
        self.v_yig_heater_c.set('%.3f'%(state['yig_heater_c']))
        self.v_yto_coarse.set('%d'%(state['yto_coarse']))
        
        # BandFrame.mon_changed
 
    # BandFrame


class App(tk.Frame):
    def __init__(self, master=None):
        super().__init__(master)
        self.master = master
        self.pack(fill='both', expand=1)
        self.setup()
        
        msg_formatter = logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s\n')
        self.msg_handler = TextboxHandler(self.messages)
        self.msg_handler.setFormatter(msg_formatter)
        logging.root.addHandler(self.msg_handler)
        
        self.actions = [self.MON_MAIN, self.MON_B3, self.MON_B6, self.MON_B7,
                        self.POWER, self.TUNE, self.LOAD_MOVE, self.LOAD_HOME,
                        self.SET_SG_DBM, self.SET_SG_HZ, self.SET_SG_OUT,
                        self.SET_BAND, self.MSG_TEST]
        
        self.retry_tasknames = drama.retry.RetryMonitor(namakanui_taskname, 'TASKNAMES')
        self.retry_load = drama.retry.RetryMonitor(namakanui_taskname, 'LOAD')
        self.retry_load_table = drama.retry.RetryMonitor(namakanui_taskname, 'LOAD_TABLE')
        self.retry_agilent = drama.retry.RetryMonitor(namakanui_taskname, 'AGILENT')
        self.retry_ifswitch = drama.retry.RetryMonitor(namakanui_taskname, 'IFSWITCH')
        self.retry_vacuum = drama.retry.RetryMonitor(namakanui_taskname, 'VACUUM')
        self.retry_lakeshore = drama.retry.RetryMonitor(namakanui_taskname, 'LAKESHORE')
        
        # temporary tasknames; will be set on TASKNAMES update
        self.retry_b3 = drama.retry.RetryMonitor('B3_DUMMY', 'DYN_STATE')
        self.retry_b6 = drama.retry.RetryMonitor('B6_DUMMY', 'DYN_STATE')
        self.retry_b7 = drama.retry.RetryMonitor('B7_DUMMY', 'DYN_STATE')
        
        # App.__init__
    
    #def __del__(self):
    #    logging.root.removeHandler(self.msg_handler)

    def setup(self):
        # frame to hold task frames separate from message_frame
        task_frame = tk.Frame(self)
        task_frame.pack()
        
        # columns of NAMAKANUI task frames
        tk.Label(task_frame, text=' ').pack(side='left')  # spacer
        c0 = tk.Frame(task_frame)
        c1 = tk.Frame(task_frame)
        c0.pack(side='left', fill='y')
        tk.Label(task_frame, text=' ').pack(side='left')  # spacer
        c1.pack(side='left', fill='y')
        
        # NAMAKANUI task frame
        #nam_frame = tk.Frame(task_frame)
        #nam_frame.pack(side='left', fill='y')
        
        cryo_parent = tk.LabelFrame(c0, text='CRYO')
        cryo_parent.pack(fill='x')
        self.cryo_frame = CryoFrame(cryo_parent)
        
        tk.Label(c0, text=' ').pack()  # spacer
        
        load_parent = tk.LabelFrame(c0, text='LOAD')
        load_parent.pack(fill='x')
        self.load_frame = LoadFrame(load_parent)
        
        agilent_parent = tk.LabelFrame(c1, text='AGILENT')
        agilent_parent.pack(fill='x')
        self.agilent_frame = AgilentFrame(agilent_parent)
        
        tk.Label(c1, text=' ').pack()  # spacer
        
        ifswitch_parent = tk.LabelFrame(c1, text='IFSWITCH')
        ifswitch_parent.pack(fill='x')
        self.ifswitch_frame = IFSwitchFrame(ifswitch_parent)
        
        tk.Label(task_frame, text=' ').pack(side='left')  # spacer
        
        # CARTRIDGE tasks, tabbed interface
        self.notebook = ttk.Notebook(task_frame)
        self.b3_frame = BandFrame(3, self.notebook)
        self.b6_frame = BandFrame(6, self.notebook)
        self.b7_frame = BandFrame(7, self.notebook)
        self.notebook.add(self.b3_frame, text='B3')
        self.notebook.add(self.b6_frame, text='B6')
        self.notebook.add(self.b7_frame, text='B7')
        self.notebook.pack(side='left')
        
        # rebind <<NotebookTabChanged>> event to avoid autoselecting first Entry
        def handle_tab_changed(event):
            # get the focused widget and clear its selection
            try:
                f = event.widget.focus_get()
                f.selection_clear()
            except AttributeError:
                pass
            # defocus by focusing on something else
            self.master.focus()
        
        self.notebook.bind("<<NotebookTabChanged>>", handle_tab_changed)
        
        tk.Label(task_frame, text=' ').pack(side='left')  # spacer
        
        # scrolled text for message window
        message_frame = tk.LabelFrame(self, text='MESSAGES')
        message_frame.pack(fill='both', expand=1)
        self.messages = ScrolledText(message_frame, height=8, bg='black', fg='gray')
        self.messages.pack(fill='both', expand=1)
        #self.messages.insert('end', 'test')
        
        # App.setup
        
    
    def start_monitors(self):
        # MON_MAIN will start MON_B3 etc when it gets cartridge tasknames
        drama.blind_obey(taskname, 'MON_MAIN')
    
    def MON_MAIN(self, msg):
        '''Calls handle() on all NAMAKANUI RetryMonitors.'''
        
        log.debug('MON_MAIN msg: %s', msg)
        
        # if UPDATE isn't running, monitors will continuously timeout.
        updating = True
        if msg.reason == drama.REA_OBEY or msg.reason == drama.REA_RESCHED:
            try:
                updating = drama.is_active(namakanui_taskname, "UPDATE", 3.0)
                if not updating:
                    e = namakanui_taskname + '.UPDATE not active'
                    log.error(e)
            except drama.BadStatus:
                pass  # for other errors, handle() as usual
        
        if updating and self.retry_tasknames.handle(msg):
            # tasknames changed; cancel old monitors if connected
            for t,b,r in [[0,3,self.retry_b3], [1,6,self.retry_b6], [2,7,self.retry_b7]]:
                new_taskname = msg.arg['B%d'%(b)]
                if r.task == new_taskname:
                    continue
                if r.connected:
                    r.cancel()
                r.task = new_taskname
                drama.blind_obey(taskname, 'MON_B%d'%(b))
                self.notebook.tab(t, text=new_taskname)
                
        
        if updating and self.retry_vacuum.handle(msg):
            self.cryo_frame.vacuum_changed(msg.arg)
        
        if updating and self.retry_lakeshore.handle(msg):
            self.cryo_frame.lakeshore_changed(msg.arg)
        
        if updating and self.retry_load.handle(msg):
            self.load_frame.mon_changed(msg.arg)
        
        if updating and self.retry_load_table.handle(msg):
            self.load_frame.table_changed(msg.arg)
        
        if updating and self.retry_agilent.handle(msg):
            self.agilent_frame.mon_changed(msg.arg)
        
        if updating and self.retry_ifswitch.handle(msg):
            self.ifswitch_frame.mon_changed(msg.arg)
            
        # set disconnected indicators on all frames
        if not updating or not self.retry_vacuum.connected:
            self.cryo_frame.edwards['text'] = "NO"
            self.cryo_frame.edwards['bg'] = 'red'
        if not updating or not self.retry_lakeshore.connected:
            self.cryo_frame.lakeshore['text'] = "NO"
            self.cryo_frame.lakeshore['bg'] = 'red'
        if not updating or not self.retry_load.connected:
            self.load_frame.connected['text'] = "NO"
            self.load_frame.connected['bg'] = 'red'
        if not updating or not self.retry_agilent.connected:
            self.agilent_frame.connected['text'] = "NO"
            self.agilent_frame.connected['bg'] = 'red'
        if not updating or not self.retry_ifswitch.connected:
            self.ifswitch_frame.connected['text'] = "NO"
            self.ifswitch_frame.connected['bg'] = 'red'
        
        drama.reschedule(15.0)  # NAMAKANUI.UPDATE is pretty slow
        
        # App.MON_MAIN
    
    def mon_cart(self, msg, retry, frame):
        updating = True
        if msg.reason == drama.REA_OBEY or msg.reason == drama.REA_RESCHED:
            try:
                updating = drama.is_active(retry.task, "UPDATE", 3.0)
                if not updating:
                    e = retry.task + '.UPDATE not active'
                    log.error(e)
            except drama.BadStatus:
                pass  # for other errors, handle() as usual
        if updating and retry.handle(msg):
            frame.mon_changed(msg.arg)
        if not updating or not retry.connected:
            frame.connected['text'] = "NO"
            frame.connected['bg'] = 'red'
        drama.reschedule(5.0)
    
    def MON_B3(self, msg):
        self.mon_cart(msg, self.retry_b3, self.b3_frame)
    
    def MON_B6(self, msg):
        self.mon_cart(msg, self.retry_b6, self.b6_frame)
    
    def MON_B7(self, msg):
        self.mon_cart(msg, self.retry_b7, self.b7_frame)
        
    
    def check_msg(self, msg, name):
        '''Log the reply to a drama.obey command.
           Return True if we should keep waiting for a completion message.
        '''
        if msg.reason == drama.REA_MESSAGE:
            log.info('%s: %s', msg.arg['TASKNAME'], '\n'.join(msg.arg['MESSAGE']))
            return True
        elif msg.reason == drama.REA_ERROR:
            # join MESSAGE array according to associated STATUS value
            sm = {}
            for s,m in zip(msg.arg['STATUS'], msg.arg['MESSAGE']):
                if s in sm:
                    sm[s] += '\n' + m
                else:
                    sm[s] = m
            t = msg.arg['TASKNAME']
            for s,m in sm.items():
                status = ''
                if s:
                    status = ' (%d: %s)' % (s, drama.get_status_string(s))
                log.error('%s: %s%s', t, m, status)
            return True
        elif msg.reason == drama.REA_RESCHED:
            log.error('timeout waiting for %s', name)
        elif msg.reason != drama.REA_COMPLETE:
            log.error('unexpected msg from %s: %s', name, msg)
        elif msg.status:
            log.error('bad status from %s: %d: %s', name, msg.status, drama.get_status_string(msg.status))
        return False
        # App.check_msg
    
    def wait_loop(self, transid, timeout, name):
        '''Wait timeout seconds for transid to complete.'''
        wall_timeout = time.time() + timeout
        while(self.check_msg(transid.wait(wall_timeout-time.time()), name)):
            pass
    
    def power_args(self, BAND, ENABLE):
        return int(BAND), int(ENABLE)
    
    def POWER(self, msg):
        # the easy way
        args,kwargs = drama.parse_argument(msg.arg)
        band,enable = self.power_args(*args,**kwargs)
        frame = {3:self.b3_frame, 6:self.b6_frame, 7:self.b7_frame}[band]
        frame.power_action = True
        frame.power_on_button['state'] = 'disabled'
        frame.power_off_button['state'] = 'disabled'
        try:
            drama.interested()  # in MsgOut/ErsOut
            tid = drama.obey(namakanui_taskname, "CART_POWER", BAND=band, ENABLE=enable)
            self.wait_loop(tid, 120, "CART_POWER")
        except:
            log.exception('exception in POWER')
            raise
        finally:
            frame.power_action = False
            # wait for update to reenable buttons
        
        # App.POWER
    
    def tune_args(self, BAND, LO_GHZ, VOLTAGE):
        return int(BAND), float(LO_GHZ), float(VOLTAGE)
    
    def TUNE(self, msg):
        args,kwargs = drama.parse_argument(msg.arg)
        band,lo_ghz,voltage = self.tune_args(*args,**kwargs)
        frame = {3:self.b3_frame, 6:self.b6_frame, 7:self.b7_frame}[band]
        frame.tune_button['state'] = 'disabled'
        try:
            drama.interested()
            tid = drama.obey(namakanui_taskname, "CART_TUNE", BAND=band, LO_GHZ=lo_ghz, VOLTAGE=voltage)
            self.wait_loop(tid, 30, "CART_TUNE")
        except:
            log.exception('exception in TUNE')
            raise
        finally:
            frame.tune_button['state'] = 'normal'
        # App.TUNE
    
    def move_args(self, POSITION):
        return POSITION
    
    def LOAD_MOVE(self, msg):
        args,kwargs = drama.parse_argument(msg.arg)
        pos = self.move_args(*args,**kwargs)
        self.load_frame.move_button['state'] = 'disabled'
        self.load_frame.home_button['state'] = 'disabled'
        try:
            drama.interested()
            tid = drama.obey(namakanui_taskname, "LOAD_MOVE", POSITION=pos)
            self.wait_loop(tid, 30, "LOAD_MOVE")
        except:
            log.exception('exception in LOAD_MOVE')
            raise
        finally:
            self.load_frame.move_button['state'] = 'normal'
            self.load_frame.home_button['state'] = 'normal'
        # App.LOAD_MOVE
    
    def LOAD_HOME(self, msg):
        self.load_frame.move_button['state'] = 'disabled'
        self.load_frame.home_button['state'] = 'disabled'
        try:
            drama.interested()
            tid = drama.obey(namakanui_taskname, "LOAD_HOME")
            self.wait_loop(tid, 30, "LOAD_HOME")
        except:
            log.exception('exception in LOAD_MOVE')
            raise
        finally:
            self.load_frame.move_button['state'] = 'normal'
            self.load_frame.home_button['state'] = 'normal'
        # App.LOAD_MOVE
    
    # TODO: some convenience functions to reduce this boilerplate might be handy
    
    def dbm_args(self, DBM):
        dbm = float(DBM)
        if dbm < -130.0 or dbm > 0.0:
            raise drama.BadStatus(drama.INVARG, 'dbm %g outside [-130, 0] range'%(dbm))
        return dbm
    
    def SET_SG_DBM(self, msg):
        args,kwargs = drama.parse_argument(msg.arg)
        dbm = self.dbm_args(*args,**kwargs)
        self.agilent_frame.dbm_button['state'] = 'disabled'
        try:
            drama.interested()
            tid = drama.obey(namakanui_taskname, "SET_SG_DBM", DBM=dbm)
            self.wait_loop(tid, 5, "SET_SG_DBM")
        except:
            log.exception('exception in SET_SG_DBM')
            raise
        finally:
            self.agilent_frame.dbm_button['state'] = 'normal'
        # App.SET_SG_DBM
    
    def hz_args(self, HZ):
        hz = float(HZ)
        if hz < 9e3 or hz > 32e9:
            raise drama.BadStatus(drama.INVARG, 'hz %g outside [9 KHz, 32 GHz] range'%(hz))
        return hz
    
    def SET_SG_HZ(self, msg):
        args,kwargs = drama.parse_argument(msg.arg)
        hz = self.hz_args(*args,**kwargs)
        self.agilent_frame.hz_button['state'] = 'disabled'
        try:
            drama.interested()
            tid = drama.obey(namakanui_taskname, "SET_SG_HZ", HZ=hz)
            self.wait_loop(tid, 5, "SET_SG_HZ")
        except:
            log.exception('exception in SET_SG_HZ')
            raise
        finally:
            self.agilent_frame.hz_button['state'] = 'normal'
        # App.SET_SG_HZ
    
    def out_args(self, OUT):
        return int(bool(OUT))
    
    def SET_SG_OUT(self, msg):
        args,kwargs = drama.parse_argument(msg.arg)
        out = self.out_args(*args,**kwargs)
        self.agilent_frame.on_button['state'] = 'disabled'
        self.agilent_frame.off_button['state'] = 'disabled'
        try:
            drama.interested()
            tid = drama.obey(namakanui_taskname, "SET_SG_OUT", OUT=out)
            self.wait_loop(tid, 5, "SET_SG_OUT")
        except:
            log.exception('exception in SET_SG_OUT')
            raise
        finally:
            self.agilent_frame.on_button['state'] = 'normal'
            self.agilent_frame.off_button['state'] = 'normal'
        # App.SET_SG_OUT
    
    def band_args(self, BAND):
        band = int(BAND)
        if band not in [3,6,7]:
            raise drama.BadStatus(drama.INVARG, 'BAND %d not one of [3,6,7]' % (band))
        return band
    
    def SET_BAND(self, msg):
        args,kwargs = drama.parse_argument(msg.arg)
        band = self.band_args(*args,**kwargs)
        self.ifswitch_frame.b3_button['state'] = 'disabled'
        self.ifswitch_frame.b6_button['state'] = 'disabled'
        self.ifswitch_frame.b7_button['state'] = 'disabled'
        try:
            drama.interested()
            tid = drama.obey(namakanui_taskname, "SET_BAND", BAND=band)
            self.wait_loop(tid, 5, "SET_BAND")
        except:
            log.exception('exception in SET_BAND')
            raise
        finally:
            self.ifswitch_frame.b3_button['state'] = 'normal'
            self.ifswitch_frame.b6_button['state'] = 'normal'
            self.ifswitch_frame.b7_button['state'] = 'normal'
    
    
    def MSG_TEST(self, msg):
        '''
        Hidden action (use a ditscmd) designed to test the message textbox.
        How many messages can we post before something breaks?
        '''
        if msg.reason == drama.REA_OBEY or msg.reason == drama.REA_RESCHED:
            nchars = len(self.messages.get(1.0, tk.END)) - 1
            nlines = int(self.messages.index(tk.END).split('.')[0]) - 1
            log.info('MSG_TEST: nchars %d, nlines %d', nchars, nlines)
            drama.reschedule(0.01)
    
    # App


try:
    log.info('tk init')
    root = tk.Tk()
    root.title('Namakanui GUI: ' + taskname)
    app = App(root)
    
    log.info('drama.init(%s)', taskname)
    drama.init(taskname, buffers = [256000, 8000, 32000, 2000], actions=app.actions)
    app.start_monitors()
    
    log.info('drama.run()...')
    drama.run()
finally:
    log.info('drama.stop(%s)', taskname)
    drama.stop()
    log.info('done')
        

