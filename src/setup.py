#!/local/python3/bin/python3
from jac_sw import uae

uae.git_version_file('namakanui/version.py')

uae.setup(
    scripts = ['namakanui_task.py',
               'cartridge_task.py',
               'fe_namakanui.py',
               'dbm_table.py',
               'mixer_iv.py',
               'pa_sweep.py',
               'tune.sh'],
    packages = ['namakanui'],
)

