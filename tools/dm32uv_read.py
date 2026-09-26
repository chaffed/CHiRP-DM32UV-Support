#!/usr/bin/env python3
"""Read-only test tool for the Baofeng DM-32UV programming protocol.

Implements the read path described in PROTOCOL.md. It never sends a write
command. Every byte sent and received is logged so the protocol notes can be
checked against the real radio.

    python3 dm32uv_read.py --list
    python3 dm32uv_read.py /dev/ttyUSB0 --probe      # identify only (Linux)
    python3 dm32uv_read.py /dev/ttyUSB0 -o dump1      # full read
"""

import argparse
import json
import os
import struct
import sys
import time

import serial
from serial.tools import list_ports

PAGE = 0x1000
SINGLE_TAGS = [0x02, 0x03, 0x04, 0x06, 0x0A, 0x0B, 0x0F, 0x10, 0x11,
               0x65, 0x66, 0x67]
RANGE_TAGS = (list(range(0x12, 0x42)) + [0x42, 0x43] +
              list(range(0x44, 0x49)) + list(range(0x5C, 0x65)))
WANTED_TAGS = SINGLE_TAGS + RANGE_TAGS


class ProtocolError(Exception):
    pass


class Radio:
    def __init__(self, port, log):
        self.ser = serial.Serial(port, 115200, bytesize=8, parity='N',
                                 stopbits=1, timeout=0.5)
        self.ser.dtr = True
        self.ser.rts = True
        self.log = log

    def send(self, data):
        time.sleep(0.01)
        self.ser.reset_input_buffer()
        self.ser.write(data)
        self.log.write('> %s\n' % data.hex(' '))

    def recv(self, n, timeout=0.5):
        self.ser.timeout = timeout
        data = self.ser.read(n)
        self.log.write('< %s\n' % data.hex(' '))
        return data

    def xfer(self, data, n, timeout=0.5, what=''):
        self.send(data)
        resp = self.recv(n, timeout)
        if len(resp) != n:
            raise ProtocolError('%s: expected %d bytes, got %d: %s' % (
                what or data[:8], n, len(resp), resp.hex(' ')))
        return resp

    def query_v(self, cmd):
        hdr = self.xfer(cmd, 3, what='V %s' % cmd.hex(' '))
        if hdr[0:1] != b'V':
            raise ProtocolError('bad V reply %s' % hdr.hex(' '))
        n = hdr[2]
        body = self.recv(n) if n else b''
        if len(body) != n:
            raise ProtocolError('short V body for %s' % cmd.hex(' '))
        return hdr, body

    def read_block(self, addr, length, timeout=5.0):
        cmd = b'R' + struct.pack('<I', addr)[:3] + struct.pack('<H', length)
        resp = self.xfer(cmd, 6 + length, timeout, what='R %06x' % addr)
        if resp[0:1] != b'W' or resp[1:6] != cmd[1:6]:
            raise ProtocolError('bad R reply header %s' % resp[:6].hex(' '))
        return resp[6:]


def identify(radio, info):
    for _attempt in range(5):
        radio.send(b'PSEARCH')
        resp = radio.recv(8)
        if len(resp) == 8 and resp[0] == 0x06:
            break
    else:
        raise ProtocolError('no reply to PSEARCH')
    info['psearch'] = resp.hex(' ')
    print('PSEARCH  -> %s  %r' % (resp.hex(' '), resp[1:]))

    resp = radio.xfer(b'PASSSTA', 3, what='PASSSTA')
    info['passsta'] = resp.hex(' ')
    print('PASSSTA  -> %s' % resp.hex(' '))
    if resp[0:1] != b'P':
        raise ProtocolError('bad PASSSTA reply')
    if resp[2] == 0xA5:
        raise ProtocolError('radio has a read password set; not supported yet')

    resp = radio.xfer(b'SYSINFO', 1, what='SYSINFO')
    info['sysinfo'] = resp.hex(' ')
    print('SYSINFO  -> %s' % resp.hex(' '))

    hdr, body = radio.query_v(b'V\x00\x00\x40\x0D')
    info['v_40_0d'] = (hdr + body).hex(' ')
    print('V 40 0D  -> %s | %s' % (hdr.hex(' '), body.hex(' ')))

    info['v'] = {}
    for i in range(1, 17):
        if i == 12:
            continue
        hdr, body = radio.query_v(b'V\x00\x00\x00' + bytes([i]))
        info['v'][i] = (hdr + body).hex(' ')
        print('V %2d     -> %s | %s  %r' % (i, hdr.hex(' '), body.hex(' '),
                                           body if body.isascii() else ''))

    # V ranges are 24-bit flash addresses; the top byte of each u32 is not
    # part of the address (V10 start reads 0x80001000 on a real radio).
    for key, i, name in (('cp', 10, 'codeplug'), ('ct', 15, 'contacts')):
        body = bytes.fromhex(info['v'][i])[3:]
        if len(body) < 8:
            continue
        start, end = struct.unpack('<II', body[:8])
        info[key + '_start'], info[key + '_end'] = start & 0xFFFFFF, end & 0xFFFFFF
        info[key + '_flags'] = '%02x %02x' % (start >> 24, end >> 24)
        print('%s area: %#08x - %#08x  (flag bytes %s)' % (
            name, info[key + '_start'], info[key + '_end'], info[key + '_flags']))


