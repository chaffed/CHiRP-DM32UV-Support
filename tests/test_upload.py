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

time.sleep = fake.virtual_sleep
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
    blank._set_scan_lists([('Scan A', [1, 2, 90], drv.SCAN_DEFAULT_OPTS)])
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
             0x44: (0x00E000, slot(0x44)), 0x11: (0x014000, slot(0x11))}
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

# 18. Remaining channel options: set them all through the extras, upload,
#     read back. TX admit follows the analog/digital list of the channel.
r15 = download(flash, 34)
m = r15.get_memory(1)                                   # analog FM channel
want = {'vox': True, 'compander': True, 'ptt_id_display': True, 'lone_work': True,
        'auto_scan': True, 'aprs_rx': True, 'aprs_ptt_analog': True,
        'aprs_ptt_digital': True, 'emerg_indicator': True, 'emerg_ack': True,
        'private_confirm': True, 'short_data_confirm': True, 'tdma_direct': True,
        'tx_admit': 'Non Match CTC', 'rx_squelch_mode': 'CTC | Optional Signaling',
        'signaling': 'Two Tone', 'ptt_id': 'Both', 'aprs_report': 'Digital'}
for x in m.extra:
    if x.get_name() in want:
        x.value = want[x.get_name()]
r15.set_memory(m)
upload(r15, flash, 35)
got = {x.get_name(): x.value.get_value() for x in download(flash, 36).get_memory(1).extra}
assert all(got[k] == v for k, v in want.items()), {k: (got[k], v) for k, v in want.items()
                                                   if got[k] != v}
_c = download(flash, 37)._chan(1)
assert (int(_c.tx_admit), int(_c.signaling), int(_c.ptt_id), int(_c.rx_squelch_mode)) == \
    (3, 2, 3, 3)
m = r15.get_memory(3)                                   # a DMR channel
assert [x.value.get_options() for x in m.extra if x.get_name() == 'tx_admit'][0] == \
    ['Always', 'Channel Idle', 'Color Code Idle']
print('OK: remaining channel options set, uploaded and read back')

# 19. Adding a channel past a gap: the skipped channels must read as empty,
#     even if they held factory template data (as on the real radio, where
#     records past the count hold e.g. 400.000 MHz).
r16 = download(flash, 38)
count = r16._count()
template = b'\xff' * 16 + bytes.fromhex('00000040000000400000000030000000') + b'\x00' * 16
r16._chan(count + 1).set_raw(template)
assert r16.get_memory(count + 1).empty          # past the count: hidden
r16.set_memory(mem(count + 3, 'After gap', 146400000))
assert r16._count() == count + 3
assert r16.get_memory(count + 1).empty and r16.get_memory(count + 2).empty, \
    'a gap channel shows up as a phantom channel'
upload(r16, flash, 39)
r17 = download(flash, 40)
assert [r17.get_memory(n).empty for n in (count + 1, count + 2)] == [True, True]
assert r17.get_memory(count + 3).name == 'After gap'
print('OK: channels skipped by a new channel read as empty')


# 20. Scan lists: edit members and modes, add a list, pick one per channel,
#     delete a channel that is in a list, delete a list channels use.
r18 = download(flash, 41)
assert [(n, m) for n, m, _o in r18._scan_lists()] == [('Scan A', [1, 2, 90])]
settings = r18.get_settings()
st = settings_dict(settings)
st['scan_1_members'].value = '2, 90, 1'
st['scan_1_ctc'].value = 'Not Detection CTC'
st['scan_1_tx'].value = 'Designed Channel'
st['scan_2_name'].value = 'Scan B'                  # the spare row: new list
st['scan_2_members'].value = '3'
r18.set_settings(settings)
edit(r18, 3, name=r18.get_memory(3).name)          # no-op
m = r18.get_memory(3)
[x for x in m.extra if x.get_name() == 'scanlist'][0].value = '2: Scan B'
r18.set_memory(m)
upload(r18, flash, 42)
r19 = download(flash, 43)
lists = r19._scan_lists()
assert [(n, mb) for n, mb, _o in lists] == [('Scan A', [2, 90, 1]), ('Scan B', [3])], lists
assert lists[0][2][0] == 0x20, 'CTC/TX mode byte'
opts = lists[0][2]                                  # designed channel (3-4) may follow
assert opts[1:3] + opts[5:] == drv.SCAN_DEFAULT_OPTS[1:3] + drv.SCAN_DEFAULT_OPTS[5:], \
    'other options must be kept'
