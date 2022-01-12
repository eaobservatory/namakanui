#!/local/python3/bin/python3
'''
namakanui_gui.py    RMB 20190828

Tkinter GUI for Namakanui DRAMA tasks.


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
import drama.retry

from tkinter import ttk  # for Notebook (tabbed interface)
import tkinter as tk
from tkinter.scrolledtext import ScrolledText

import sys
import os
import time
taskname = 'NGUI_%d'%(os.getpid())

# TODO add some way to change debug levels
import drama.log
import logging
drama.log.setup()
log = logging.getLogger(taskname)
log.setLevel(logging.INFO)
#logging.root.setLevel(logging.DEBUG)
#drama.retry.log.setLevel(logging.DEBUG)
#drama.__drama__._log.setLevel(logging.DEBUG)

#namakanui_taskname = 'NAMAKANUI'
import argparse
import namakanui.util
parser = argparse.ArgumentParser(
         formatter_class=argparse.RawTextHelpFormatter,
         description=namakanui.util.get_description(__doc__)
         )
parser.add_argument('target', nargs='?', default='NAMAKANUI', help='taskname of namakanui_task.py')
parser.add_argument('--debug', action='store_true', help='set logging levels to DEBUG')
cmdline_args = parser.parse_args()
namakanui_taskname = cmdline_args.target

if cmdline_args.debug:
    log.setLevel(logging.DEBUG)
    logging.getLogger('drama').setLevel(logging.DEBUG)



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
    '''
    tk.Label(parent, text=text).grid(row=row, column=0, sticky='nw')
    return grid_value(parent, row=row, column=1, sticky='ne', width=width, label=label)


class LakeshoreFrame(tk.Frame):
    def __init__(self, master=None):
        super().__init__(master)
        self.master = master
        self.setup()
    
    def setup(self):
        self.pack(fill='x')
        self.connected = grid_label(self, 'connected', 0, label=True)
        self.connected.set('NO', False)
        self.v_number = grid_label(self, 'number', 1)
        self.v_simulate = grid_label(self, 'simulate', 2)  # TODO sim_text as tooltip
        self.v_temp1 = grid_label(self, 'coldhead', 3)
        self.v_temp2 = grid_label(self, '4K', 4)
        self.v_temp3 = grid_label(self, '15K', 5)
        self.v_temp4 = grid_label(self, '90K', 6)
        self.v_temp5 = grid_label(self, 'load', 7)
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(7, weight=1)
    
    def mon_changed(self, state):
        self.connected.set("YES")
        self.connected.bg('green')
        self.v_number.set('%d'%(state['number']))
        self.v_simulate.set('0x%x'%(state['simulate']), state['simulate']==0)  # TODO tooltip
        temp = state['temp']  # list
        self.v_temp1.set('%.3f'%(temp[0]), 0.0 < temp[0] < 5.0)
        self.v_temp2.set('%.3f'%(temp[1]), 0.0 < temp[1] < 5.0)
        self.v_temp3.set('%.3f'%(temp[2]), 0.0 < temp[2] < 25.0)
        self.v_temp4.set('%.3f'%(temp[3]), 0.0 < temp[3] < 115.0)
        if len(temp) > 4:
            self.v_temp5.set('%.3f'%(temp[4]), 0.0 < temp[4] < 374.0)
    
    # LakeshoreFrame


class VacuumFrame(tk.Frame):
    def __init__(self, master=None):
        super().__init__(master)
        self.master = master
        self.setup()
    
    def setup(self):
        self.pack(fill='x')
        self.connected = grid_label(self, 'connected', 0, label=True)
        self.connected.set('NO', False)
        self.v_number = grid_label(self, 'number', 1)
        self.v_simulate = grid_label(self, 'simulate', 2)  # TODO sim_text as tooltip
        self.v_vacuum_unit = grid_value(self, 3, 0, 'nw', label=True)
        self.v_vacuum_s1 = grid_value(self, 3, 1, 'ne')
        self.v_vacuum_status = grid_label(self, 'vsensor', 4)
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(4, weight=1)
    
    def mon_changed(self, state):
        self.connected.set("YES")
        self.connected.bg('green')
        self.v_number.set('%d'%(state['number']))
        self.v_simulate.set('0x%x'%(state['simulate']), state['simulate']==0)  # TODO tooltip
        pressure_unit = state['unit']
        if not pressure_unit or pressure_unit == 'none':
            pressure_unit = 'pressure'
        self.v_vacuum_unit.set(pressure_unit)
        self.v_vacuum_s1.set(state['s1'])
        self.v_vacuum_status.set(state['status'], state['status'] == 'okay')
        try:
            s1 = float(state['s1'])
            if not 0.0 < s1 < 1e-6:
                raise ValueError
            self.v_vacuum_s1.bg('')
        except (ValueError, TypeError):
            self.v_vacuum_s1.bg('red')
    
    # VacuumFrame


