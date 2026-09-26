#!/usr/bin/env python3
"""Read-only test tool for the Baofeng DM-32UV programming protocol.

Implements the read path described in PROTOCOL.md. It never sends a write
command. Every byte sent and received is logged so the protocol notes can be
checked against the real radio.

The serial link corrupts about 1 received byte in 1000 (bit 7 flipped 0 -> 1,
see PROTOCOL.md "Serial link reliability"), and the protocol has no checksums.
So every block is read at least three times and the copies are merged byte
by byte; V queries are repeated until three replies match.

    python3 dm32uv_read.py --list
    python3 dm32uv_read.py /dev/ttyUSB0 --probe      # identify only (Linux)
    python3 dm32uv_read.py /dev/ttyUSB0 -o dump1      # full read
    python3 dm32uv_read.py /dev/ttyUSB0 --all-pages -o backup1   # every page
"""

import argparse
import collections
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

# The known link fault: received bytes sometimes have this bit set when the
# radio sent it clear. It has never been seen the other way round.
LINK_FAULT = 0x80


class ProtocolError(Exception):
    pass


def marker_ok(got, want):
    """Check a one-byte reply marker, allowing for the known link fault."""
    return got in (want, want | LINK_FAULT)


def merge_copies(copies, stats):
    """Merge copies of the same block byte by byte, or return None if more
    copies are needed.

    Where copies differ only in bit 7, the value with bit 7 clear is taken,
    since the link fault only ever sets it. Any other disagreement is
    counted separately and needs a strict majority of at least 3 copies.
    """
    first = copies[0]
    if all(c == first for c in copies[1:]):
        return first
    out = bytearray(first)
    found = collections.Counter()
    for i, vals in enumerate(zip(*copies)):
        if min(vals) == max(vals):
            continue
        votes = collections.Counter(vals)
        if len({v & ~LINK_FAULT for v in votes}) == 1:
            out[i] = min(votes)
            found['bit-7 errors corrected'] += 1
            continue
        found['other disagreements'] += 1
        value, n = votes.most_common(1)[0]
        if n < 3 or n * 2 <= len(copies):
            return None
        out[i] = value
    stats.update(found)
    return bytes(out)


class Radio:
    def __init__(self, port, log):
        self.ser = serial.Serial(port, 115200, bytesize=8, parity='N',
                                 stopbits=1, timeout=0.5)
        self.ser.dtr = True
        self.ser.rts = True
        self.log = log
        self.stats = collections.Counter()

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

    def drain(self):
        """Discard any late bytes of a bad reply before retrying."""
        time.sleep(0.1)
        self.ser.reset_input_buffer()

    def xfer(self, data, n, timeout=0.5, what=''):
        self.send(data)
        resp = self.recv(n, timeout)
        if len(resp) != n:
            raise ProtocolError('%s: expected %d bytes, got %d: %s' % (
                what or data[:8], n, len(resp), resp.hex(' ')))
        return resp

    def query_v(self, cmd, agree=3, tries=10):
        """Repeat a V query until `agree` identical replies have been seen."""
        seen = collections.Counter()
        for _attempt in range(tries):
            self.send(cmd)
            hdr = self.recv(3)
            n = hdr[2] if len(hdr) == 3 else 0
            body = self.recv(n) if n else b''
            if len(hdr) != 3 or len(body) != n or not marker_ok(hdr[0], 0x56):
                self.stats['bad V replies'] += 1
                self.drain()
                continue
            seen[hdr + body] += 1
            reply, count = seen.most_common(1)[0]
            if count >= agree:
                if len(seen) > 1:
                    self.stats['V replies corrected'] += 1
                return reply[:3], reply[3:]
        raise ProtocolError('no %d matching replies to V %s' % (
            agree, cmd.hex(' ')))

    def read_copy(self, addr, length, timeout):
        """One R transfer; None if the reply is short or has a bad header."""
        cmd = b'R' + struct.pack('<I', addr)[:3] + struct.pack('<H', length)
        self.send(cmd)
        resp = self.recv(6 + length, timeout)
        if len(resp) == 6 + length and resp[:6] == b'W' + cmd[1:6]:
            return resp[6:]
        self.stats['bad R replies'] += 1
        self.drain()
        return None

    def read_block(self, addr, length, timeout=5.0, copies=3, tries=10):
        """Read a block at least `copies` times and merge the copies."""
        good = []
        for _attempt in range(tries):
            data = self.read_copy(addr, length, timeout)
            if data is None:
                continue
            good.append(data)
            if len(good) >= copies:
                merged = merge_copies(good, self.stats)
                if merged is not None:
                    return merged
        raise ProtocolError('R %06x: no reliable copy after %d tries '
                            '(%d good replies)' % (addr, tries, len(good)))


