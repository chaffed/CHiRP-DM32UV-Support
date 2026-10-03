#!/usr/bin/env python3
"""Measure read errors at serial rates close to 115200 (read-only).

The received-data errors seen on the DM-32UV (only bit 7, only 0 -> 1,
only radio -> PC) look like a small baud-rate mismatch. For each rate
this identifies the radio and sends its 64-byte info query (V 00 00 40
0d) 50 times, without entering programming mode, and counts the bytes
that differ from the majority of the replies.

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
QUERY, REPLY, QUERIES = b'V\x00\x00\x40\x0D', 3 + 0x40, 50


def measure(port, rate):
    """Send the 64-byte radio info query QUERIES times at `rate` (no
    programming mode) and count bytes that differ from the majority."""
    pipe = serial.Serial(port, rate, timeout=0.5)
    pipe.dtr = pipe.rts = True
    try:
        link = drv._Link(pipe)
        drv._search(link)                 # raises if there is no answer
        link.xfer(b'PASSSTA', 3)
        link.xfer(b'SYSINFO', 1)
        replies = []
        for _ in range(QUERIES):
            link.send(QUERY)
            resp = link.recv(REPLY)
            if len(resp) == REPLY:
                replies.append(resp[3:])
            else:                       # drop the rest of a bad reply
                time.sleep(0.1)
                pipe.reset_input_buffer()
    finally:
        pipe.close()
    if len(replies) < 3:
        return None
    bit7 = other = 0
    for i in range(REPLY - 3):
        vals = [r[i] for r in replies]
        want = collections.Counter(vals).most_common(1)[0][0]
        for v in vals:
            if v != want:
                if v ^ want == 0x80:
                    bit7 += 1
                else:
                    other += 1
    return len(replies), bit7, other


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
            rate, n, n * (REPLY - 3), b7, other,
            '%d' % (n * (REPLY - 3) // (b7 + other)) if b7 + other
            else 'none'))
        time.sleep(3)                   # let the radio end the session


if __name__ == '__main__':
    main()