class CompressorFrame(tk.Frame):
    def __init__(self, master=None):
        super().__init__(master)
        self.master = master
        self.setup()
    
    def setup(self):
        self.pack(fill='x')
        self.connected = grid_label(self, 'connected', 0, label=True)
        self.connected.set('NO', False)
        self.v_number = grid_label(self, 'number', 1)
        self.v_simulate = grid_label(self, 'simulate', 2)  # TODO sim_text as tooltip
        self.v_pressure_alarm = grid_label(self, 'pressure_alarm', 3)
        self.v_temp_alarm = grid_label(self, 'temp_alarm', 4)
        self.v_drive_operating = grid_label(self, 'drive_operating', 5)
        self.v_main_power_sw = grid_label(self, 'main_power_sw', 6)
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(6, weight=1)
    
    def mon_changed(self, state):
        self.connected.set("YES")
        self.connected.bg('green')
        self.v_number.set('%d'%(state['number']))
        self.v_simulate.set('0x%x'%(state['simulate']), state['simulate']==0)  # TODO tooltip
        self.v_pressure_alarm.set(state['pressure_alarm'], state['pressure_alarm']==0)
        self.v_temp_alarm.set(state['temp_alarm'], state['temp_alarm']==0)
        self.v_drive_operating.set(state['drive_operating'], state['drive_operating'])
        self.v_main_power_sw.set(state['main_power_sw'], state['main_power_sw'])
    
    # CompressorFrame


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
            drama.blind_obey(taskname, "LOAD_MOVE", position=self.combo.get())
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


class ReferenceFrame(tk.Frame):
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
        # ReferenceFrame.setup
        
    def mon_changed(self, state):
        self.connected['text'] = "YES"
        self.connected['bg'] = 'green'
        self.v_number.set('%d'%(state['number']))
        self.v_simulate.set('0x%x'%(state['simulate']), state['simulate']==0)  # TODO tooltip
        self.v_hz.set('%.1f'%(state['hz']))
        self.v_dbm.set('%.2f'%(state['dbm']))  # TODO warning?  how?
        self.v_output.set('%d'%(state['output']), state['output'])
    
    # ReferenceFrame


class PhotonicsFrame(tk.Frame):
    def __init__(self, master=None):
        super().__init__(master)
        self.master = master
        self.setup()
    
    def setup(self):
        # number simulate sim_text DO attenuation
        self.pack(fill='x')
        status_frame = tk.Frame(self)
        status_frame.pack(fill='x')
        tk.Label(status_frame, text='connected').grid(row=0, column=0, sticky='nw')
        self.connected = tk.Label(status_frame, text="NO", bg='red')
        self.connected.grid(row=0, column=1, sticky='ne')
        self.v_number = grid_label(status_frame, 'number', 1)
        self.v_simulate = grid_label(status_frame, 'simulate', 2)  # TODO sim_text as tooltip
        self.v_do = grid_label(status_frame, 'DO', 3)
        self.v_att = grid_label(status_frame, 'attenuation', 4)
        status_frame.grid_columnconfigure(0, weight=1)
        status_frame.grid_columnconfigure(1, weight=1)
        status_frame.grid_rowconfigure(4, weight=1)
        cmd_frame = tk.Frame(self)
        cmd_frame.pack(side='right')
        att_entry = tk.Entry(cmd_frame, width=13, bg='white')
        att_entry.pack(side='right')
        def att_callback():
            drama.blind_obey(taskname, "SET_ATT", att=int(att_entry.get()))
        self.att_button = tk.Button(cmd_frame, text='ATT')
        self.att_button.pack(side='left')
        self.att_button['command'] = att_callback
    
    def mon_changed(self, state):
        self.connected['text'] = "YES"
        self.connected['bg'] = 'green'
        self.v_number.set('%d'%(state['number']))
        self.v_simulate.set('0x%x'%(state['simulate']), state['simulate']==0)  # TODO tooltip
        do = ''.join([str(x) for x in state['DO']])
        self.v_do.set(do)
        self.v_att.set('%d'%(state['attenuation']), state['attenuation']>0)
    
    # PhotonicsFrame


