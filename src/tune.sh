#!/bin/bash
#
# tune.sh   RMB 20190820
#
# Tune a cartridge to the given LO GHz and optimize IF power
# by using the dbm_table.py script.  Sets the "lock above reference" option
# and starts the signal generator output 1 dBm below the value interpolated
# from the table in the agilent.ini file.
# 
# Usage:
# tune.sh <band> <lo_ghz>
#
#
# Copyright (C) 2020 East Asian Observatory
# 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

BAND=$1
LO_GHZ=$2
#DBM_TABLE=/jac_sw/itsroot/install/namakanui/bin/Linux-x86_64/dbm_table.py
DBM_TABLE=`dirname "$0"`/dbm_table.py
${DBM_TABLE} "$BAND" "$LO_GHZ" "$LO_GHZ" 1 above ini-0