assert int(r19._chan(3).scanlist) == 2
m = r19.get_memory(90)
m.empty = True
r19.set_memory(m)                                   # delete a scan list member
assert r19._scan_lists()[0][1] == [2, 1]
settings = r19.get_settings()
settings_dict(settings)['scan_1_name'].value = ''   # delete list 1
r19.set_settings(settings)
assert [n for n, _m, _o in r19._scan_lists()] == ['Scan B']
assert int(r19._chan(3).scanlist) == 1, 'channel must follow Scan B to number 1'
upload(r19, flash, 44)
assert [n for n, _m, _o in download(flash, 45)._scan_lists()] == ['Scan B']
print('OK: scan lists edited, created, deleted; channel refs follow; deleted channel removed')


# 21. Radio settings (tag 0x04): change a few, upload, read back; the radio's
#     current A/B display state in byte 0x80 must survive the upload.
r20 = download(flash, 46)
SP = pages[0x04][0]
settings = r20.get_settings()
st = settings_dict(settings)
st['set_set_opts_tot'].value = '180 s'
st['set_set_opts_vox_delay'].value = '0.5 s'
st['set_set_power_line1'].value = 'Hello'
st['set_set_power_key_tone'].value = not st['set_set_power_key_tone'].value.get_value()
st['set_set_work_dual_watch'].value = 'Double Wait'
r20.set_settings(settings)
flash[SP + 0x80] ^= 0x3E                               # someone browsed on the radio
radio_state = flash[SP + 0x80] & 0x3E
n, writes, _ = upload(r20, flash, 47)
assert [(a, ln) for _, a, ln in writes] == [(SP, PAGE)], writes
got = {k: v.value.get_value() for k, v in settings_dict(download(flash, 48).get_settings()).items()
       if k.startswith('set_')}
assert got['set_set_opts_tot'] == '180 s' and got['set_set_opts_vox_delay'] == '0.5 s'
assert got['set_set_power_line1'] == 'Hello' and got['set_set_work_dual_watch'] == 'Double Wait'
assert flash[SP + 0x80] & 0x3E == radio_state, 'radio display state overwritten'
assert flash[SP + 0xA3] == 5, 'VOX delay is stored as value + 3'
# applying the settings tab unchanged writes nothing
r21 = download(flash, 49)
r21.set_settings(r21.get_settings())
n, writes, _ = upload(r21, flash, 50)
assert n == 0 and not writes, writes
print('OK: radio settings uploaded; display state kept; unchanged settings write nothing')

# 22. Zone management on the Settings tab: channel order in a zone, delete a
#     zone in the middle, swap zones; the radio's current-zone pointers follow.
r22 = download(flash, 51)
zl = r22._zone_list()
assert len(zl) >= 5, len(zl)
hdr = r22._memobj.zone_hdr
hdr.a_zone, hdr.a_pos, hdr.b_zone, hdr.b_pos = 5, 1, 2, 1
settings = r22.get_settings()
st = settings_dict(settings)
st['zone_1_members'].value = ', '.join(map(str, reversed(zl[0][1])))
st['zone_5_members'].value = ''                        # delete zone 5
order = [2, 1] + list(range(3, len(zl) + 1))
st['zone_order'].value = ', '.join(map(str, order))
r22.set_settings(settings)
new = r22._zone_list()
expect = [zl[1], (zl[0][0], list(reversed(zl[0][1])))] + [
    zl[z - 1] for z in range(3, len(zl) + 1) if z != 5]
