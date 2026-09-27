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
    hdr = blank._memobj.zone_hdr
    hdr.count, hdr.a_zone, hdr.a_pos, hdr.b_zone, hdr.b_pos = 2, 1, 1, 2, 2
    for z, name, members in ((1, 'Analog', [1, 2]), (2, 'Mixed', [3, 90, 1])):
        blank._zone(z).name = name.ljust(16, '\x00')
        blank._set_zone_members(z, members)
    blank._set_radio_ids([(1111111, 'Me'), (2222222, 'Club')])
    blank._set_contacts({1: ('Alice', 3100, 1), 2: ('Bob TG', 91, 1)})
    blank._set_rx_groups({1: ('Group A', [3100]), 2: ('Group B', [91, 3100])})
    tag, first, size, length, _count = drv.DMR_LISTS['privacy']
    base = drv.IMAGE_TAGS.index(tag) * PAGE + first
    blank.get_mmap().set(base, b'Key 1'.ljust(length, b'\x00'))
    img = blank.get_mmap().get_packed()
    slot = lambda t: img[drv.IMAGE_TAGS.index(t) * PAGE:][:PAGE]  # noqa: E731
    rng = random.Random(7)
    pages = {0x12: (0x05000, slot(0x12)), 0x13: (0x0B3000, slot(0x13)),
             0x02: (0x0B5000, rng.randbytes(PAGE)),
             0x69: (0x0BC000, rng.randbytes(PAGE)),
             0x04: (0x04C000, rng.randbytes(PAGE)),
             0x5C: (0x040000, slot(0x5C)),
             0x67: (0x009000, slot(0x67)), 0x0F: (0x00F000, slot(0x0F)),
             0x10: (0x00C000, slot(0x10)), 0x0B: (0x00D000, slot(0x0B)),
             0x44: (0x00E000, slot(0x44))}
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

# 7. CHIRP's upload entry point (sync_out) runs the same verified upload.
r3 = download(flash, 8)
edit(r3, 90, name='Via sync_out')
radio = fake.FakeRadio(flash, fake.NOISY, seed=9)
r3.pipe = radio
r3.sync_out()
radio.close()
assert not radio.violations, radio.violations
assert [(e[1], e[2]) for e in radio.log if e[0] == 'W'] == [(0x0B3000, PAGE)]
assert names(download(flash, 10), (90,)) == ['Via sync_out']
print('OK: sync_out uploads through do_upload')


# 8. Zones: add a channel to a zone. Only the zone page is written, in place,
#    and display state the radio changed since the download is kept.
ZP = pages[0x5C][0]
r4 = download(flash, 11)
bm = r4.get_bank_model()
assert [b.get_name() for b in bm.get_mappings()] == ['Analog', 'Mixed', 'New zone']
flash[ZP + 1] = 2                                       # someone browsed on the radio
bm.add_memory_to_mapping(r4.get_memory(200), bm.get_mappings()[0])
n, writes, _ = upload(r4, flash, 12)
assert n == 1 and [(a, ln) for _, a, ln in writes] == [(ZP, PAGE)], writes
r5 = download(flash, 13)
assert r5._zone_members(1) == [1, 2, 200] and r5._zone_members(2) == [3, 90, 1]
assert flash[ZP + 1] == 2, 'display state from the radio was not kept'
print('OK: zone member added; only the zone page written; display state kept')

# 9. A display pointer past the end of a zone that shrank is reset to 1.
flash[ZP + 7], flash[ZP + 3] = 2, 3                     # line B on zone 2, position 3
bm = r5.get_bank_model()
bm.remove_memory_from_mapping(r5.get_memory(1), bm.get_mappings()[1])
bm.remove_memory_from_mapping(r5.get_memory(90), bm.get_mappings()[1])
upload(r5, flash, 14)
assert download(flash, 15)._zone_members(2) == [3]
assert (flash[ZP + 7], flash[ZP + 3]) == (2, 1), (flash[ZP + 7], flash[ZP + 3])
print('OK: display pointer into a shrunken zone reset to position 1')

# 10. Browsing on the radio alone does not make the zone page look changed.
r6 = download(flash, 16)
flash[ZP + 1] = 1
n, writes, _ = upload(r6, flash, 17)
assert n == 0 and not writes, writes
print('OK: display-state changes alone write nothing')

# 11. Renaming a zone is uploaded.
bm = r6.get_bank_model()
bm.get_mappings()[1].set_name('Renamed zone')
upload(r6, flash, 18)
assert [b.get_name() for b in download(flash, 19).get_bank_model().get_mappings()] == \
    ['Analog', 'Renamed zone', 'New zone']
print('OK: zone rename uploaded')


# 12. DMR channel fields: TX contact, radio ID, RX group list and key by name.
r7 = download(flash, 20)
m = r7.get_memory(3)
extra = {x.get_name(): x for x in m.extra}
assert list(extra['tx_contact'].value.get_options()) == ['None', '1: Alice', '2: Bob TG']
assert list(extra['radio_id'].value.get_options()) == \
    ['Default', '1: Me (1111111)', '2: Club (2222222)']
extra['tx_contact'].value = '2: Bob TG'
extra['radio_id'].value = '2: Club (2222222)'
extra['rxgroup'].value = '1: Group A'
extra['privacy'].value = '1: Key 1'
extra['encrypt'].value = True
extra['timeslot'].value = '2'
r7.set_memory(m)
n, writes, _ = upload(r7, flash, 21)
assert n == 2, n                            # channel page + TX contact table (new page)
r7b = download(flash, 22)
got = {x.get_name(): str(x.value) for x in r7b.get_memory(3).extra}
assert (got['tx_contact'], got['radio_id'], got['rxgroup'], got['privacy'], got['encrypt'],
        got['timeslot']) == ('2: Bob TG', '2: Club (2222222)', '1: Group A', '1: Key 1',
                             'True', '2'), got