def identify(radio, info):
    for _attempt in range(5):
        radio.send(b'PSEARCH')
        resp = radio.recv(8)
        if len(resp) == 8 and marker_ok(resp[0], 0x06):
            break
    else:
        raise ProtocolError('no reply to PSEARCH')
    info['psearch'] = resp.hex(' ')
    print('PSEARCH  -> %s  %r' % (resp.hex(' '), resp[1:]))

    resp = radio.xfer(b'PASSSTA', 3, what='PASSSTA')
    info['passsta'] = resp.hex(' ')
    print('PASSSTA  -> %s' % resp.hex(' '))
    if not marker_ok(resp[0], ord('P')):
        raise ProtocolError('bad PASSSTA reply')
    if resp[2] == 0xA5:
        raise ProtocolError('radio has a read password set; not supported yet')

    resp = radio.xfer(b'SYSINFO', 1, what='SYSINFO')
    info['sysinfo'] = resp.hex(' ')
    print('SYSINFO  -> %s' % resp.hex(' '))
    if not marker_ok(resp[0], 0x06):
        raise ProtocolError('SYSINFO not acknowledged: %s' % resp.hex(' '))

    hdr, body = radio.query_v(b'V\x00\x00\x40\x0D')
    info['v_40_0d'] = (hdr + body).hex(' ')
    print('V 40 0D  -> %s | %s' % (hdr.hex(' '), body.hex(' ')))

    info['v'] = {}
    for i in range(1, 17):
        if i == 12:
            continue
        hdr, body = radio.query_v(b'V\x00\x00\x00' + bytes([i]))
        info['v'][i] = (hdr + body).hex(' ')
        print('V %2d     -> %s | %s  %r' % (
            i, hdr.hex(' '), body.hex(' '), body if body.isascii() else ''))

    # V ranges are 24-bit flash addresses in u32 fields.
    for key, i, name in (('cp', 10, 'codeplug'), ('ct', 15, 'contacts')):
        body = bytes.fromhex(info['v'][i])[3:]
        if len(body) < 8:
            continue
        start, end = struct.unpack('<II', body[:8])
        if (start | end) >> 24:
            raise ProtocolError('V%d range %#x - %#x is not 24-bit' % (
                i, start, end))
        info[key + '_start'], info[key + '_end'] = start, end
        print('%s area: %#08x - %#08x' % (name, start, end))


def enter_program(radio, info):
    resp = radio.xfer(b'G\x00\x00\x00\x00\x01', 0x106, what='G')
    info['g_block'] = resp.hex(' ')
    print('G        -> %s ... (%d bytes)' % (resp[:6].hex(' '), len(resp)))
    if not marker_ok(resp[0], ord('S')):
        raise ProtocolError('bad G reply header %s' % resp[:6].hex(' '))

    radio.send(b'\xFF\xFF\xFF\xFF\x0C')
    resp = radio.xfer(b'PROGRAM', 1, what='PROGRAM')
    if not marker_ok(resp[0], 0x06):
        raise ProtocolError('PROGRAM not acknowledged: %s' % resp.hex(' '))
    resp = radio.xfer(b'\x02', 8, what='02')
    info['ident'] = resp.hex(' ')
    print('02       -> %s  %r' % (resp.hex(' '), resp))
    resp = radio.xfer(b'\x06', 1, what='06')
    if not marker_ok(resp[0], 0x06):
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
    ap.add_argument('--all-pages', action='store_true',
                    help='save every codeplug page, including free (tag ff) '
                    'ones, e.g. for a backup')
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
                if tag in by_tag and tag != 0x00:
                    print('warning: tag %#04x on pages %#x and %#x' % (
                        tag, by_tag[tag], addr))
                by_tag.setdefault(tag, addr)
            # Save every page in use, not just the tags the CPS reads: the
            # others (and stale tag 0x00 pages) help with mapping.
            os.makedirs(os.path.join(args.out, 'pages'), exist_ok=True)
            for addr, tag in sorted(tags.items(), key=lambda at: (at[1], at[0])):
                if tag == 0xFF and not args.all_pages:
                    continue
                data = radio.read_block(addr, PAGE)
                name = 'tag%02x_%06x.bin' % (tag, addr)
                with open(os.path.join(args.out, 'pages', name), 'wb') as f:
                    f.write(data)
                print('read tag %#04x from %#08x' % (tag, addr))
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
            info['link_stats'] = dict(radio.stats)
            print('link errors handled: %s' % (
                ', '.join('%s %d' % kv for kv in sorted(radio.stats.items()))
                or 'none'))
            with open(os.path.join(args.out, 'info.json'), 'w') as f:
                json.dump(info, f, indent=2)
            print('log and results saved in %s/' % args.out)


if __name__ == '__main__':
    main()