assert new == expect, (new[:4], expect[:4])
assert (int(hdr.a_zone), int(hdr.b_zone)) == (1, 1), (int(hdr.a_zone), int(hdr.b_zone))
upload(r22, flash, 52)
assert download(flash, 53)._zone_list() == expect
for bad, text in (('zone_order', '1, 1'), ('zone_1_members', '9999'), ('zone_order', 'x')):
    settings = r22.get_settings()
    settings_dict(settings)[bad].value = text
    try:
        r22.set_settings(settings)
        raise AssertionError('accepted %s=%r' % (bad, text))
    except errors.InvalidValueError:
        pass
print('OK: zones reordered and deleted from the Settings tab; pointers follow; bad input refused')

# 23. More radio settings: a key function, a colour, the time zone, DMR
#     timing, a menu item; upload and read back; stored-offset fields.
r23 = download(flash, 54)
settings = r23.get_settings()
st = settings_dict(settings)
st['set_set_work_key_p1_short'].value = 'Flashlight'
st['set_set_display_a_zone_color'].value = 'Green'
st['set_set_gps_time_zone'].value = 'UTC +1:00'
st['set_set_dmr_active_wait'].value = '360 ms'
st['set_set_dmr_active_retries'].value = '5'
st['set_set_menu_gps'].value = not st['set_set_menu_gps'].value.get_value()
r23.set_settings(settings)
upload(r23, flash, 55)
got = {k: v.value.get_value() for k, v in settings_dict(download(flash, 56).get_settings()).items()}
assert (got['set_set_work_key_p1_short'], got['set_set_display_a_zone_color'],
        got['set_set_gps_time_zone'], got['set_set_dmr_active_wait'],
        got['set_set_dmr_active_retries']) == ('Flashlight', 'Green', 'UTC +1:00', '360 ms', '5')
assert flash[SP + 0x91] == 41 and flash[SP + 0x3A] == 5 and flash[SP + 0x41] == 13
assert flash[SP + 0x62] == 3 and flash[SP + 0x63] == 5, 'stored as list position + 1'
print('OK: keys, colours, GPS, DMR timing and menu items uploaded and read back')


# 24. Identification: detect_from_serial accepts a DM-32UV and refuses other
#     radios (also over the noisy link); an untested firmware only warns.
import logging  # noqa: E402
for seed in range(60, 66):
    assert drv.DM32UV.detect_from_serial(fake.FakeRadio(flash, fake.NOISY, seed=seed)) \
        is drv.DM32UV
for probe in ('detect', 'download'):
    other = fake.FakeRadio(flash, fake.NOISY, seed=66, model=b'UV17PRO')
    try:
        if probe == 'detect':
            drv.DM32UV.detect_from_serial(other)
        else:
            r = drv.DM32UV(other)
            r.status_fn = lambda s: None
            r.sync_in()
        raise AssertionError('other radio accepted by %s' % probe)
    except errors.RadioError as e:
        assert 'UV17PRO' in str(e) and 'not as a Baofeng DM-32UV' in str(e), e
    assert not [x for x in other.log if x[0] in ('R', 'W')], 'talked on after a wrong model'
warnings = []
handler = logging.Handler()
handler.emit = lambda rec: warnings.append(rec.getMessage())
drv.LOG.addHandler(handler)
newer = fake.FakeRadio(flash, fake.NOISY, seed=67, firmware=b'DM32.01.01.048')
r = drv.DM32UV(newer)
r.status_fn = lambda s: None
r.sync_in()
drv.LOG.removeHandler(handler)
assert any('DM32.01.01.048' in w and 'not been tested' in w for w in warnings), warnings
assert r._metadata['dm32uv_firmware'] == 'DM32.01.01.048'
print('OK: DM-32UV detected; other radios refused before any transfer; new firmware warns')


