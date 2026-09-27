#!/usr/bin/env python3
"""Build the synthetic CHIRP test image for the DM-32UV driver.

Everything in it is made up here; no data from a real radio. Channels
cover analog and DMR, all tone modes, duplex variants and power levels;
there are two zones, two scan lists, radio IDs, contacts, RX group lists
a key, and DTMF, two-tone and five-tone settings.

    python3 make_test_image.py tests/images/Baofeng_DM-32UV.img
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'driver'))
import baofeng_dm32uv as drv  # noqa: E402
from chirp import chirp_common, memmap  # noqa: E402

PAGE = drv.PAGE

# number, name, freq (Hz), mode, duplex, offset, power, tone settings
CHANNELS = [
    (1, 'Simplex FM', 146520000, 'FM', '', 0, 2, {}),
    (2, 'Rpt Tone', 146940000, 'FM', '-', 600000, 2,
     {'tmode': 'Tone', 'rtone': 100.0}),
    (3, 'Rpt TSQL', 147330000, 'FM', '+', 600000, 1,
     {'tmode': 'TSQL', 'ctone': 131.8}),
    (4, 'UHF DCS', 446000000, 'NFM', '', 0, 0,
     {'tmode': 'DTCS', 'dtcs': 23, 'rx_dtcs': 23, 'dtcs_polarity': 'NN'}),
    (5, 'DCS Rev', 446100000, 'NFM', '', 0, 0,
     {'tmode': 'DTCS', 'dtcs': 754, 'rx_dtcs': 754, 'dtcs_polarity': 'RR'}),
    (6, 'Cross', 145500000, 'FM', '', 0, 2,
     {'tmode': 'Cross', 'cross_mode': 'Tone->DTCS', 'rtone': 88.5,
      'rx_dtcs': 125}),
    (7, 'UHF Rpt', 442100000, 'FM', '+', 5000000, 2,
     {'tmode': 'Tone', 'rtone': 88.5}),
    (8, 'Split', 144390000, 'FM', 'split', 145390000, 1, {}),
    (9, 'RX only', 162550000, 'NFM', 'off', 0, 0, {}),
    (10, 'DMR Local', 441000000, 'DMR', '+', 5000000, 2, {}),
    (11, 'DMR TS2', 441000000, 'DMR', '+', 5000000, 2, {}),
    (12, 'DMR Simplex', 441000000, 'DMR', '', 0, 1, {}),
    (13, 'PMR 1', 446006250, 'NFM', '', 0, 0, {}),
    (14, 'Odd step', 434043500, 'FM', '', 0, 2, {}),
]
DMR_EXTRA = {1: {'scanlist': '1: Analog scan'},
             10: {'colorcode': 1, 'timeslot': '1', 'tx_contact': '1: Local',
                  'rxgroup': '1: Local RX', 'radio_id': '1: Main (1234567)',
                  'scanlist': '2: DMR scan'},
             11: {'colorcode': 1, 'timeslot': '2', 'tx_contact': '2: Worldwide',
                  'rxgroup': '2: Wide RX'},
             12: {'colorcode': 3, 'timeslot': '1', 'tx_contact': '3: Test Call',
                  'radio_id': '2: Spare (7654321)'}}
# Made-up IDs: radio IDs (id, name); contacts slot: (name, id, call type);
# RX groups n: (name, member IDs)
RADIO_IDS = [(1234567, 'Main'), (7654321, 'Spare')]
CONTACTS = {1: ('Local', 9, 1), 2: ('Worldwide', 91, 1),
            3: ('Test Call', 1000001, 0), 4: ('All Call', 16777215, 2)}
RX_GROUPS = {1: ('Local RX', [9]), 2: ('Wide RX', [9, 91])}
SCAN_LISTS = [('Analog scan', [1, 2, 3, 4, 5, 7]), ('DMR scan', [10, 11, 12])]
SETTINGS = [('set_power', 'poweron_type', 1), ('set_power', 'line1', 'CHIRP TEST' + '\x00' * 4),
            ('set_power', 'line2', 'DM-32UV' + '\x00' * 7), ('set_power', 'key_tone', 1),
            ('set_power', 'voice_prompt', 1), ('set_opts', 'tot', 22),
            ('set_opts', 'vox_level', 2), ('set_opts', 'vox_delay', 10),
            ('set_opts', 'language', 1), ('set_opts', 'tbst', 2),
            ('set_display', 'backlight', 4), ('set_display', 'menu_exit', 2),
            ('set_work', 'dual_watch', 2), ('set_work', 'dual_watch_hang', 1)]
LISTS = {'privacy': ['Test key']}
ZONES = [('Analog', [1, 2, 3, 4, 5, 6, 7, 8, 9, 13, 14]),
         ('Digital', [10, 11, 12])]


def dtmf_page():
    """Made-up DTMF settings (tag 0x06): codes, options, two contacts."""
    page = bytearray(b'\xff' * (PAGE - 1))
    page[0x000:0x007] = bytes([1, 2, 3, 14, 4, 5, 6])            # 123*456
    page[0x100:0x110] = bytes([15, 0, 0, 0, 10, 1, 1, 2, 3, 10, 14, 2,
                               0, 0, 0, 0])
    page[0x110:0x114] = bytes([1, 0, 1, 0xFF])                   # PTT ID up
    page[0x1FF] = 2
    for k, (name, digits) in enumerate(((b'Base', [1, 0, 0]),
                                        (b'Mobile', [2, 0, 0])), 1):
        page[0x1E0 + 0x20 * k:0x1F0 + 0x20 * k] = name.ljust(16, b'\x00')
        page[0x1F0 + 0x20 * k:0x200 + 0x20 * k] = bytes(digits).ljust(
            5, b'\xff') + bytes(11)
    return bytes(page)


def signal_page():
    """Made-up two-tone and five-tone settings (tag 0x03)."""
    page = bytearray(b'\xff' * (PAGE - 1))
    page[0x001] = 1
    page[0x030:0x041] = bytes([5, 5, 5, 5, 0, 0xFF, 0]) + bytes.fromhex(
        '1027983a204ea861ff') + bytes([10])     # 1000/1500/2000/2500 Hz
    page[0x041:0x045] = bytes.fromhex('0103ffff')
    page[0x220:0x248] = ('Test').encode('utf-16-le').ljust(0x20, b'\x00') + \
        bytes.fromhex('feff1027983affff')
    page[0x730:0x740] = bytes.fromhex('0506070809' '00f1ffffff0f0a0a0001ff')
    page[0x750:0x760] = bytes.fromhex('00f10a0b0cffffffffffffffffffffff')
    page[0x820:0x829] = bytes.fromhex('000102030405000007')
    page[0x840:0x850] = b'Test call\x00'.ljust(16, b'\xff')
    return bytes(page)


def build():
    radio = drv.DM32UV(memmap.MemoryMapBytes(b'\xff' * drv.DM32UV._memsize))
    mmap = radio.get_mmap()
    for kind, names in LISTS.items():
        tag, first, size, length, _count = drv.DMR_LISTS[kind]
        base = drv.IMAGE_TAGS.index(tag) * PAGE + first
        for i, name in enumerate(names):
            mmap.set(base + i * size, name.encode().ljust(length, b'\x00'))
    # A settings page (tag 0x04) with plausible values.
    radio._put(0x04, 0, b'\x00' * (PAGE - 1))
    for sname, field, value in SETTINGS:
        setattr(getattr(radio._memobj, sname), field, value)
    radio._put(0x03, 0, signal_page())
    radio._put(0x06, 0, dtmf_page())
    radio._set_radio_ids(RADIO_IDS)
    radio._set_contacts(CONTACTS)
    radio._set_rx_groups(RX_GROUPS)
    radio._set_scan_lists([(name, members, drv.SCAN_DEFAULT_OPTS)
                           for name, members in SCAN_LISTS])
    for number, name, freq, mode, duplex, offset, power, tones in CHANNELS:
        mem = chirp_common.Memory(number)
        mem.name, mem.freq, mem.mode = name, freq, mode
        mem.duplex, mem.offset = duplex, offset
        mem.power = drv.POWER_LEVELS[power]
        for key, value in tones.items():
            setattr(mem, key, value)
        radio.set_memory(mem)
        if number in DMR_EXTRA:
            mem = radio.get_memory(number)
            for setting in mem.extra:
                if setting.get_name() in DMR_EXTRA[number]:
                    setting.value = DMR_EXTRA[number][setting.get_name()]
            radio.set_memory(mem)
    hdr = radio._memobj.zone_hdr
    hdr.count = len(ZONES)
    hdr.a_zone = hdr.a_pos = hdr.b_zone = hdr.b_pos = 1
    for z, (name, members) in enumerate(ZONES, 1):
        radio._zone(z).name = name.ljust(16, '\x00')
        radio._set_zone_members(z, members)
    # Every slot that now holds data needs its page tag, as on a radio.
    for i, tag in enumerate(drv.IMAGE_TAGS):
        slot = i * PAGE
        if mmap.get(slot, PAGE - 1) != b'\xff' * (PAGE - 1):
            mmap.set(slot + PAGE - 1, bytes([tag]))
    return radio


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    radio = build()
    radio.save_mmap(sys.argv[1])
    print('%s: %d channels, %d zones' % (
        sys.argv[1], radio._count(), radio._zone_count()))


if __name__ == '__main__':
    main()