_c = r7b._chan(3)
assert (int(_c.radio_id), int(_c.rxgroup), int(_c.privacy), int(_c.timeslot)) == (2, 1, 1, 1)
assert r7b._tx_contact(3) == 2
tag, off = r7b._txc_loc(3)
assert r7b._page(tag)[1][off] & 1 == 1, 'digital flag not set for a DMR channel'
print('OK: TX contact, radio ID, RX group list, key and time slot set by name and uploaded')


# 13. Creating a zone: the spare "New zone" becomes zone 3 when a channel is
#     added, and is uploaded; removing its last channel removes it again.
r8 = download(flash, 24)
bm = r8.get_bank_model()
assert [b.get_name() for b in bm.get_mappings()] == ['Analog', 'Renamed zone', 'New zone']
bm.add_memory_to_mapping(r8.get_memory(2), bm.get_mappings()[2])
assert [b.get_name() for b in bm.get_mappings()] == \
    ['Analog', 'Renamed zone', 'Zone 3', 'New zone']
upload(r8, flash, 25)
r9 = download(flash, 26)
assert r9._zone_count() == 3 and r9._zone_members(3) == [2]
bm = r9.get_bank_model()
bm.remove_memory_from_mapping(r9.get_memory(2), bm.get_mappings()[2])
assert [b.get_name() for b in bm.get_mappings()] == ['Analog', 'Renamed zone', 'New zone']
print('OK: zone created from the spare, uploaded, and removed again when emptied')

# 14. Zone 29 is on the second zone page (tag 0x5D), which the radio does not
#     have yet: upload puts it on a free page.
r10 = download(flash, 27)
bm = r10.get_bank_model()
for z in range(3, 30):
    bm.add_memory_to_mapping(r10.get_memory(1), bm.get_mappings()[z - 1])
assert r10._zone_count() == 29
before = bytes(flash)
n, writes, _ = upload(r10, flash, 28)
assert n == 2, n                                        # zone pages 0x5C and 0x5D
new = [a for _, a, _ in writes if before[a + PAGE - 1] == 0xFF]
assert len(new) == 1 and flash[new[0] + PAGE - 1] == 0x5D, writes
r11 = download(flash, 29)
assert r11._zone_count() == 29 and r11._zone_members(29) == [1]
assert r11.get_bank_model().get_mappings()[28].get_name() == 'Zone 29'
print('OK: zone 29 created on a newly allocated second zone page')


# 15. Settings tab: edit radio IDs, contacts and RX groups, upload, read back.
def settings_dict(settings):
    out = {}

    def walk(group):
        for el in group:
            if hasattr(el, 'value'):
                out[el.get_name()] = el
            else:
                walk(el)
    walk(settings)
    return out


r12 = download(flash, 30)
settings = r12.get_settings()
st = settings_dict(settings)
st['con_1_name'].value = 'Alice 2'              # rename
st['con_2_name'].value = ''                     # delete Bob TG (used by channel 3)
st['con_3_name'].value = 'Carol'                # new contact in a free slot
st['con_3_id'].value = 1234567
st['con_3_type'].value = 'Private Call'
st['rid_1_id'].value = 0                        # delete radio ID 1 ("Me")
st['rid_3_id'].value = 3333333                  # add a radio ID
st['rid_3_name'].value = 'Third'
st['rxg_2_members'].value = 'Carol, 91'
r12.set_settings(settings)
assert r12._contacts() == {1: ('Alice 2', 3100, 1), 3: ('Carol', 1234567, 0)}
assert r12._radio_ids() == [(2222222, 'Club'), (3333333, 'Third')]
assert r12._tx_contact(3) == 0, 'channel still points at the deleted contact'
assert int(r12._chan(3).radio_id) == 1, 'radio ID 2 should now be 1 (Club)'
assert r12._rx_groups()[2] == ('Group B', [1234567, 91])
upload(r12, flash, 31)
r13 = download(flash, 32)
assert r13._contacts() == r12._contacts() and r13._radio_ids() == r12._radio_ids()
assert r13._rx_groups() == r12._rx_groups()
# the index page must be exactly what a rebuild from the records gives
idx_before = r13._page(drv.CONTACT_INDEX_TAG)[1]
r13._set_contacts(r13._contacts())
assert r13._page(drv.CONTACT_INDEX_TAG)[1] == idx_before
print('OK: Settings tab edits (contacts, radio IDs, RX groups) uploaded and consistent')

# 16. An unknown contact name in an RX group is refused.
settings = r13.get_settings()
settings_dict(settings)['rxg_1_members'].value = 'Nobody'
try:
    r13.set_settings(settings)
    raise AssertionError('unknown contact accepted')
except errors.InvalidValueError as e:
    assert 'Nobody' in str(e)
print('OK: unknown RX group member refused')


# 17. As in the CHIRP GUI: rename a contact, then (in a later, separate edit
#     of the same, never-refreshed settings tree) change an RX group whose
#     text still shows the old name.
r14 = download(flash, 33)
settings = r14.get_settings()
st = settings_dict(settings)
old_name = st['con_1_name'].value.get_value()
st['con_1_name'].value = 'Renamed TG'
r14.set_settings(settings)
st['rxg_1_members'].value = str(st['rxg_1_members'].value) + ', Carol'
r14.set_settings(settings)
assert old_name in str(st['rxg_1_members'].value)
assert r14._rx_groups()[1][1] == [3100, 1234567], r14._rx_groups()
print('OK: RX group edit after a contact rename in an earlier edit')