# 25. Deleting every channel on a page: the emptied page is still uploaded
#     (it is all 0xFF in the image, but the radio has it).
def small_radio(channels, zones, extra=None):
    """Flash with the given channels and zones, pages placed in tag order."""
    b = drv.DM32UV(memmap.MemoryMapBytes(b'\xff' * drv.DM32UV._memsize))
    b._put(0x04, 0, b'\x00' * (PAGE - 1))
    for n, f in channels:
        b.set_memory(mem(n, 'Ch%d' % n, f))
    hdr = b._memobj.zone_hdr
    hdr.count, hdr.a_zone, hdr.a_pos, hdr.b_zone, hdr.b_pos = len(zones), 1, 1, 1, 1
    for z, (name, members) in enumerate(zones, 1):
        b._zone(z).name = name.ljust(16, '\x00')
        b._set_zone_members(z, members)
    if extra:
        extra(b)
    img = b.get_mmap().get_packed()
    pages = {}
    for i, t in enumerate(drv.IMAGE_TAGS):
        data = img[i * PAGE:(i + 1) * PAGE]
        if data[:-1] != b'\xff' * (PAGE - 1):
            pages[t] = (0x20000 + i * PAGE, data)
    return fake.make_flash(pages)


flash25 = small_radio([(1, 146520000), (90, 145500000), (200, 147000000)],
                      [('Z', [1, 90, 200])])
r = download(flash25, 70)
e = r.get_memory(90)
e.empty = True
r.set_memory(e)
upload(r, flash25, 71)
assert download(flash25, 72).get_memory(90).empty, 'emptied page not uploaded'
print('OK: a channel page emptied by deleting its channels is uploaded')

# 26. A lost W acknowledgement: the radio ends the session after 2 s of
#     silence; the driver reconnects, checks the page and carries on.
r = download(flash25, 73)
edit(r, 1, name='After lost ACK')
edit(r, 200, name='Second page')
n, writes, radio = upload(r, flash25, 74, drop_acks=1)
assert radio.sessions == 1, radio.sessions
assert names(download(flash25, 75), (1, 200)) == ['After lost ACK', 'Second page']
print('OK: lost write ACK: reconnected and finished the upload')

# 27. Passwords: CHIRP can't enter one, so a write password stops an upload
#     before any W, and a read password stops a download.
SP25 = [a for a in range(fake.CP_START, fake.CP_END, PAGE)
        if flash25[a + PAGE - 1] == 0x04][0]
flash25[SP25 + 0x439] = 0xA5                            # write password on
r = download(flash25, 76)                               # reading is allowed
edit(r, 1, name='Not written')
radio = fake.FakeRadio(flash25, fake.NOISY, seed=77)
r.pipe = radio
try:
    drv.do_upload(r)
    raise AssertionError('uploaded despite a write password')
except errors.RadioError as e:
    assert 'write password' in str(e), e
assert not [x for x in radio.log if x[0] == 'W'], 'wrote despite a write password'
flash25[SP25 + 0x439], flash25[SP25 + 0x43A] = 0x00, 0xA5    # read password on
try:
    download(flash25, 78)
    raise AssertionError('downloaded despite a read password')
except errors.RadioError as e:
    assert 'read password' in str(e), e
flash25[SP25 + 0x43A] = 0x00
print('OK: write password refuses upload, read password refuses download')

# 28. The radio's current zone and position follow a zone reorder done in
#     CHIRP, even though the radio's live values are used.
flash28 = small_radio([(n, 146000000 + n * 25000) for n in range(1, 10)],
                      [('One', [1, 2, 3]), ('Two', [4, 5]), ('Three', [6, 7, 8, 9])])
ZP28 = [a for a in range(fake.CP_START, fake.CP_END, PAGE)
        if flash28[a + PAGE - 1] == 0x5C][0]
