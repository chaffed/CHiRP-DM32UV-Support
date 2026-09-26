"""Run dm32uv_read.py against a simulated radio that follows PROTOCOL.md.

The tool runs twice: over a clean link, then over a noisy one that mimics
the real cable (bit 7 of received bytes set about 1 time in 500, plus rarer
faults the real link hasn't shown yet). Both runs must give exactly the
simulated flash contents.
"""
import json, os, random, struct, sys, runpy, tempfile, time
import serial

CP_START, CP_END = 0x001000, 0x0C8FFF              # values seen on a real radio
CT_START, CT_END = 0x278000, 0x6DBFFF
rng = random.Random(1)
flash = bytearray(b'\xff' * 0x1000000)
tags = [0x02, 0x03, 0x0B] + list(range(0x12, 0x42)) + [0x5C]
pages = {}
for i, t in enumerate(tags):
    base = CP_START + (i + i // 3) * 0x1000       # spread pages out, leave gaps
    flash[base:base + 0xFFF] = rng.randbytes(0xFFF)
    flash[base + 0xFFF] = t
    pages[t] = base
for a in (0x0C1000, 0x0C7000):                     # stale pages, as on the real radio
    flash[a:a + 0xFFF] = rng.randbytes(0xFFF)
    flash[a + 0xFFF] = 0x00
    pages[0x00, a] = a

CLEAN = dict(bit7=0, other=0, drop=0)
NOISY = dict(bit7=0.002,    # the fault seen on the real link
             other=0.0002,  # a different bit flipped: not seen yet, must still be caught
             drop=0.01)     # R/V reply cut short
noise = CLEAN

class Fake:
    def __init__(self, *a, **k): self.out = b''; self.timeout = 0.5; self.dtr = self.rts = True
    def reset_input_buffer(self): self.out = b''
    def close(self): pass
    def read(self, n): d, self.out = self.out[:n], self.out[n:]; return d
    def write(self, d):
        r = b''
        if d == b'PSEARCH': r = b'\x06DP570UV'
        elif d == b'PASSSTA': r = b'P\x00\x00'
        elif d == b'SYSINFO': r = b'\x06'
        elif d[:1] == b'V':
            i = d[4]
            body = {10: struct.pack('<II', CP_START, CP_END),
                    15: struct.pack('<II', CT_START, CT_END),
                    1: b'DM32.01.01.047'}.get(i, b'\x01\x02')
            r = b'V' + bytes([i, len(body)]) + body
        elif d[:1] == b'G': r = b'S' + d[1:6] + bytes(256)
        elif d == b'PROGRAM': r = b'\x06'
        elif d == b'\x02': r = b'IDENT123'
        elif d == b'\x06': r = b'\x06'
        elif d[:1] == b'R':
            a = int.from_bytes(d[1:4], 'little'); n = int.from_bytes(d[4:6], 'little')
            r = b'W' + d[1:6] + bytes(flash[a:a + n])
        if d[:1] in (b'R', b'V') and r and rng.random() < noise['drop']:
            r = r[:rng.randrange(len(r))]
        r = bytearray(r)
        for j, b in enumerate(r):
            if not b & 0x80 and rng.random() < noise['bit7']:
                r[j] = b | 0x80
            elif rng.random() < noise['other']:
                r[j] = b ^ (1 << rng.randrange(7))
        self.out += bytes(r)
        return len(d)

serial.Serial = Fake
time.sleep = lambda s: None
TOOL = os.path.join(os.path.dirname(__file__), '..', 'tools', 'dm32uv_read.py')
TOP = sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp()

for name, noise in (('clean', CLEAN), ('noisy', NOISY)):
    out = os.path.join(TOP, name)
    print('==== %s link' % name)
    sys.argv = ['dm32uv_read.py', 'FAKE', '-o', out, '--contacts']
    runpy.run_path(TOOL, run_name='__main__')

    info = json.load(open(os.path.join(out, 'info.json')))
    assert 'error' not in info, info['error']
    assert (info['cp_start'], info['cp_end']) == (CP_START, CP_END), info
    files = sorted(os.listdir(os.path.join(out, 'pages')))
    names = {'tag%02x_%06x.bin' % (flash[a + 0xFFF], a): a for a in pages.values()}
    assert files == sorted(names), files
    for fname, a in names.items():
        got = open(os.path.join(out, 'pages', fname), 'rb').read()
        assert got == flash[a:a + 0x1000], '%s differs from flash' % fname
    stats = info['link_stats']
    if noise is NOISY:
        assert stats.get('bit-7 errors corrected') and stats.get('other disagreements'), stats
    print('OK: %s link, %d pages match the simulated flash' % (name, len(files)))
