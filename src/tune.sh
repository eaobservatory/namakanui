#!/bin/bash
# Tune a cartridge to the given LO GHz and optimize IF power
# by using the dbm_table.py script.  Sets the "lock above reference" option
# and starts the signal generator output 2 dBm below the value interpolated
# from the table in the agilent.ini file.
# 
# Usage:
# tune.sh <band> <lo_ghz>

BAND=$1
LO_GHZ=$2
DBM_TABLE=/jac_sw/itsroot/install/namakanui/bin/Linux-x86_64/dbm_table.py
${DBM_TABLE} "$BAND" "$LO_GHZ" "$LO_GHZ" 1 above ini-2