flash28[ZP28 + 5], flash28[ZP28 + 1] = 3, 2             # line A: zone Three, 2nd channel (7)
flash28[ZP28 + 7], flash28[ZP28 + 3] = 2, 2             # line B: zone Two, channel 5
r = download(flash28, 80)
settings = r.get_settings()
st = settings_dict(settings)
st['zone_order'].value = '3, 1'
st['zone_2_members'].value = ''                         # zone Two deleted
st['zone_3_members'].value = '9, 7, 6'                  # 8 dropped, order changed
r.set_settings(settings)
upload(r, flash28, 81)
assert download(flash28, 82)._zone_list() == [('Three', [9, 7, 6]), ('One', [1, 2, 3])]
assert (flash28[ZP28 + 5], flash28[ZP28 + 1]) == (1, 2), 'line A did not follow channel 7'
assert (flash28[ZP28 + 7], flash28[ZP28 + 3]) == (1, 1), 'line B not reset after deletion'
print('OK: radio display follows zones reordered and deleted in CHIRP')


# 29. Names CHIRP can't show (vendor CPS names in GBK), clamped values and
#     250 zones: everything loads, and nothing changes unless edited.
def odd_names(b):
    b._set_contacts({1: ('X', 91, 1), 2: ('Plain', 92, 1)})
    tag, off = b._contact_loc(1)
    b._put(tag, off + 2, '中文'.encode('gbk'))
    b._set_radio_ids([(16777215, 'Odd')])
    b._memobj.zone_hdr.count = 250
    for z in range(3, 251):
        b._zone(z).name = ('Z%d' % z).ljust(16, '\x00')
        b._set_zone_members(z, [1])
    b._zone(2).name.set_raw('区'.encode('gbk').ljust(16, b'\x00'))


flash29 = small_radio([(1, 146520000)], [('A', [1]), ('B', [1])], odd_names)
r = download(flash29, 83)
before = r.get_mmap().get_packed()
settings = r.get_settings()
st = settings_dict(settings)
assert all(v.value.initialized for v in st.values()), [
    k for k, v in st.items() if not v.value.initialized]
assert str(st['con_1_name'].value) == '????' and str(st['zone_2_name'].value) == '??'
r.set_settings(settings)
assert r.get_mmap().get_packed() == before, 'unchanged settings changed the image'
st['con_1_id'].value = 3100                             # edit the odd contact's ID
st['zone_250_name'].value = 'Last'                      # edit with 250 zones
r.set_settings(settings)
assert r._contacts()[1] == ('中文'.encode('gbk').decode('latin-1'), 3100, 1)
assert r._zone_list()[249][0] == 'Last' and r._radio_ids() == [(16777215, 'Odd')]
print('OK: odd names, clamped IDs and 250 zones load; kept unless edited')

# 30. Speed: 4000 channels and 800 contacts open in a few seconds.
big = drv.DM32UV(memmap.MemoryMapBytes(b'\xff' * drv.DM32UV._memsize))
for n in range(1, 4001):
    big.set_memory(mem(n, 'C%d' % n, 440000000 + n * 12500, 'DMR' if n % 2 else 'FM'))
big._set_contacts({k: ('TG %d' % k, 1000 + k, 1) for k in range(1, 801)})
t0 = time.time()
for n in range(1, 4001):
    big.get_memory(n)
elapsed = time.time() - t0
assert elapsed < 10, '%.1f s to read 4000 channels' % elapsed
print('OK: 4000 channels with 800 contacts read in %.1f s' % elapsed)

# 31. APRS settings and the per-channel report channel: edited on the
#     Settings tab, uploaded, stored as the CPS stores them; bad coordinates
#     refused; the password bytes next to them untouched.
def aprs_radio(b):
    b.set_memory(mem(5, 'DMR Rpt', 441000000, 'DMR'))
    b._put(0x04, 0x431, b'1234\xff\xff\xff\xff')     # a password value, flag off


