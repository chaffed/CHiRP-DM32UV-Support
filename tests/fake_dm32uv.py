"""A simulated DM-32UV for testing, modelled on the radio firmware.

Behaviour follows docs/PROTOCOL.md ("Radio firmware"): frames are parsed
from the byte stream; W erases the sector first when the address is 4 KB
aligned and erases the next sector if the data crosses into it; flash
programming can only clear bits; S/G use a separate memory; a session ends
when the host is silent for 2 s: tests route time.sleep to virtual_sleep()
so the driver's waits count, and close() ends it too. PASSSTA reports the
password flags from the settings page (tag 0x04, bytes 0x439/0x43A).

Anything our tools must never do is recorded in `violations`: a W that is
not exactly one aligned 4 KB page inside the codeplug area, a W to a page
tagged 0x02 or 0x69 (or making one), and any S.

Noise only affects replies (radio -> PC), as seen on the real cable.
"""
import random
import struct

CP_START, CP_END = 0x001000, 0x0C8FFF          # values seen on a real radio
CT_START, CT_END = 0x278000, 0x6DBFFF
PAGE = 0x1000
PROTECTED_TAGS = (0x02, 0x69)

SESSION_IDLE = 2.0            # seconds of silence that end a session
_LIVE = []                    # the radio most recently connected


def virtual_sleep(seconds):
    """Stand-in for time.sleep: silence on the line, as the radio sees it."""
    if _LIVE:
        _LIVE[-1].idle(seconds)


CLEAN = dict(bit7=0, other=0, drop=0)
NOISY = dict(bit7=0.002,    # the fault seen on the real link
             other=0.0002,  # a different bit flipped: not seen yet, must still be caught
             drop=0.01)     # R/V reply cut short


