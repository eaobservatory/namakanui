#!/local/python3/bin/python3
from jac_sw import uae

uae.git_version_file('namakanui/version.py')

uae.setup(
    scripts = ['namakanui_task.py'],
    packages = ['namakanui'],
)

