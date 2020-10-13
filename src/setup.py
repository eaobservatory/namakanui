#!/local/python3/bin/python3
from jac_sw import uae

uae.git_version_file('namakanui/version.py')

uae.setup(
    scripts = ['cartridge_task.py',
               'dbm_table.py',
               'fe_namakanui.py',
               'mixer_iv.py',
               'namakanui_gui.py',
               'namakanui_task.py',
               'pa_sweep.py',
               'power_down.py',
               'set_load.py',
               'temp_mon.py',
               'tune.sh',
               'yfactor.py'],
    packages = ['namakanui'],
)