flash31 = small_radio([(1, 146520000)], [('A', [1])], aprs_radio)
SP31 = [a for a in range(fake.CP_START, fake.CP_END, PAGE)
        if flash31[a + PAGE - 1] == 0x04][0]
r = download(flash31, 90)
settings = r.get_settings()
st = settings_dict(settings)
assert 'Current Channel' in st['set_set_aprs_report_channel_1'].value.get_options()
assert '5: DMR Rpt' in st['set_set_aprs_report_channel_1'].value.get_options()
assert '1: Ch1' not in st['set_set_aprs_report_channel_1'].value.get_options(), 'analog offered'
for key, value in (('send_interval', '120 s'), ('fixed_beacon', True),
                   ('latitude', '5.5'), ('lat_hemi', 'S'), ('longitude', '118'),
                   ('lon_hemi', 'W'), ('upload_number', 310999), ('call_type', 'Group'),
                   ('active_delay', '300 ms'), ('report_channel_1', '5: DMR Rpt')):
    st['set_set_aprs_' + key].value = value
r.set_settings(settings)
m = r.get_memory(5)
for s_ in m.extra:
    if s_.get_name() == 'aprs_channel':
        s_.value = '2'
r.set_memory(m)
upload(r, flash31, 91)
page = flash31[SP31:SP31 + PAGE]
assert page[0x301] == 4 and page[0x302] & 1 == 1
assert page[0x306:0x30F] == b'05.500000' and page[0x30F] == 1
assert page[0x310:0x319] == b'118.00000' and page[0x319] == 1
assert page[0x31E:0x320] == b'\x05\x00' and page[0x320:0x32E] == bytes(14)
assert page[0x330] == 3 and page[0x331] & 1 == 1
assert page[0x332:0x335] == (310999).to_bytes(3, 'little')
assert page[0x431:0x435] == b'1234', 'password bytes changed'
r2 = download(flash31, 92)
got = {k: str(v.value) for k, v in settings_dict(r2.get_settings()).items()}
assert (got['set_set_aprs_latitude'], got['set_set_aprs_longitude']) == ('5.500000', '118.00000')
assert got['set_set_aprs_report_channel_1'] == '5: DMR Rpt'
assert int(r2._chan(5).aprs_channel) == 1
for bad in ('91', '-1', 'north'):
    settings = r2.get_settings()
    settings_dict(settings)['set_set_aprs_latitude'].value = bad
    try:
        r2.set_settings(settings)
        raise AssertionError('latitude %r accepted' % bad)
    except errors.InvalidValueError:
        pass
print('OK: APRS settings and report channel uploaded in the CPS format')


# 32. DTMF (tag 0x06): system options, codes and DTMF contacts, in the
#     CPS's storage format (one digit value per byte, 0xFF-terminated).
def dtmf_radio(b):
    page = bytearray(b'\xff' * (PAGE - 1))
    page[0x000:0x007] = bytes([4, 5, 6, 14, 1, 2, 3])            # 456*123
    page[0x100:0x110] = bytes([0x0F, 0, 0, 0, 10, 1, 1, 2, 3, 10, 14, 2, 0, 0, 0, 0])
    page[0x110:0x117] = bytes([4, 5, 6, 13, 1, 2, 3])            # 456D123
    page[0x1FF] = 2
    for k, (name, digits) in enumerate(((b'AContact 1', [9, 6, 0, 0, 0]),
                                        (b'AContacts 2', [9, 6, 0, 0, 1])), 1):
        page[0x1E0 + 0x20 * k:0x1F0 + 0x20 * k] = name.ljust(16, b'\x00')
        page[0x1F0 + 0x20 * k:0x200 + 0x20 * k] = bytes(digits + [0] * 11)
    page[0xA20:0xA30] = bytes(range(16))                          # BDC1200: kept
    b._put(0x06, 0, bytes(page))
    b.set_memory(mem(2, 'Two tone', 146600000))


