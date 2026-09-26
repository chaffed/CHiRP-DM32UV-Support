# Copyright 2026 The CHIRP DM-32UV driver authors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Baofeng DM-32UV (DMR) driver.

Download and upload work. Upload writes only the channel pages, and only
those that differ from the radio, and reads every written page back. The
protocol and memory layout are described in docs/PROTOCOL.md of the
CHiRP-DM32UV-Support project.

The radio keeps its codeplug in 4 KB flash pages whose last byte is a tag
naming the contents; pages move around as the radio rewrites them. The
image this driver stores is logical: one 4 KB slot per tag in IMAGE_TAGS,
in that order, each holding the page as read (tag byte included), or all
0xFF if the radio has no page with that tag.

The serial link on the tested cable flips bit 7 of about 1 received byte
in 1000 and the protocol has no checksums, so every block is read at
least three times and the copies are merged byte by byte.
"""

import collections
import logging
import struct
import time

from chirp import bitwise, chirp_common, directory, errors, memmap
from chirp.settings import (RadioSetting, RadioSettingGroup,
                            RadioSettingValueBoolean,
                            RadioSettingValueInteger, RadioSettingValueList)

LOG = logging.getLogger(__name__)

PAGE = 0x1000
# The tags the vendor CPS reads (0x12-0x41 are the channel pages).
IMAGE_TAGS = ([0x02, 0x03, 0x04, 0x06, 0x0A, 0x0B, 0x0F, 0x10, 0x11] +
              list(range(0x12, 0x49)) + list(range(0x5C, 0x68)))
CH_TAG0 = 0x12
CH_BASE = IMAGE_TAGS.index(CH_TAG0) * PAGE
CH_SIZE, CH_PER_PAGE, CH_COUNT = 0x30, 85, 4000
VFO_OFFSETS = (0xF9F, 0xFCF)            # in the last channel page

# Received bytes sometimes have this bit set when the radio sent it clear.
LINK_FAULT = 0x80
READ_COPIES, READ_TRIES = 3, 10

# Upload writes channel pages only, one whole aligned page per W frame: the
# firmware erases the sector on an aligned W and also erases the next sector
# if a W crosses into it. Tags 0x02 and 0x69 look like calibration.
UPLOAD_ENABLED = True
UPLOAD_TAGS = list(range(0x12, 0x42))
NEVER_WRITE = (0x02, 0x69)
WRITE_TRIES = 3

CHAN_FORMAT = """
struct chan {
  char name[16];
  lbcd rxfreq[4];
  lbcd txfreq[4];
  u8 chtype:4, forbid_tx:1, power:2, lone_work:1;
  u8 wide:1, auto_scan:1, scanlist:6;
  u8 forbid_talkaround:1, tx_admit:3, unknown1a:1, aprs_rx:1, offset_dir:2;
  u8 emerg_indicator:1, emerg_ack:1, unknown1b:1, emerg_system:5;
  u8 squelch:4, aprs_report:2, aprs_ptt_analog:1, aprs_ptt_digital:1;
  u8 private_confirm:1, short_data_confirm:1, tdma_direct:1, timeslot:1,
     colorcode:4;
  u8 unknown1e;
  u8 unknown1f:1, encrypt:1, rxgroup:6;
  u8 unknown20;
  u8 rxtone[2];
  u8 txtone[2];
  u8 unknown25:2, compander:1, vox:1, unknown25b:4;
  u8 ptt_id_display:1, rx_squelch_mode:3, signaling:3, unknown26:1;
  u8 unknown27;
  u8 unknown28;
  u8 step:4, ptt_id:2, unknown29:2;
  u8 unknown2a;
  u8 unknown2b;
  lbcd offset[4];
};
"""


def _mem_format():
    """Channel pages as the CPS lays them out (see channel_offset)."""
    fmt = [CHAN_FORMAT,
           '#seekto 0x%x;\nul16 ch_count;' % CH_BASE,
           '#seekto 0x%x;\nstruct chan page0[84];' % (CH_BASE + 0x10)]
    for p in range(1, 48):
        n = CH_PER_PAGE if p < 47 else CH_COUNT - 47 * CH_PER_PAGE + 1
        fmt.append('#seekto 0x%x;\nstruct chan page%d[%d];' % (
            CH_BASE + p * PAGE, p, n))
    # VFO A and B are back to back (VFO_OFFSETS).
    fmt.append('#seekto 0x%x;\nstruct chan vfo0;\nstruct chan vfo1;' % (
        CH_BASE + 47 * PAGE + VFO_OFFSETS[0]))
    return '\n'.join(fmt)


MEM_FORMAT = _mem_format()


def channel_offset(n):
    """(page, index) of channel n, as the CPS computes it (0x47dcc0)."""
    if n < CH_PER_PAGE:
        return 0, n - 1
    return n // CH_PER_PAGE, n % CH_PER_PAGE


CHTYPES = ['Analog', 'Digital', 'Fixed Analog', 'Fixed Digital']
POWER_LEVELS = [chirp_common.PowerLevel('Low', watts=1),
                chirp_common.PowerLevel('Middle', watts=2.5),
                chirp_common.PowerLevel('High', watts=5)]
STEPS = [2.5, 5.0, 6.25, 10.0, 12.5, 25.0, 50.0, 100.0]


# --- Serial link ------------------------------------------------------------

def _marker_ok(got, want):
    """Check a one-byte reply marker, allowing for the known link fault."""
    return got in (want, want | LINK_FAULT)


def _merge_copies(copies):
    """Merge copies of one block byte by byte, or None if more are needed.

    Where copies differ only in bit 7, the value with bit 7 clear wins, as
    the link fault only ever sets it. Anything else needs a strict majority
    of at least 3 copies.
    """
    first = copies[0]
    if all(c == first for c in copies[1:]):
        return first
    out = bytearray(first)
    for i, vals in enumerate(zip(*copies)):
        if min(vals) == max(vals):
            continue
        votes = collections.Counter(vals)
        if len({v & ~LINK_FAULT for v in votes}) == 1:
            out[i] = min(votes)
            continue
        value, n = votes.most_common(1)[0]
        if n < 3 or n * 2 <= len(copies):
            return None
        out[i] = value
    return bytes(out)


class _Link:
    def __init__(self, pipe):
        self.pipe = pipe

    def send(self, data):
        time.sleep(0.01)
        self.pipe.reset_input_buffer()
        self.pipe.write(data)

    def recv(self, n, timeout=0.5):
        self.pipe.timeout = timeout
        return self.pipe.read(n)

    def drain(self):
        time.sleep(0.1)
        self.pipe.reset_input_buffer()

    def xfer(self, data, n, timeout=0.5):
        self.send(data)
        resp = self.recv(n, timeout)
        if len(resp) != n:
            raise errors.RadioError('No reply from radio to %r' % data[:7])
        return resp

    def query_v(self, cmd, agree=3, tries=10):
        """Repeat a V query until `agree` identical replies have been seen."""
        seen = collections.Counter()
        for _attempt in range(tries):
            self.send(cmd)
            hdr = self.recv(3)
            n = hdr[2] if len(hdr) == 3 else 0
            body = self.recv(n) if n else b''
            if len(hdr) != 3 or len(body) != n or not _marker_ok(hdr[0], 0x56):
                self.drain()
                continue
            seen[hdr + body] += 1
            reply, count = seen.most_common(1)[0]
            if count >= agree:
                return reply[3:]
        raise errors.RadioError('Unreliable reply to radio info query')

    def read_block(self, addr, length, timeout=5.0):
        cmd = b'R' + struct.pack('<I', addr)[:3] + struct.pack('<H', length)
        good = []
        for _attempt in range(READ_TRIES):
            self.send(cmd)
            resp = self.recv(6 + length, timeout)
            if len(resp) != 6 + length or resp[:6] != b'W' + cmd[1:6]:
                self.drain()
                continue
            good.append(resp[6:])
            if len(good) >= READ_COPIES:
                merged = _merge_copies(good)
                if merged is not None:
                    return merged
        raise errors.RadioError('Could not read flash at %06x reliably' % addr)


def _identify(link):
    for _attempt in range(5):
        link.send(b'PSEARCH')
        resp = link.recv(8)
        if len(resp) == 8 and _marker_ok(resp[0], 0x06):
            break
    else:
        raise errors.RadioError('Radio did not respond. Is it switched on '
                                'and connected?')
    resp = link.xfer(b'PASSSTA', 3)
    if not _marker_ok(resp[0], ord('P')):
        raise errors.RadioError('Unexpected reply to PASSSTA')
    if resp[2] == 0xA5:
        raise errors.RadioError('The radio has a read password set; this '
                                'driver does not support that yet')
    if not _marker_ok(link.xfer(b'SYSINFO', 1)[0], 0x06):
        raise errors.RadioError('Radio refused SYSINFO')
    link.query_v(b'V\x00\x00\x40\x0D')
    info = {}
    for i in range(1, 17):
        if i != 12:
            info[i] = link.query_v(b'V\x00\x00\x00' + bytes([i]))
    start, end = struct.unpack('<II', info[10][:8])
    if (start | end) >> 24 or start >= end:
        raise errors.RadioError('Unexpected codeplug range from radio')
    return info[1].decode('ascii', 'replace'), start, end


def _enter_program(link):
    if not _marker_ok(link.xfer(b'G\x00\x00\x00\x00\x01', 0x106)[0],
                      ord('S')):
        raise errors.RadioError('Unexpected reply to G')
    link.send(b'\xFF\xFF\xFF\xFF\x0C')
    if not _marker_ok(link.xfer(b'PROGRAM', 1)[0], 0x06):
        raise errors.RadioError('Radio refused programming mode')
    link.xfer(b'\x02', 8)
    if not _marker_ok(link.xfer(b'\x06', 1)[0], 0x06):
        raise errors.RadioError('Radio did not acknowledge')


def _scan(link, start, end, radio, status):
    """Tag of every page: ({tag: [addresses]}, [free page addresses])."""
    pages = list(range(start, end + 1 - PAGE + 1, PAGE))
    where = collections.defaultdict(list)
    for i, addr in enumerate(pages):
        where[link.read_block(addr + PAGE - 1, 1, timeout=0.5)[0]].append(addr)
        status.cur = i
        radio.status_fn(status)
    return where, where.pop(0xFF, [])


def do_download(radio):
    link = _Link(radio.pipe)
    firmware, start, end = _identify(link)
    LOG.info('DM-32UV firmware %s, codeplug %06x-%06x', firmware, start, end)
    _enter_program(link)

    status = chirp_common.Status()
    status.msg = 'Scanning flash pages'
    status.max = (end + 1 - start) // PAGE + len(IMAGE_TAGS)
    where, _free = _scan(link, start, end, radio, status)

    status.msg = 'Cloning from radio'
    base = status.cur + 1
    image = bytearray(b'\xFF' * (len(IMAGE_TAGS) * PAGE))
    for i, tag in enumerate(IMAGE_TAGS):
        if where.get(tag):
            data = link.read_block(where[tag][0], PAGE)
            image[i * PAGE:(i + 1) * PAGE] = data
        status.cur = base + i
        radio.status_fn(status)
    radio._metadata['dm32uv_firmware'] = firmware
    return memmap.MemoryMapBytes(bytes(image))


def _write_page(link, addr, data, start, end):
    """Write one whole page with W and read it back until it matches."""
    if (len(data) != PAGE or addr % PAGE or addr < start or
            addr + PAGE - 1 > end or data[-1] in NEVER_WRITE):
        raise errors.RadioError('Refusing unsafe write at %06x' % addr)
    frame = (b'W' + struct.pack('<I', addr)[:3] + struct.pack('<H', PAGE) +
             bytes(data))
    for _attempt in range(WRITE_TRIES):
        link.send(frame)
        ack = link.recv(1, timeout=5.0)
        if not ack:
            # The radio may still be waiting for data; after 2 s it gives
            # up and ends the session, which the read-back below reports.
            time.sleep(2.5)
        elif not _marker_ok(ack[0], 0x06):
            LOG.warning('Unexpected reply %s to W %06x', ack.hex(), addr)
        if link.read_block(addr, PAGE) == bytes(data):
            return
        LOG.warning('Page %06x did not verify, writing it again', addr)
    raise errors.RadioError('Page at %06x did not verify after %d writes' % (
        addr, WRITE_TRIES))


def do_upload(radio):
    """Write changed channel pages back to the radio, verifying each one.

    A page is written to wherever the radio keeps that tag now, or to the
    first free page if the radio has none yet. Pages that already match the
    image are left alone, so an unchanged image writes nothing. Returns the
    number of pages written.
    """
    image = radio.get_mmap().get_packed()
    link = _Link(radio.pipe)
    firmware, start, end = _identify(link)
    LOG.info('Upload to DM-32UV firmware %s', firmware)
    _enter_program(link)

    status = chirp_common.Status()
    status.msg = 'Scanning flash pages'
    status.max = (end + 1 - start) // PAGE + len(UPLOAD_TAGS)
    where, free = _scan(link, start, end, radio, status)
    dupes = [t for t in UPLOAD_TAGS if len(where.get(t, [])) > 1]
    if dupes:
        raise errors.RadioError(
            'The radio has more than one page with tag %s; not writing' %
            ', '.join('%02x' % t for t in dupes))

    status.msg = 'Cloning to radio'
    base = status.cur + 1
    written = 0
    for i, tag in enumerate(UPLOAD_TAGS):
        slot = IMAGE_TAGS.index(tag) * PAGE
        want = image[slot:slot + PAGE - 1] + bytes([tag])
        if image[slot:slot + PAGE - 1] != b'\xFF' * (PAGE - 1):
            if where.get(tag):
                addr = where[tag][0]
                if link.read_block(addr, PAGE) == want:
                    addr = None
            elif free:
                addr = free.pop(0)
            else:
                raise errors.RadioError('No free page left on the radio')
            if addr is not None:
                _write_page(link, addr, want, start, end)
                written += 1
        status.cur = base + i
        radio.status_fn(status)
    return written


# --- Tones ------------------------------------------------------------------

def _decode_tone(raw):
    """Two tone bytes -> (mode, value, polarity) for split_tone_decode."""
    lo, hi = int(raw[0]), int(raw[1])
    try:
        if hi & 0x80:
            code = int('%x%02x' % (hi & 0x07, lo))
            if code in chirp_common.DTCS_CODES:
                return 'DTCS', code, 'R' if hi & 0x40 else 'N'
        else:
            tone = int('%02x%02x' % (hi, lo)) / 10.0
            if tone in chirp_common.TONES:
                return 'Tone', tone, None
    except ValueError:
        pass
    if (lo, hi) != (0xFF, 0xFF):
        LOG.warning('Unknown tone bytes %02x %02x', lo, hi)
    return '', None, None


def _encode_tone(raw, mode, value, pol):
    if mode == 'Tone':
        digits = '%04d' % round(value * 10)
        raw[0], raw[1] = int(digits[2:], 16), int(digits[:2], 16)
    elif mode == 'DTCS':
        digits = '%03d' % value
        raw[1] = (0xC0 if pol == 'R' else 0x80) | int(digits[0])
        raw[0] = int(digits[1:], 16)
    else:
        raw[0] = raw[1] = 0xFF


@directory.register
class DM32UV(chirp_common.CloneModeRadio):
    """Baofeng DM-32UV"""
    VENDOR = 'Baofeng'
    MODEL = 'DM-32UV'
    BAUD_RATE = 115200
    _memsize = len(IMAGE_TAGS) * PAGE

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = (
            'This driver is experimental. Upload changes only the channel '
            'memories; other settings, contacts and zones are left as they '
            'are on the radio.')
        rp.pre_download = (
            'Switch the radio on and connect the programming cable.\n\n'
            'The radio returns to normal by itself a few seconds after '
            'the download.')
        rp.pre_upload = (
            'Before the first upload, download from the radio and save the '
            'image as a backup.\n\n'
            'Upload writes only channel pages that differ from the radio '
            'and checks each one by reading it back. It takes about a '
            'minute plus a few seconds per changed page.')
        return rp

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.memory_bounds = (1, CH_COUNT)
        rf.has_bank = False
        rf.has_ctone = True
        rf.has_cross = True
        rf.has_rx_dtcs = True
        rf.has_dtcs_polarity = True
        rf.has_settings = False
        rf.can_odd_split = True
        rf.valid_modes = ['FM', 'NFM', 'DMR']
        rf.valid_tmodes = ['', 'Tone', 'TSQL', 'DTCS', 'Cross']
        rf.valid_cross_modes = ['Tone->Tone', 'DTCS->', '->DTCS', 'Tone->DTCS',
                                'DTCS->Tone', '->Tone', 'DTCS->DTCS']
        rf.valid_duplexes = ['', '-', '+', 'split', 'off']
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_bands = [(136000000, 174000000), (400000000, 480000000)]
        rf.valid_tuning_steps = STEPS
        # Frequencies are stored to 10 Hz, independent of the step.
        rf.has_nostep_tuning = True
        rf.valid_skips = []
        rf.valid_name_length = 16
        rf.valid_characters = chirp_common.CHARSET_ASCII
        return rf

    def sync_in(self):
        try:
            self._mmap = do_download(self)
        except errors.RadioError:
            raise
        except Exception as e:
            LOG.exception('Download failed')
            raise errors.RadioError('Failed to download from radio: %s' % e)
        self.process_mmap()

    def sync_out(self):
        if not UPLOAD_ENABLED:
            raise errors.RadioError('Uploading to the DM-32UV is not '
                                    'supported yet by this driver')
        try:
            do_upload(self)
        except errors.RadioError:
            raise
        except Exception as e:
            LOG.exception('Upload failed')
            raise errors.RadioError('Failed to upload to radio: %s' % e)

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def _chan(self, number):
        page, index = channel_offset(number)
        return getattr(self._memobj, 'page%d' % page)[index]

    def _count(self):
        count = int(self._memobj.ch_count)
        return 0 if count > CH_COUNT else count

    def get_raw_memory(self, number):
        return repr(self._chan(number))

    def get_memory(self, number):
        _mem = self._chan(number)
        mem = chirp_common.Memory()
        mem.number = number
        rx = _mem.rxfreq.get_raw()
        if number > self._count() or rx in (b'\xFF' * 4, b'\x00' * 4):
            mem.empty = True
            return mem

        mem.freq = int(_mem.rxfreq) * 10
        if _mem.txfreq.get_raw() == b'\xFF' * 4:
            mem.duplex = 'off'
        else:
            chirp_common.split_to_offset(mem, mem.freq,
                                         int(_mem.txfreq) * 10)
        mem.name = str(_mem.name).rstrip('\x00\xFF ')
        digital = _mem.chtype in (1, 3)
        mem.mode = 'DMR' if digital else ('FM' if _mem.wide else 'NFM')
        mem.power = POWER_LEVELS[min(int(_mem.power), 2)]
        if _mem.step < len(STEPS):
            mem.tuning_step = STEPS[_mem.step]
        if not digital:
            chirp_common.split_tone_decode(
                mem, _decode_tone(_mem.txtone), _decode_tone(_mem.rxtone))

        mem.extra = self._get_extra(_mem)
        return mem

    def _get_extra(self, _mem):
        extra = RadioSettingGroup('extra', 'Extra')
        extra.append(RadioSetting(
            'chtype', 'Channel type',
            RadioSettingValueList(CHTYPES, current_index=min(
                int(_mem.chtype), len(CHTYPES) - 1))))
        extra.append(RadioSetting(
            'colorcode', 'Color code (DMR)',
            RadioSettingValueInteger(0, 15, int(_mem.colorcode))))
        extra.append(RadioSetting(
            'timeslot', 'Time slot (DMR)',
            RadioSettingValueList(['1', '2'],
                                  current_index=int(_mem.timeslot))))
        extra.append(RadioSetting(
            'squelch', 'Squelch level',
            RadioSettingValueInteger(0, 9, min(int(_mem.squelch), 9))))
        extra.append(RadioSetting(
            'forbid_tx', 'Forbid TX',
            RadioSettingValueBoolean(bool(_mem.forbid_tx))))
        extra.append(RadioSetting(
            'forbid_talkaround', 'Forbid talkaround',
            RadioSettingValueBoolean(bool(_mem.forbid_talkaround))))
        return extra

    def set_memory(self, mem):
        _mem = self._chan(mem.number)
        if mem.empty:
            _mem.set_raw(b'\xFF' * CH_SIZE)
            if mem.number == self._count():
                count = mem.number - 1
                while count and self.get_memory(count).empty:
                    count -= 1
                self._memobj.ch_count = count
            return

        if _mem.get_raw() in (b'\xFF' * CH_SIZE, b'\x00' * CH_SIZE):
            # Defaults as on the channels the radio came with.
            _mem.set_raw(b'\xFF' * 16 + b'\x00' * 8 + bytes.fromhex(
                '0000000030000000' '00ffffffff000000' '0000000000000000'))
        if mem.number > self._count():
            self._memobj.ch_count = mem.number

        _mem.name = mem.name.ljust(16, '\x00')[:16]
        _mem.rxfreq = mem.freq // 10
        if mem.duplex == 'off':
            _mem.txfreq.fill_raw(b'\xFF')
        elif mem.duplex == 'split':
            _mem.txfreq = mem.offset // 10
        elif mem.duplex == '+':
            _mem.txfreq = (mem.freq + mem.offset) // 10
        elif mem.duplex == '-':
            _mem.txfreq = (mem.freq - mem.offset) // 10
        else:
            _mem.txfreq = mem.freq // 10

        digital = mem.mode == 'DMR'
        if digital and _mem.chtype not in (1, 3):
            _mem.chtype = 1
        elif not digital and _mem.chtype not in (0, 2):
            _mem.chtype = 0
        _mem.wide = mem.mode == 'FM'
        _mem.power = POWER_LEVELS.index(mem.power) if mem.power else 2
        if mem.tuning_step in STEPS:
            _mem.step = STEPS.index(mem.tuning_step)

        txtone, rxtone = chirp_common.split_tone_encode(mem)
        _encode_tone(_mem.txtone, *txtone)
        _encode_tone(_mem.rxtone, *rxtone)

        for setting in mem.extra:
            name = setting.get_name()
            if name == 'chtype':
                # Keep the analog/digital choice consistent with the mode.
                value = CHTYPES.index(str(setting.value))
                if (value in (1, 3)) == digital:
                    _mem.chtype = value
            elif name == 'timeslot':
                _mem.timeslot = int(str(setting.value)) - 1
            else:
                setattr(_mem, name, int(setting.value))
