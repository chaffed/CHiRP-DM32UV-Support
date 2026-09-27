#!/usr/bin/env python3
"""Careful single-page writes to a DM-32UV, for testing the write path.

Only pages the driver itself uploads can be written (channels, zones, settings
page 0x04, DMR and scan lists; never 0x02/0x69). Every write goes through
the driver's guarded _write_page (one whole aligned page, read back until
it matches). The page tags are scanned before and after, and the tool
reports any change. Without --yes nothing is written (dry run).

    # rewrite one page with its current contents (changes nothing)
    python3 dm32uv_write.py /dev/ttyUSB0 --noop 12 --yes
    # put one page back from a backup made with dm32uv_read.py --all-pages
    python3 dm32uv_write.py /dev/ttyUSB0 --restore backup-2026-09-26 --tag 12 --yes

Every byte sent and received is logged to OUT/traffic.log.
"""

import argparse
import os
import sys
import types

import serial

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'driver'))
import baofeng_dm32uv as drv  # noqa: E402


class LoggingPipe:
    """Wraps the serial port and logs every byte, like dm32uv_read.py."""

    def __init__(self, pipe, log):
        self.pipe, self.log = pipe, log

    def write(self, data):
        self.log.write('> %s\n' % bytes(data).hex(' '))
        return self.pipe.write(data)

    def read(self, n):
        data = self.pipe.read(n)
        self.log.write('< %s\n' % data.hex(' '))
        return data

    def __getattr__(self, name):
        return getattr(self.pipe, name)

    def __setattr__(self, name, value):
        if name in ('pipe', 'log'):
            object.__setattr__(self, name, value)
        else:
            setattr(self.pipe, name, value)


def backup_page(backup, tag):
    names = [n for n in os.listdir(os.path.join(backup, 'pages'))
             if n.startswith('tag%02x_' % tag)]
    if len(names) != 1:
        raise drv.errors.RadioError(
            'backup has %d pages with tag %02x' % (len(names), tag))
    with open(os.path.join(backup, 'pages', names[0]), 'rb') as f:
        return f.read()


def scan(link, start, end):
    status = drv.chirp_common.Status()
    where, free = drv._scan(link, start, end,
                            types.SimpleNamespace(status_fn=lambda s: None),
                            status)
    return {addr: tag for tag, addrs in where.items() for addr in addrs} | {
        addr: 0xFF for addr in free}


def run(args, pipe):
    link = drv._Link(pipe)
    firmware, start, end = drv._identify(link)
    print('radio firmware %s, codeplug %06x-%06x' % (firmware, start, end))
    drv._enter_program(link)

    before = scan(link, start, end)
    addrs = [a for a, t in before.items() if t == args.tag]
    if len(addrs) != 1:
        raise drv.errors.RadioError(
            'radio has %d pages with tag %02x; not writing' %
            (len(addrs), args.tag))
    addr = addrs[0]
    current = link.read_block(addr, drv.PAGE)
    if args.restore:
        want = backup_page(args.restore, args.tag)
    else:
        want = current
    if want[-1] != args.tag:
        raise drv.errors.RadioError(
            'page data does not end with tag %02x' % args.tag)
    changed = sum(a != b for a, b in zip(current, want))
    print('tag %02x is at %06x; %d bytes differ from the %s' % (
        args.tag, addr, changed, 'backup' if args.restore else 'current page'))
    if args.restore and not changed:
        print('nothing to do')
        return 0
    if not args.yes:
        print('dry run: would write page %06x (use --yes to write)' % addr)
        return 0

    drv._write_page(link, addr, want, start, end)
    print('wrote page %06x and read it back: matches' % addr)
    after = scan(link, start, end)
    moved = {a: (before[a], after[a]) for a in before if before[a] != after[a]}
    if moved:
        print('WARNING: page tags changed: %s' % ', '.join(
            '%06x %02x->%02x' % (a, b, c) for a, (b, c) in sorted(moved.items())))
        return 1
    print('page tags unchanged after the write')
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument('port')
    what = ap.add_mutually_exclusive_group(required=True)
    what.add_argument('--noop', metavar='TAG', type=lambda s: int(s, 16),
                      help='rewrite this page with its current contents')
    what.add_argument('--restore', metavar='BACKUP',
                      help='backup directory to restore --tag from')
    ap.add_argument('--tag', type=lambda s: int(s, 16),
                    help='page tag (hex) for --restore')
    ap.add_argument('--yes', action='store_true', help='really write')
    ap.add_argument('-o', '--out', default='dump-write',
                    help='directory for traffic.log (default dump-write)')
    args = ap.parse_args()
    if args.noop is not None:
        args.tag = args.noop
    if args.tag is None:
        ap.error('--restore needs --tag')
    if args.tag not in drv.UPLOAD_TAGS:
        ap.error('only pages the driver uploads can be written '
                 '(not calibration-like or unknown pages)')

    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, 'traffic.log'), 'w') as log:
        ser = serial.Serial(args.port, drv.DM32UV.BAUD_RATE, timeout=0.5)
        ser.dtr = ser.rts = True
        try:
            return run(args, LoggingPipe(ser, log))
        except drv.errors.RadioError as e:
            print('ERROR: %s' % e, file=sys.stderr)
            return 2
        finally:
            ser.close()
            print('traffic log in %s/traffic.log' % args.out)


if __name__ == '__main__':
    sys.exit(main())