class FakeRadio:
    """Stands in for serial.Serial."""

    def __init__(self, flash, noise=CLEAN, seed=1, model=b'DP570UV',
                 firmware=b'DM32.01.01.047'):
        self.flash = flash
        self.model, self.firmware = model, firmware
        self.smem = bytearray(b'\xff' * 0x10000)   # the G/S memory
        self.noise = noise
        self.rng = random.Random(seed)
        self.out = b''
        self.inbuf = b''
        self.state = 'top'
        self.timeout = 0.5
        self.dtr = self.rts = True
        self.log = []            # (cmd, addr, length) of every frame handled
        self.violations = []
        self.corrupt_writes = 0  # corrupt one data byte of the next N writes
        self.drop_acks = 0       # send no ACK for the next N writes
        self.resets = 0
        self.sessions = 0        # sessions ended by silence
        _LIVE[:] = [self]

    # --- serial.Serial interface --------------------------------------------
    def reset_input_buffer(self):
        self.out = b''

    def read(self, n):
        d, self.out = self.out[:n], self.out[n:]
        return d

    def write(self, d):
        self.inbuf += bytes(d)
        self._process()
        return len(d)

    def idle(self, seconds):
        if seconds >= SESSION_IDLE and self.state != 'top':
            self.state = 'top'      # back to the home screen, no reset
            self.inbuf = b''
            self.sessions += 1

    def close(self):
        if self.state != 'top':
            self.state = 'top'      # 2 s idle ends the session, then a reset
            self.resets += 1
        self.inbuf = b''

    # --- replies ------------------------------------------------------------
    def _reply(self, r, noisy_frame):
        rng, noise = self.rng, self.noise
        if noisy_frame and r and rng.random() < noise['drop']:
            r = r[:rng.randrange(len(r))]
        r = bytearray(r)
        for j, b in enumerate(r):
            if not b & 0x80 and rng.random() < noise['bit7']:
                r[j] = b | 0x80
            elif rng.random() < noise['other']:
                r[j] = b ^ (1 << rng.randrange(7))
        self.out += bytes(r)

    def _password_flags(self):
        """Settings bytes 0x439 (write) and 0x43A (read), as the firmware."""
        for a in range(CP_START, CP_END, PAGE):
            if self.flash[a + PAGE - 1] == 0x04:
                return bytes(self.flash[a + 0x439:a + 0x43B])
        return b'\x00\x00'

    def _v(self, i):
        body = {10: struct.pack('<II', CP_START, CP_END),
                15: struct.pack('<II', CT_START, CT_END),
                1: self.firmware}.get(i, b'\x01\x02')
        return b'V' + bytes([i, len(body)]) + body

    # --- frame parser -----------------------------------------------------
    def _process(self):
        while self.inbuf:
            used = self._frame(self.inbuf)
            if used == 0:
                return              # wait for more bytes
            self.inbuf = self.inbuf[used:]

    def _frame(self, b):
        st = self.state
        if st == 'top':
            for cmd, rep in ((b'PSEARCH', b'\x06' + self.model),
                             (b'PASSSTA', b'P' + self._password_flags()),
                             (b'SYSINFO', b'\x06')):
                if b.startswith(cmd):
                    self._reply(rep, False)
                    return 7
            if b.startswith(b'PROGRAM'):
                self._reply(b'\x06', False)
                self.state = 'prog02'
                return 7
            if b.startswith(b'\xff\xff\xff\xff\x0c'):
                return 5
        elif st == 'prog02' and b[:1] == b'\x02':
            self._reply(b'\xff' * 8, False)
            self.state = 'prog06'
            return 1
        elif st == 'prog06' and b[:1] == b'\x06':
            self._reply(b'\x06', False)
            self.state = 'session'
            return 1
        if b[:1] == b'V':
            if len(b) < 5:
                return 0
            self._reply(self._v(b[4]), True)
            return 5
        if b[:1] == b'G' and st == 'top' or (
                b[:1] in (b'R', b'G', b'W', b'S', b'D') and st == 'session'):
            if len(b) < 6:
                return 0
            cmd = b[:1]
            a = int.from_bytes(b[1:4], 'little')
            n = int.from_bytes(b[4:6], 'little')
            if cmd in (b'W', b'S'):
                if len(b) < 6 + n:
                    return 0
                self._write(cmd, a, n, bytearray(b[6:6 + n]))
                return 6 + n
            self.log.append((cmd.decode(), a, n))
            if cmd == b'R':
                self._reply(b'W' + b[1:6] + bytes(self.flash[a:a + n]), True)
            elif cmd == b'G':
                self._reply(b'S' + b[1:6] + bytes(self.smem[a:a + n]), False)
            return 6
        self.log.append(('garbage', b[0], 1))
        return 1                    # unknown byte: skip it, as the radio would

    def _write(self, cmd, a, n, data):
        self.log.append((cmd.decode(), a, n))
        if cmd == b'S':
            self.violations.append('S frame sent (erases the G/S memory)')
            mem = self.smem
        else:
            mem = self.flash
            if n != PAGE or a % PAGE or not (CP_START <= a and a + n - 1 <= CP_END):
                self.violations.append('unsafe W at %06x length %#x' % (a, n))
            old_tag = mem[(a & ~0xFFF) + 0xFFF]
            if old_tag in PROTECTED_TAGS or (n == PAGE and data[-1] in PROTECTED_TAGS):
                self.violations.append('W to protected page %06x' % a)
            if self.corrupt_writes:
                self.corrupt_writes -= 1
                data[self.rng.randrange(n)] ^= 0x10
        if a % PAGE == 0:
            mem[a:a + PAGE] = b'\xff' * PAGE
        for i, byte in enumerate(data):
            p = a + i
            if p % PAGE == 0 and i:
                mem[p:p + PAGE] = b'\xff' * PAGE   # crossed into the next sector
            mem[p] &= byte
        if cmd == b'W' and self.drop_acks:
            self.drop_acks -= 1     # written, but the ACK never arrives
            return
        self._reply(b'\x06', False)


def make_flash(pages, stale=()):
    """Flash with {tag: (addr, 4 KB data)} placed, plus stale tag 0x00 pages."""
    flash = bytearray(b'\xff' * 0x1000000)
    for tag, (addr, data) in pages.items():
        assert len(data) == PAGE and addr % PAGE == 0
        flash[addr:addr + PAGE] = data[:-1] + bytes([tag])
    for addr in stale:
        flash[addr:addr + PAGE - 1] = b'\x00' * (PAGE - 1)
        flash[addr + PAGE - 1] = 0x00
    return flash
