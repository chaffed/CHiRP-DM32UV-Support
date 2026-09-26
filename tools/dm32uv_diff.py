#!/usr/bin/env python3
"""Compare two dumps made by dm32uv_read.py, page by page.

Pages are matched by tag, not by address, because the radio moves a page
when it rewrites it (the old copy is left behind with tag 0x00). Stale
(tag 0x00) and free (tag 0xFF) pages are ignored. Offsets in channel pages (tags 0x12-0x41) are
also shown as a channel number or VFO slot and a record offset, using the
CPS's layout (see PROTOCOL.md "Channel pages").

    python3 dm32uv_diff.py dump3 dump4
"""

import json
import os
import sys

PAGE = 0x1000
CH_TAGS = range(0x12, 0x42)
CH_SIZE, CH_PER_PAGE, CH_COUNT = 0x30, 85, 4000
VFO = {'VFO A': (47, 0xF9F), 'VFO B': (47, 0xFCF)}


def load(dump):
    info = json.load(open(os.path.join(dump, 'info.json')))
    pages = {}
    for name in os.listdir(os.path.join(dump, 'pages')):
        tag, addr = int(name[3:5], 16), int(name[6:12], 16)
        if tag in (0x00, 0xFF):     # stale and free pages
            continue
        with open(os.path.join(dump, 'pages', name), 'rb') as f:
            pages[tag] = (addr, f.read())
    return info, pages


def channel_offset(n):
    """(page, offset) of channel n, as the CPS computes it (0x47dcc0)."""
    if n < CH_PER_PAGE:
        return 0, n * CH_SIZE - 0x20
    return n // CH_PER_PAGE, (n % CH_PER_PAGE) * CH_SIZE


def where(tag, off):
    if tag not in CH_TAGS or off == 0xFFF:
        return ''
    page = tag - CH_TAGS[0]
    for name, (p, o) in VFO.items():
        if p == page and o <= off < o + CH_SIZE:
            return '%s +%02x' % (name, off - o)
    if page == 0 and off < 0x10:
        return 'ch header'
    first = 1 if page == 0 else page * CH_PER_PAGE
    for n in range(first, min(first + CH_PER_PAGE, CH_COUNT + 1)):
        p, o = channel_offset(n)
        if p == page and o <= off < o + CH_SIZE:
            return 'ch %4d +%02x' % (n, off - o)
    return ''


def runs(a, b):
    """Yield (start, end) of runs of differing bytes, merging gaps < 4."""
    start = last = None
    for i in range(len(a)):
        if a[i] != b[i]:
            if start is None:
                start = i
            elif i - last >= 4:
                yield start, last + 1
                start = i
            last = i
    if start is not None:
        yield start, last + 1


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    info_a, a = load(sys.argv[1])
    info_b, b = load(sys.argv[2])
    for key in ('v', 'v_40_0d', 'g_block', 'ident'):
        if info_a.get(key) != info_b.get(key):
            print('%s differs' % key)
    for tag in sorted(set(a) - set(b)):
        print('tag %02x: only in %s' % (tag, sys.argv[1]))
    for tag in sorted(set(b) - set(a)):
        print('tag %02x: only in %s' % (tag, sys.argv[2]))
    changed = 0
    for tag in sorted(set(a) & set(b)):
        (addr_a, da), (addr_b, db) = a[tag], b[tag]
        if da == db:
            continue
        changed += 1
        moved = '' if addr_a == addr_b else ' (moved %06x -> %06x)' % (
            addr_a, addr_b)
        print('tag %02x%s:' % (tag, moved))
        for start, end in runs(da, db):
            print('  %03x-%03x %-12s %s' % (
                start, end - 1, where(tag, start), da[start:end].hex(' ')))
            print('  %7s %-12s %s' % ('', '', db[start:end].hex(' ')))
    moved_only = [t for t in sorted(set(a) & set(b))
                  if a[t][1] == b[t][1] and a[t][0] != b[t][0]]
    if moved_only:
        print('moved, unchanged: %s' % ' '.join('%02x' % t for t in moved_only))
    print('%d tags changed' % changed)


if __name__ == '__main__':
    main()
