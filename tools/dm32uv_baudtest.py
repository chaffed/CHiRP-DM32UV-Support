#!/usr/bin/env python3
"""Measure read errors at serial rates close to 115200 (read-only).

The received-data errors seen on the DM-32UV (only bit 7, only 0 -> 1,
only radio -> PC) look like a small baud-rate mismatch. For each rate
this does the normal handshake, reads one 4 KB block several times and
counts the bytes that differ from the majority of the copies.

Nothing is written. At a rate the radio can't follow it may stop
answering; the sweep then stops, and the radio needs switching off and
on. The first rate is always 115200, the known-good one.

    python3 tools/dm32uv_baudtest.py /dev/ttyUSB0
    python3 tools/dm32uv_baudtest.py /dev/ttyUSB0 --rates 115200,116400,117500
"""

import argparse
import collections
import os
import sys
import time

import serial

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'driver'))
import baofeng_dm32uv as drv  # noqa: E402
from chirp import errors  # noqa: E402

DEFAULT_RATES = [115200, 116300, 117400, 118500, 114100]
ADDR, COPIES = 0x001000, 20


def raw_reads(link, addr, copies):
    """`copies` single reads of one block, without merging."""
    cmd = b'R' + addr.to_bytes(3, 'little') + drv.PAGE.to_bytes(2, 'little')
    out = []
    for _ in range(copies * 2):
        link.send(cmd)
        resp = link.recv(6 + drv.PAGE, 5.0)
        if len(resp) == 6 + drv.PAGE and resp[1:6] == cmd[1:6]:
            out.append(resp[6:])
            if len(out) == copies:
                break
        else:
            link.drain()
    return out


def measure(port, rate):
    pipe = serial.Serial(port, rate, timeout=0.5)
    pipe.dtr = pipe.rts = True
    try:
        link = drv._Link(pipe)
        drv._identify(link)
        drv._enter_program(link)
        copies = raw_reads(link, ADDR, COPIES)
    finally:
        pipe.close()
    if len(copies) < 3:
        return None
    errors_bit7 = errors_other = 0
    for i in range(drv.PAGE):
        want = collections.Counter(c[i] for c in copies).most_common(1)[0][0]
        for c in copies:
            if c[i] != want:
                if c[i] ^ want == 0x80:
                    errors_bit7 += 1
                else:
                    errors_other += 1
    return len(copies), errors_bit7, errors_other


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('port')
    ap.add_argument('--rates', default=','.join(map(str, DEFAULT_RATES)))
    args = ap.parse_args()
    rates = [int(r) for r in args.rates.split(',')]
    if rates[0] != 115200:
        rates.insert(0, 115200)
    print('%8s %6s %9s %11s %12s' % ('rate', 'reads', 'bytes', 'bit-7 errs',
                                     'other errs'))
    for rate in rates:
        try:
            result = measure(args.port, rate)
        except errors.RadioError as e:
            print('%8d  no usable reply (%s); stopping here. Switch the radio '
                  'off and on before using it again.' % (rate, e))
            break
        if result is None:
            print('%8d  too few good reads; stopping here.' % rate)
            break
        n, b7, other = result
        print('%8d %6d %9d %11d %12d  (1 in %s)' % (
            rate, n, n * drv.PAGE, b7, other,
            '%d' % (n * drv.PAGE // (b7 + other)) if b7 + other else 'none'))
        time.sleep(3)                   # let the radio end the session


if __name__ == '__main__':
    main()