def enter_program(radio, info):
    resp = radio.xfer(b'G\x00\x00\x00\x00\x01', 0x106, what='G')
    info['g_block'] = resp.hex(' ')
    print('G        -> %s ... (%d bytes)' % (resp[:6].hex(' '), len(resp)))

    radio.send(b'\xFF\xFF\xFF\xFF\x0C')
    resp = radio.xfer(b'PROGRAM', 1, what='PROGRAM')
    if resp != b'\x06':
        raise ProtocolError('PROGRAM not acknowledged: %s' % resp.hex(' '))
    resp = radio.xfer(b'\x02', 8, what='02')
    info['ident'] = resp.hex(' ')
    print('02       -> %s  %r' % (resp.hex(' '), resp))
    resp = radio.xfer(b'\x06', 1, what='06')
    if resp != b'\x06':
        raise ProtocolError('06 not acknowledged: %s' % resp.hex(' '))


def scan_pages(radio, info):
    tags = {}
    addr = info['cp_start']
    while addr + 0xFFF <= info['cp_end']:
        tag = radio.read_block(addr + 0xFFF, 1, timeout=0.5)[0]
        tags[addr] = tag
        addr += PAGE
    info['page_tags'] = {'%06x' % a: '%02x' % t for a, t in tags.items()}
    used = {a: t for a, t in tags.items() if t != 0xFF}
    print('scanned %d pages, %d in use' % (len(tags), len(used)))
    return tags


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument('port', nargs='?')
    ap.add_argument('--list', action='store_true', help='list serial ports')
    ap.add_argument('--probe', action='store_true',
                    help='identify only; do not enter programming mode')
    ap.add_argument('--contacts', action='store_true',
                    help='also read the digital contacts area')
    ap.add_argument('-o', '--out', default='dump')
    args = ap.parse_args()

    if args.list or not args.port:
        for p in list_ports.comports():
            print(p.device, '-', p.description)
        return

    os.makedirs(args.out, exist_ok=True)
    info = {}
    with open(os.path.join(args.out, 'traffic.log'), 'w') as log:
        radio = Radio(args.port, log)
        try:
            identify(radio, info)
            if args.probe:
                return
            enter_program(radio, info)
            tags = scan_pages(radio, info)
            by_tag = {}
            for addr, tag in tags.items():
                if tag == 0xFF:
                    continue
                if tag in by_tag:
                    print('warning: tag %#04x on pages %#x and %#x' % (
                        tag, by_tag[tag], addr))
                by_tag.setdefault(tag, addr)
            os.makedirs(os.path.join(args.out, 'pages'), exist_ok=True)
            for tag in WANTED_TAGS:
                if tag not in by_tag:
                    continue
                data = radio.read_block(by_tag[tag], PAGE)
                name = 'tag%02x_%06x.bin' % (tag, by_tag[tag])
                with open(os.path.join(args.out, 'pages', name), 'wb') as f:
                    f.write(data)
                print('read tag %#04x from %#08x' % (tag, by_tag[tag]))
            unknown = sorted(set(by_tag) - set(WANTED_TAGS) - {0xFF})
            if unknown:
                print('tags in use that the CPS does not read: %s' %
                      ', '.join('%#04x' % t for t in unknown))
            if args.contacts and 'ct_start' in info:
                hdr = radio.read_block(info['ct_start'], 4, timeout=0.5)
                info['contacts_hdr'] = hdr.hex(' ')
                print('contacts header: %s' % hdr.hex(' '))
        except ProtocolError as e:
            print('PROTOCOL ERROR: %s' % e, file=sys.stderr)
            info['error'] = str(e)
        finally:
            radio.ser.close()
            with open(os.path.join(args.out, 'info.json'), 'w') as f:
                json.dump(info, f, indent=2)
            print('log and results saved in %s/' % args.out)


if __name__ == '__main__':
    main()
