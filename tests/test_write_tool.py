"""Test tools/dm32uv_write.py against the simulated radio, on the noisy link."""
import contextlib
import io
import os
import runpy
import sys
import tempfile
import time

import serial

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fake_dm32uv as fake  # noqa: E402

TOOL = os.path.join(HERE, '..', 'tools', 'dm32uv_write.py')
PAGE = fake.PAGE
time.sleep = lambda s: None

pages = {0x12: (0x05000, bytes(range(256)) * 16), 0x13: (0x0B3000, b'\x13' * PAGE),
         0x02: (0x0B5000, b'\x02' * PAGE)}
flash = fake.make_flash(pages, stale=(0x010000,))
tmp = tempfile.mkdtemp()
os.makedirs(os.path.join(tmp, 'backup', 'pages'))
with open(os.path.join(tmp, 'backup', 'pages', 'tag12_005000.bin'), 'wb') as f:
    f.write(flash[0x05000:0x06000])


def run(*argv, seed=1):
    radio = fake.FakeRadio(flash, fake.NOISY, seed=seed)
    serial.Serial = lambda *a, **k: radio
    sys.argv = ['dm32uv_write.py', 'FAKE', '-o', os.path.join(tmp, 'log')] + list(argv)
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            runpy.run_path(TOOL, run_name='__main__')
        code = 0
    except SystemExit as e:
        code = e.code
    radio.close()
    assert not radio.violations, radio.violations
    return code, [e for e in radio.log if e[0] == 'W'], out.getvalue()


# 1. Without --yes nothing is written.
before = bytes(flash)
code, writes, out = run('--noop', '12')
assert code == 0 and not writes and 'dry run' in out, out
print('OK: dry run writes nothing')

# 2. No-op write: one W to the same page, flash unchanged, tags unchanged.
code, writes, out = run('--noop', '12', '--yes', seed=2)
assert code == 0, out
assert [(a, n) for _, a, n in writes] == [(0x05000, PAGE)], writes
assert bytes(flash) == before
assert 'tags unchanged' in out, out
print('OK: no-op write rewrites the page in place and changes nothing')

# 3. Restore: the radio's page changed; restoring puts the backup back.
flash[0x05010:0x05020] = b'\x00' * 16
code, writes, out = run('--restore', os.path.join(tmp, 'backup'), '--tag', '12',
                        '--yes', seed=3)
assert code == 0 and len(writes) == 1, out
assert bytes(flash) == before
print('OK: restore puts the backed-up page back')

# 4. Restoring an identical page writes nothing.
code, writes, out = run('--restore', os.path.join(tmp, 'backup'), '--tag', '12',
                        '--yes', seed=4)
assert code == 0 and not writes and 'nothing to do' in out, out
print('OK: restore of an identical page writes nothing')

# 5. Tags the driver never uploads are refused before anything is sent.
for tag in ('02', '69', '65'):
    code, writes, out = run('--noop', tag, '--yes', seed=5)
    assert code == 2 and not writes and 'only pages the driver uploads' in out, out
print('OK: tags 02, 69 and 65 refused')

# 6. A tag the radio has no page for is refused.
code, writes, out = run('--noop', '20', '--yes', seed=6)
assert code == 2 and not writes and 'has 0 pages with tag 20' in out, out
print('OK: missing tag refused')
