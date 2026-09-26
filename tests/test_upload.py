"""Test the driver's upload against the simulated radio (fake_dm32uv.py).

Every scenario runs over the noisy link. The simulator records anything
the firmware analysis says we must never do (unsafe W, S, touching tags
0x02/0x69), and every scenario checks that list is empty.
"""
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', 'driver'))
import fake_dm32uv as fake  # noqa: E402
import baofeng_dm32uv as drv  # noqa: E402
from chirp import chirp_common, errors, memmap  # noqa: E402

time.sleep = lambda s: None
PAGE = drv.PAGE


def mem(number, name, freq, mode='FM'):
    m = chirp_common.Memory(number)
    m.name, m.freq, m.mode = name, freq, mode
    m.power = drv.POWER_LEVELS[2]
    return m


def build_radio():
    """A synthetic radio: channel pages made by the driver, other pages random."""
    blank = drv.DM32UV(memmap.MemoryMapBytes(b'\xff' * drv.DM32UV._memsize))
    for n, name, f, mode in ((1, 'Alpha', 146520000, 'FM'),
                             (2, 'Bravo', 446006250, 'NFM'),
                             (3, 'Charlie', 438500000, 'DMR'),
                             (90, 'Page one', 145500000, 'FM')):
        m = mem(n, name, f, mode)
        if n == 2:
            m.tmode, m.rtone = 'Tone', 88.5
        blank.set_memory(m)
    img = blank.get_mmap().get_packed()
    slot = lambda t: img[drv.IMAGE_TAGS.index(t) * PAGE:][:PAGE]  # noqa: E731
    rng = random.Random(7)
    pages = {0x12: (0x05000, slot(0x12)), 0x13: (0x0B3000, slot(0x13)),
             0x02: (0x0B5000, rng.randbytes(PAGE)),
             0x69: (0x0BC000, rng.randbytes(PAGE)),
             0x04: (0x04C000, rng.randbytes(PAGE))}
    flash = fake.make_flash(pages, stale=(0x010000, 0x023000))
    return flash, pages


def connect(flash, seed):
    radio = fake.FakeRadio(flash, fake.NOISY, seed=seed)
    r = drv.DM32UV(radio)
    r.status_fn = lambda s: None
    return r, radio


def download(flash, seed):
    r, radio = connect(flash, seed)
    r.sync_in()
    radio.close()
    assert not radio.violations, radio.violations
    return r


def upload(r, flash, seed, **fault):
    radio = fake.FakeRadio(flash, fake.NOISY, seed=seed)
    for k, v in fault.items():
        setattr(radio, k, v)
    r.pipe = radio
    n = drv.do_upload(r)
    radio.close()
    assert not radio.violations, radio.violations
    return n, [e for e in radio.log if e[0] == 'W'], radio


def edit(r, number, **fields):
    m = r.get_memory(number)
    for k, v in fields.items():
        setattr(m, k, v)
    r.set_memory(m)


def names(r, numbers):
    return [r.get_memory(n).name for n in numbers]


# 1. Download sees what was built.
flash, pages = build_radio()
r = download(flash, 1)
assert names(r, (1, 2, 3, 90)) == ['Alpha', 'Bravo', 'Charlie', 'Page one']
assert r.get_memory(2).rtone == 88.5 and r.get_memory(3).mode == 'DMR'
print('OK: download of the synthetic radio')

# 2. Uploading an unchanged image writes nothing.
n, writes, _ = upload(r, flash, 2)
assert n == 0 and not writes, writes
print('OK: unchanged image writes no pages')

# 3. Edits: a rename, a new frequency, and a channel on a page the radio
#    does not have yet (tag 0x14 -> first free page).
before = bytes(flash)
edit(r, 1, name='Renamed')
edit(r, 3, freq=439000000)
r.set_memory(mem(200, 'New page', 145600000))
n, writes, radio = upload(r, flash, 3)
free0 = next(a for a in range(fake.CP_START, fake.CP_END, PAGE)
             if before[a + PAGE - 1] == 0xFF)
assert n == 2, n
assert [(a, ln) for _, a, ln in writes] == [(0x05000, PAGE), (free0, PAGE)], writes
changed = {a for a in range(0, len(flash), PAGE) if flash[a:a + PAGE] != before[a:a + PAGE]}
assert changed == {0x05000, free0}, sorted(hex(a) for a in changed)
for tag in (0x02, 0x69, 0x04, 0x13):
    a = pages[tag][0]
    assert flash[a:a + PAGE] == before[a:a + PAGE], 'tag %02x changed' % tag
r2 = download(flash, 4)
assert names(r2, (1, 2, 3, 90, 200)) == ['Renamed', 'Bravo', 'Charlie', 'Page one', 'New page']
assert r2.get_memory(3).freq == 439000000 and r2.get_memory(2).rtone == 88.5
print('OK: edits written to 2 pages (one newly allocated), nothing else touched')

# 4. A byte corrupted on its way into flash is caught by the read-back and
#    the page is written again.
edit(r2, 2, name='Bravo 2')
n, writes, _ = upload(r2, flash, 5, corrupt_writes=1)
assert n == 1 and len(writes) == 2, writes
assert names(download(flash, 6), (2,)) == ['Bravo 2']
print('OK: corrupted write detected by read-back and repeated')

# 5. Two pages with the same channel tag: refuse before writing anything.
dup = bytearray(flash)
dup[0x0C2000:0x0C3000] = dup[0x05000:0x06000]
edit(r2, 1, name='Nope')
try:
    upload(r2, dup, 7)
    raise AssertionError('duplicate tag not refused')
except errors.RadioError as e:
    assert 'more than one page' in str(e), e
assert dup[0x05000:0x06000] == flash[0x05000:0x06000]
print('OK: duplicate channel tag refused, nothing written')

# 6. The write guard refuses anything but one aligned codeplug page.
link = drv._Link(fake.FakeRadio(flash))
good = b'\xff' * (PAGE - 1) + b'\x12'
for addr, data in ((0x05800, good), (0x05000, good[:-1]), (0x0C9000, good),
                   (0x05000, good[:-1] + b'\x02'), (0x05000, good[:-1] + b'\x69')):
    try:
        drv._write_page(link, addr, data, fake.CP_START, fake.CP_END)
        raise AssertionError('unsafe write allowed: %06x' % addr)
    except errors.RadioError:
        pass
assert not link.pipe.log, link.pipe.log
print('OK: write guard refuses unaligned, short, out-of-range and 0x02/0x69 pages')
