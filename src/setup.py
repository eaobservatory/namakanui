#!/local/python3/bin/python3
from jac_sw import uae
import glob

uae.git_version_file('namakanui/version.py')

uae.setup(
    scripts = glob.glob('namakanui_*.py'),
    packages = ['namakanui'],
)