class STSRFrame(tk.Frame):
    def __init__(self, master=None):
        super().__init__(master)
        self.master = master
        self.setup()
    
    def setup(self):
        self.pack(fill='x')
        status_frame = tk.Frame(self)
        status_frame.pack(fill='x')
        tk.Label(status_frame, text='connected').grid(row=0, column=0, sticky='nw')
        self.connected = tk.Label(status_frame, text="NO", bg='red')
        self.connected.grid(row=0, column=1, sticky='ne')
        self.v_number = grid_label(status_frame, 'number', 1)
        self.v_simulate = grid_label(status_frame, 'simulate', 2)  # TODO sim_text as tooltip
        self.v_lo1_lock = grid_label(status_frame, 'lo1_lock', 3)
        self.v_lo2_lock = grid_label(status_frame, 'lo2_lock', 4)
        self.v_24vdc = grid_label(status_frame, '24vdc', 5)
        self.v_12vdc = grid_label(status_frame, '12vdc', 6)
        self.v_p5vdc = grid_label(status_frame, '+5vdc', 7)
        self.v_n5vdc = grid_label(status_frame, '-5vdc', 8)
        self.v_fan1 = grid_label(status_frame, 'fan1', 9)
        self.v_fan2 = grid_label(status_frame, 'fan2', 10)
        self.v_sw1_degc = grid_label(status_frame, 'sw1_degC', 11)
        self.v_sw2_degc = grid_label(status_frame, 'sw2_degC', 12)
        self.v_sw3_degc = grid_label(status_frame, 'sw3_degC', 13)
        self.v_sw4_degc = grid_label(status_frame, 'sw4_degC', 14)
        self.v_pa1_degc = grid_label(status_frame, 'pa1_degC', 15)
        self.v_pa2_degc = grid_label(status_frame, 'pa2_degC', 16)
        self.v_lo1_degc = grid_label(status_frame, 'lo1_degC', 17)
        self.v_5056 = grid_label(status_frame, '5056_DO', 18)
        self.v_sw1_ch = grid_label(status_frame, 'sw1', 19)
        self.v_sw2_ch = grid_label(status_frame, 'sw2', 20)
        self.v_sw3_ch = grid_label(status_frame, 'sw3', 21)
        self.v_sw4_ch = grid_label(status_frame, 'sw4', 22)
        self.v_sw5_ch = grid_label(status_frame, 'sw5', 23)
        self.v_band = grid_label(status_frame, 'band', 24)
        status_frame.grid_columnconfigure(0, weight=1)
        status_frame.grid_columnconfigure(1, weight=1)
        status_frame.grid_rowconfigure(24, weight=1)
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
        ai = state['5017']
        self.v_lo1_lock.set('%.3f'%(ai[0]), 4.0 < ai[0] < 6.0)  # 4.8
        self.v_lo2_lock.set('%.3f'%(ai[1]), 2.4 < ai[1] < 4.0)  # 3.2
        self.v_24vdc.set('%.3f'%(ai[2]), 9.2 < ai[2] < 10.0)  # 9.6
        self.v_12vdc.set('%.3f'%(ai[3]), 4.6 < ai[3] < 5.0)   # 4.8
        self.v_p5vdc.set('%.3f'%(ai[4]), 1.8 < ai[4] < 2.2)    # +2.0
        self.v_n5vdc.set('%.3f'%(ai[5]), -2.2 < ai[5] < -1.8)  # -2.0
        self.v_fan1.set('%.3f'%(ai[6]))
        self.v_fan2.set('%.3f'%(ai[7]))
        ai = state['5018']
        self.v_sw1_degc.set('%.1f'%(ai[0]), -10.0 < ai[0] < 40.0)
        self.v_sw2_degc.set('%.1f'%(ai[1]), -10.0 < ai[1] < 40.0)
        self.v_sw3_degc.set('%.1f'%(ai[2]), -10.0 < ai[2] < 40.0)
        self.v_sw4_degc.set('%.1f'%(ai[3]), -10.0 < ai[3] < 40.0)
        self.v_pa1_degc.set('%.1f'%(ai[4]), -10.0 < ai[4] < 40.0)
        self.v_pa2_degc.set('%.1f'%(ai[5]), -10.0 < ai[5] < 40.0)
        self.v_lo1_degc.set('%.1f'%(ai[6]), -10.0 < ai[6] < 40.0)
        do = ''.join([str(x) for x in state['5056']])
        self.v_5056.set(do)
        self.v_sw1_ch.set(state['sw1'])
        self.v_sw2_ch.set(state['sw2'])
        self.v_sw3_ch.set(state['sw3'])
        self.v_sw4_ch.set(state['sw4'])
        self.v_sw5_ch.set(state['sw5'])
        self.band.set(str(state['band']), state['band'] in [3,6,7])
    
    # STSRFrame
        

