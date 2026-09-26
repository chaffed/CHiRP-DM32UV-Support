"""Run dm32uv_read.py against the simulated radio (tests/fake_dm32uv.py).

The tool runs twice: over a clean link, then over a noisy one that mimics
the real cable (bit 7 of received bytes set about 1 time in 500, plus rarer
faults the real link hasn't shown yet). Both runs must give exactly the
simulated flash contents.
"""
import json
import os
import random
import runpy
import sys
import tempfile
import time

import serial

sys.path.insert(0, os.path.dirname(__file__))
import fake_dm32uv as fake  # noqa: E402

rng = random.Random(1)
tags = [0x02, 0x03, 0x0B] + list(range(0x12, 0x42)) + [0x5C]
pages = {t: (fake.CP_START + (i + i // 3) * 0x1000, rng.randbytes(0x1000))
         for i, t in enumerate(tags)}          # spread pages out, leave gaps
stale = (0x0C1000, 0x0C7000)                   # tag 0x00 pages, as on the real radio
flash = fake.make_flash(pages, stale)
want = {'tag%02x_%06x.bin' % (t, a): a for t, (a, _) in pages.items()}
want.update({'tag00_%06x.bin' % a: a for a in stale})

time.sleep = lambda s: None
TOOL = os.path.join(os.path.dirname(__file__), '..', 'tools', 'dm32uv_read.py')
TOP = sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp()

for name, noise in (('clean', fake.CLEAN), ('noisy', fake.NOISY)):
    radio = fake.FakeRadio(flash, noise)
    serial.Serial = lambda *a, **k: radio
    out = os.path.join(TOP, name)
    print('==== %s link' % name)
    sys.argv = ['dm32uv_read.py', 'FAKE', '-o', out, '--contacts']
    runpy.run_path(TOOL, run_name='__main__')

    info = json.load(open(os.path.join(out, 'info.json')))
    assert 'error' not in info, info['error']
    assert (info['cp_start'], info['cp_end']) == (fake.CP_START, fake.CP_END), info
    assert not radio.violations, radio.violations
    files = sorted(os.listdir(os.path.join(out, 'pages')))
    assert files == sorted(want), files
    for fname, a in want.items():
        got = open(os.path.join(out, 'pages', fname), 'rb').read()
        assert got == flash[a:a + 0x1000], '%s differs from flash' % fname
    stats = info['link_stats']
    if noise is fake.NOISY:
        assert stats.get('bit-7 errors corrected') and stats.get('other disagreements'), stats
    print('OK: %s link, %d pages match the simulated flash' % (name, len(files)))
