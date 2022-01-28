#!/local/python3/bin/python3
'''
namakanui_pcand.py   RMB 20220125

A daemon to communicate with the PEAK PCAN-Ethernet Gateway DR.

The PCAN module is designed primarily to talk to other PCAN modules,
and as such it uses separate, preconfigured can2lan and lan2can routes.
You can't just connect a socket and get simple bidirectional communication.

If you want to talk to the CANbus with multiple simultaneous processes,
you'd normally need to configure a separate pair of routes for each one.
Instead, we configure a single pair of routes that only talk to this process,
and everybody else talks to us with bidirectional sockets.

This daemon is designed to exit immediately on any communication error,
so it should be configured to automatically restart, for instance
by running it as a systemd service.



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
import sys
import time
import logging
import argparse
import socket
import select
import namakanui.util

namakanui.util.setup_logging()
log = logging.getLogger('pcand')

parser = argparse.ArgumentParser(
    formatter_class=argparse.RawTextHelpFormatter,
    description=namakanui.util.get_description(__doc__)
    )
parser.add_argument('-v', '--verbose', action='store_true', help='enable debug logging output')
args = parser.parse_args()

if args.verbose:
    logging.root.setLevel(logging.DEBUG)
    log.setLevel(logging.DEBUG)

cfg = namakanui.util.get_config('femc.ini')['femc']
pcan_type = cfg['pcan_type'].lower()  # tcp or udp
lan2can_ip = cfg['lan2can_ip']  # PCAN IP
lan2can_port = int(cfg['lan2can_port'])
can2lan_port = int(cfg['can2lan_port'])  # on localhost
pcand_port = int(cfg['pcand_port'])

# connect to PCAN
if pcan_type == 'tcp':
    log.debug('creating tcp lan2can socket')
    lan2can = socket.socket()
else:
    log.debug('creating udp lan2can socket')
    lan2can = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
lan2can.settimeout(1)
log.debug('lan2can.connect((%s, %d))', lan2can_ip, lan2can_port)
lan2can.connect((lan2can_ip, lan2can_port))

# bind a known port so PCAN can connect to us;
# set SO_REUSEADDR so pcand can restart even if old socket stuck in TIME_WAIT
if pcan_type == 'tcp':
    log.debug('listening for can2lan on tcp port %d', can2lan_port)
    can2lan_listener = socket.socket()
    can2lan_listener.settimeout(5)
    can2lan_listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    can2lan_listener.bind(('0.0.0.0', can2lan_port))
    can2lan_listener.listen()
    can2lan = can2lan_listener.accept()[0]
    can2lan.settimeout(1)
    can2lan_listener.shutdown(socket.SHUT_RDWR)
    can2lan_listener.close()
else:
    log.debug('binding can2lan on udp port %d', can2lan_port)
    can2lan = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    can2lan.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    can2lan.settimeout(1)
    can2lan.bind(('0.0.0.0', can2lan_port))
    

# create server listening socket on pcand_port;
# set SO_REUSEADDR so pcand can restart even if old socket stuck in TIME_WAIT
log.debug('listening for clients on tcp port %d', pcand_port)
listener = socket.socket()
listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
listener.bind(('0.0.0.0', pcand_port))
listener.listen()
clients = set()

# main loop
log.debug('entering main loop')
while True:
    r,w,x = select.select([listener, can2lan] + list(clients), [], [], 0.0)
    r = set(r)
    if listener in r:
        r -= {listener}
        client = listener.accept()[0]
        log.debug('accepted new client %s', client)
        client.setblocking(False)
        clients |= {client}
    if can2lan in r:
        r -= {can2lan}
        packet = can2lan.recv(36)
        if not packet:
            log.error('lost PCAN connection')
            break
        for client in clients:
            try:
                client.send(packet)
            except:
                # ignore all errors forwarding packets to clients
                pass
    for client in r:
        packet = client.recv(36)
        if len(packet) < 36:  # bad/lost/closed connection
            log.debug('dropping client %s', client)
            client.close()
            clients -= {client}
        else:
            lan2can.send(packet)

# only get here if lost PCAN connection, so clean up and exit with error
log.debug('done, closing sockets.')
listener.close()
can2lan.close()
for client in clients:
    client.close()
sys.exit(1)