class BandFrame(tk.Frame):
    def __init__(self, band, master=None):
        super().__init__(master)
        self.band = int(band)
        self.master = master
        # RMB 20211123: b6 p0 is always just above 5; raise p tokay a little
        # RMB 20211220: b6 temperature order is different at the GLT
        self.tnames = ['4k', '110k', 'spare', 'p0', '15k', 'p1']
        self.tokay = [(0,5), (70,115), (-2,2), (0,5.5), (5,30), (0,5.5)]
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
            drama.blind_obey(taskname, "POWER", band=self.band, enable=1)
        def power_off_callback():
            drama.blind_obey(taskname, "POWER", band=self.band, enable=0)
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
            drama.blind_obey(taskname, "TUNE", band=self.band, lo_ghz=float(tune_entry.get()), voltage=0.0)
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
        self.v_fe_mode.set('---')#'%d'%(state['fe_mode']))  # TODO monitor FEMC state
        
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
                        self.SET_ATT,
                        self.SET_BAND, self.MSG_TEST]
        
        self.retry_load = drama.retry.RetryMonitor(namakanui_taskname, 'LOAD')
        self.retry_load_table = drama.retry.RetryMonitor(namakanui_taskname, 'LOAD_TABLE')
        self.retry_reference = drama.retry.RetryMonitor(namakanui_taskname, 'REFERENCE')
        self.retry_photonics = drama.retry.RetryMonitor(namakanui_taskname, 'PHOTONICS')
        self.retry_stsr = drama.retry.RetryMonitor(namakanui_taskname, 'STSR')
        self.retry_vacuum = drama.retry.RetryMonitor(namakanui_taskname, 'VACUUM')
        self.retry_compressor = drama.retry.RetryMonitor(namakanui_taskname, 'COMPRESSOR')
        self.retry_lakeshore = drama.retry.RetryMonitor(namakanui_taskname, 'LAKESHORE')
        self.retry_b3 = drama.retry.RetryMonitor(namakanui_taskname, 'BAND3')
        self.retry_b6 = drama.retry.RetryMonitor(namakanui_taskname, 'BAND6')
        self.retry_b7 = drama.retry.RetryMonitor(namakanui_taskname, 'BAND7')
        
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
        c2 = tk.Frame(task_frame)
        c0.pack(side='left', fill='y')
        tk.Label(task_frame, text=' ').pack(side='left')  # spacer
        c1.pack(side='left', fill='y')
        tk.Label(task_frame, text=' ').pack(side='left')  # spacer
        c2.pack(side='left', fill='y')
        
        # NAMAKANUI task frame
        #nam_frame = tk.Frame(task_frame)
        #nam_frame.pack(side='left', fill='y')
        
        vacuum_parent = tk.LabelFrame(c0, text='VACUUM')
        vacuum_parent.pack(fill='x')
        self.vacuum_frame = VacuumFrame(vacuum_parent)
        
        tk.Label(c0, text=' ').pack()  # spacer
        
        compressor_parent = tk.LabelFrame(c0, text='COMPRESSOR')
        compressor_parent.pack(fill='x')
        self.compressor_frame = CompressorFrame(compressor_parent)
        
        tk.Label(c0, text=' ').pack()  # spacer
        
        lakeshore_parent = tk.LabelFrame(c0, text='LAKESHORE')
        lakeshore_parent.pack(fill='x')
        self.lakeshore_frame = LakeshoreFrame(lakeshore_parent)
        
        tk.Label(c0, text=' ').pack()  # spacer
        
        load_parent = tk.LabelFrame(c0, text='LOAD')
        load_parent.pack(fill='x')
        self.load_frame = LoadFrame(load_parent)
        
        reference_parent = tk.LabelFrame(c1, text='REFERENCE')
        reference_parent.pack(fill='x')
        self.reference_frame = ReferenceFrame(reference_parent)
        
        tk.Label(c1, text=' ').pack()  # spacer
        
        photonics_parent = tk.LabelFrame(c1, text='PHOTONICS')
        photonics_parent.pack(fill='x')
        self.photonics_frame = PhotonicsFrame(photonics_parent)
        
        #tk.Label(c1, text=' ').pack()  # spacer
        
        stsr_parent = tk.LabelFrame(c2, text='STSR')
        stsr_parent.pack(fill='x')
        self.stsr_frame = STSRFrame(stsr_parent)
        
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
        drama.blind_obey(taskname, 'MON_MAIN')
        drama.blind_obey(taskname, 'MON_B3')
        drama.blind_obey(taskname, 'MON_B6')
        drama.blind_obey(taskname, 'MON_B7')
    
    def MON_MAIN(self, msg):
        '''Calls handle() on all NAMAKANUI RetryMonitors.'''
        
        log.debug('MON_MAIN msg: %s', msg)
        
        # if UPDATE_HW isn't running, monitors will continuously timeout.
        updating = True
        if msg.reason == drama.REA_OBEY or msg.reason == drama.REA_RESCHED:
            try:
                log.info('MON_MAIN checking if %s is active', namakanui_taskname+'.UPDATE_HW')
                updating = False
                #updating = drama.is_active(namakanui_taskname, "UPDATE_HW", 3.0)
                updating = drama.obey(namakanui_taskname, "IS_ACTIVE", "UPDATE_HW").wait(3.0)
                if not updating:
                    e = 'MON_MAIN: ' + namakanui_taskname + '.UPDATE_HW not active'
                    log.error(e)
            except drama.BadStatus as e:
                log.error('MON_MAIN: %s not active, status: %r', namakanui_taskname+'.UPDATE_HW', e)
                pass  # for other errors, handle() as usual
        
        if updating and self.retry_vacuum.handle(msg):
            self.vacuum_frame.mon_changed(msg.arg)
        
        if updating and self.retry_compressor.handle(msg):
            self.compressor_frame.mon_changed(msg.arg)
        
        if updating and self.retry_lakeshore.handle(msg):
            self.lakeshore_frame.mon_changed(msg.arg)
        
        if updating and self.retry_load.handle(msg):
            self.load_frame.mon_changed(msg.arg)
        
        if updating and self.retry_load_table.handle(msg):
            self.load_frame.table_changed(msg.arg)
        
        if updating and self.retry_reference.handle(msg):
            self.reference_frame.mon_changed(msg.arg)
        
        if updating and self.retry_photonics.handle(msg):
            self.photonics_frame.mon_changed(msg.arg)
        
        if updating and self.retry_stsr.handle(msg):
            self.stsr_frame.mon_changed(msg.arg)
            
        # set disconnected indicators on all frames
        if not updating or not self.retry_vacuum.connected:
            self.vacuum_frame.connected['text'] = "NO"
            self.vacuum_frame.connected['bg'] = 'red'
        if not updating or not self.retry_compressor.connected:
            self.compressor_frame.connected['text'] = "NO"
            self.compressor_frame.connected['bg'] = 'red'
        if not updating or not self.retry_lakeshore.connected:
            self.lakeshore_frame.connected['text'] = "NO"
            self.lakeshore_frame.connected['bg'] = 'red'
        if not updating or not self.retry_load.connected:
            self.load_frame.connected['text'] = "NO"
            self.load_frame.connected['bg'] = 'red'
        if not updating or not self.retry_reference.connected:
            self.reference_frame.connected['text'] = "NO"
            self.reference_frame.connected['bg'] = 'red'
        if not updating or not self.retry_photonics.connected:
            self.photonics_frame.connected['text'] = "NO"
            self.photonics_frame.connected['bg'] = 'red'
        if not updating or not self.retry_stsr.connected:
            self.stsr_frame.connected['text'] = "NO"
            self.stsr_frame.connected['bg'] = 'red'
        
        drama.reschedule(10.0)
        
        # App.MON_MAIN
    
    def mon_cart(self, msg, retry, frame, caller):
        updating = True
        if msg.reason == drama.REA_OBEY or msg.reason == drama.REA_RESCHED:
            try:
                log.info('%s checking if %s is active', caller, retry.task+'.UPDATE_CARTS')
                updating = False
                #updating = drama.is_active(retry.task, "UPDATE_CARTS", 3.0)
                updating = drama.obey(retry.task, "IS_ACTIVE", "UPDATE_CARTS").wait(3.0)
                if not updating:
                    e = caller + ': ' + retry.task + '.UPDATE_CARTS not active'
                    log.error(e)
            except drama.BadStatus as e:
                log.error('%s: %s not active, status: %r', caller, retry.task+'.UPDATE_CARTS', e)
                pass  # for other errors, handle() as usual
        if updating and retry.handle(msg):
            frame.mon_changed(msg.arg)
        if not updating or not retry.connected:
            frame.connected['text'] = "NO"
            frame.connected['bg'] = 'red'
        drama.reschedule(10.0)
    
    def MON_B3(self, msg):
        self.mon_cart(msg, self.retry_b3, self.b3_frame, 'MON_B3')
    
    def MON_B6(self, msg):
        self.mon_cart(msg, self.retry_b6, self.b6_frame, 'MON_B6')
    
    def MON_B7(self, msg):
        self.mon_cart(msg, self.retry_b7, self.b7_frame, 'MON_B7')
        
    
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
    
    def power_args(self, band, enable):
        return int(band), int(enable)
    
    def POWER(self, msg):
        args,kwargs = drama.parse_argument(msg.arg)
        band,enable = self.power_args(*args,**kwargs)
        frame = {3:self.b3_frame, 6:self.b6_frame, 7:self.b7_frame}[band]
        frame.power_action = True
        frame.power_on_button['state'] = 'disabled'
        frame.power_off_button['state'] = 'disabled'
        try:
            drama.interested()  # in MsgOut/ErsOut
            tid = drama.obey(namakanui_taskname, "CART_POWER", band=band, enable=enable)
            self.wait_loop(tid, 120, "CART_POWER")
        except:
            log.exception('exception in POWER')
            raise
        finally:
            frame.power_action = False
            # wait for update to reenable buttons
        # App.POWER
    
    def tune_args(self, band, lo_ghz, voltage):
        return int(band), float(lo_ghz), float(voltage)
    
    def TUNE(self, msg):
        args,kwargs = drama.parse_argument(msg.arg)
        band,lo_ghz,voltage = self.tune_args(*args,**kwargs)
        frame = {3:self.b3_frame, 6:self.b6_frame, 7:self.b7_frame}[band]
        frame.tune_button['state'] = 'disabled'
        try:
            drama.interested()
            tid = drama.obey(namakanui_taskname, "TUNE", band=band, lo_ghz=lo_ghz, voltage=voltage)
            self.wait_loop(tid, 30, "TUNE")
        except:
            log.exception('exception in TUNE')
            raise
        finally:
            frame.tune_button['state'] = 'normal'
        # App.TUNE
    
    def move_args(self, position):
        return position
    
    def LOAD_MOVE(self, msg):
        args,kwargs = drama.parse_argument(msg.arg)
        position = self.move_args(*args,**kwargs)
        self.load_frame.move_button['state'] = 'disabled'
        self.load_frame.home_button['state'] = 'disabled'
        try:
            drama.interested()
            tid = drama.obey(namakanui_taskname, "LOAD_MOVE", position=position)
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
    
    def dbm_args(self, dbm):
        dbm = float(dbm)
        return dbm
    
    def SET_SG_DBM(self, msg):
        args,kwargs = drama.parse_argument(msg.arg)
        dbm = self.dbm_args(*args,**kwargs)
        self.reference_frame.dbm_button['state'] = 'disabled'
        try:
            drama.interested()
            tid = drama.obey(namakanui_taskname, "SET_SG_DBM", dbm=dbm)
            self.wait_loop(tid, 5, "SET_SG_DBM")
        except:
            log.exception('exception in SET_SG_DBM')
            raise
        finally:
            self.reference_frame.dbm_button['state'] = 'normal'
        # App.SET_SG_DBM
    
    def hz_args(self, hz):
        hz = float(hz)
        if hz < 9e3 or hz > 32e9:
            raise ValueError(f'hz {hz} outside [9 KHz, 32 GHz] range')
        return hz
    
    def SET_SG_HZ(self, msg):
        args,kwargs = drama.parse_argument(msg.arg)
        hz = self.hz_args(*args,**kwargs)
        self.reference_frame.hz_button['state'] = 'disabled'
        try:
            drama.interested()
            tid = drama.obey(namakanui_taskname, "SET_SG_HZ", hz=hz)
            self.wait_loop(tid, 5, "SET_SG_HZ")
        except:
            log.exception('exception in SET_SG_HZ')
            raise
        finally:
            self.reference_frame.hz_button['state'] = 'normal'
        # App.SET_SG_HZ
    
    def out_args(self, out):
        return int(bool(out))
    
    def SET_SG_OUT(self, msg):
        args,kwargs = drama.parse_argument(msg.arg)
        out = self.out_args(*args,**kwargs)
        self.reference_frame.on_button['state'] = 'disabled'
        self.reference_frame.off_button['state'] = 'disabled'
        try:
            drama.interested()
            tid = drama.obey(namakanui_taskname, "SET_SG_OUT", out=out)
            self.wait_loop(tid, 5, "SET_SG_OUT")
        except:
            log.exception('exception in SET_SG_OUT')
            raise
        finally:
            self.reference_frame.on_button['state'] = 'normal'
            self.reference_frame.off_button['state'] = 'normal'
        # App.SET_SG_OUT
    
    def att_args(self, att):
        return int(att)
    
    def SET_ATT(self, msg):
        args,kwargs = drama.parse_argument(msg.arg)
        att = self.att_args(*args, **kwargs)
        self.photonics_frame.att_button['state'] = 'disabled'
        try:
            drama.interested()
            tid = drama.obey(namakanui_taskname, "SET_ATT", att=att)
            self.wait_loop(tid, 5, "SET_ATT")
        except:
            log.exception('exception in SET_ATT')
            raise
        finally:
            self.photonics_frame.att_button['state'] = 'normal'
        # App.SET_ATT
    
    def band_args(self, band):
        band = int(band)
        if band not in [3,6,7]:
            raise ValueError(f'BAND {band} not one of [3,6,7]')
        return band
    
    def SET_BAND(self, msg):
        args,kwargs = drama.parse_argument(msg.arg)
        band = self.band_args(*args,**kwargs)
        self.stsr_frame.b3_button['state'] = 'disabled'
        self.stsr_frame.b6_button['state'] = 'disabled'
        self.stsr_frame.b7_button['state'] = 'disabled'
        try:
            drama.interested()
            tid = drama.obey(namakanui_taskname, "SET_BAND", band=band)
            self.wait_loop(tid, 5, "SET_BAND")
        except:
            log.exception('exception in SET_BAND')
            raise
        finally:
            self.stsr_frame.b3_button['state'] = 'normal'
            self.stsr_frame.b6_button['state'] = 'normal'
            self.stsr_frame.b7_button['state'] = 'normal'
        # App.SET_BAND
    
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
        # App.MSG_TEST
    
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
except:
    log.exception('fatal exception')
    sys.exit(1)
finally:
    log.info('drama.stop(%s)', taskname)
    drama.stop()
    log.info('done')
        