flash32 = small_radio([(1, 146520000)], [('A', [1])], dtmf_radio)
DP32 = [a for a in range(fake.CP_START, fake.CP_END, PAGE)
        if flash32[a + PAGE - 1] == 0x06][0]
r = download(flash32, 93)
settings = r.get_settings()
st = settings_dict(settings)
got = {k: str(v.value) for k, v in st.items()}
assert (got['set_dtmf_code1'], got['set_dtmf_ptt_id_up'], got['set_dtmf_self_id'],
        got['set_dtmf_group_code'], got['set_dtmf_interval_sign'],
        got['set_dtmf_auto_answer'], got['set_dtmf_pre_carrier'],
        got['set_dtmf_auto_reset'], got['set_dtmf_side_tone']) == (
    '456*123', '456D123', '123', 'A', '*', 'Alert Tone And Ack', '300 ms', '10 s',
    'True'), got
assert (got['dtc_1_name'], got['dtc_1_number'], got['dtc_2_number']) == (
    'AContact 1', '96000', '96001')
r.set_settings(settings)
assert flash32[DP32:DP32 + PAGE - 1] == r.get_mmap().get(
    drv.IMAGE_TAGS.index(0x06) * PAGE, PAGE - 1), 'unchanged DTMF settings changed the page'
for key, value in (('set_dtmf_code2', '#1a'), ('set_dtmf_kill_code', 'C999'),
                   ('set_dtmf_self_id', '7'), ('set_dtmf_group_code', 'Off'),
                   ('set_dtmf_pre_carrier', '400 ms'), ('set_dtmf_ptt_id_pause', '6 s'),
                   ('dtc_2_name', 'Base'), ('dtc_3_name', 'Mobile'),
                   ('dtc_3_number', '12345')):
    st[key].value = value
r.set_settings(settings)
m = r.get_memory(2)
for s_ in m.extra:
    if s_.get_name() == 'signaling':
        s_.value = 'Two Tone'
    elif s_.get_name() == 'rx_signal':
        s_.value = '3'
    elif s_.get_name() == 'tx_signal':
        s_.value = '8'
r.set_memory(m)
n, writes, _ = upload(r, flash32, 94)
page = flash32[DP32:DP32 + PAGE]
assert page[0x010:0x014] == bytes([15, 1, 10, 0xFF]), page[0x10:0x14].hex()
assert page[0x140:0x145] == bytes([12, 9, 9, 9, 0xFF])
assert page[0x106:0x109] == bytes([0, 0, 7]), 'self ID not zero-padded'
assert page[0x109] == 0xFF and page[0x100] == 17 and page[0x10C] == 6
assert page[0x1FF] == 3 and page[0x220:0x225] == b'Base\x00'
assert page[0x240:0x246] == b'Mobile' and page[0x250:0x256] == bytes([1, 2, 3, 4, 5, 0])
assert page[0xA20:0xA30] == bytes(range(16)), 'BDC1200 bytes changed'
r2 = download(flash32, 95)
_m = r2._chan(2)
assert (int(_m.signaling), int(_m.rx_signal), int(_m.tx_signal)) == (2, 3, 8)
settings = r2.get_settings()
st = settings_dict(settings)
st['dtc_3_name'].value = ''                                  # remove the last one
r2.set_settings(settings)
assert r2._dtmf_contacts() == [('AContact 1', '96000'), ('Base', '96001')]
settings = r2.get_settings()
settings_dict(settings)['dtc_1_name'].value = ''             # not the last: refused
try:
    r2.set_settings(settings)
    raise AssertionError('removed a DTMF contact in the middle')
except errors.InvalidValueError:
    pass
print('OK: DTMF options, codes, contacts and channel signaling systems uploaded')
