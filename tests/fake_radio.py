"""Run dm32uv_read.py against a simulated radio that follows PROTOCOL.md."""
import os, struct, sys, runpy, tempfile
import serial

CP_START, CP_END = 0x100000, 0x100000 + 0x60 * 0x1000 - 1
flash = bytearray(b'\xff' * 0x400000)
tags = [0x02, 0x03, 0x0B] + list(range(0x12, 0x42)) + [0x5C]
for i, t in enumerate(tags):
    base = CP_START + (i + i // 3) * 0x1000       # spread pages out, leave gaps
    flash[base:base + 0xFFF] = bytes([t]) * 0xFFF
    flash[base + 0xFFF] = t

class Fake:
    def __init__(self, *a, **k): self.out = b''; self.timeout = 0.5; self.dtr = self.rts = True
    def reset_input_buffer(self): pass
    def close(self): pass
    def read(self, n): d, self.out = self.out[:n], self.out[n:]; return d
    def write(self, d):
        r = b''
        if d == b'PSEARCH': r = b'\x06DM32UV\x00'[:8]
        elif d == b'PASSSTA': r = b'P\x00\x00'
        elif d == b'SYSINFO': r = b'\x06'
        elif d[:1] == b'V':
            i = d[4]
            body = {10: struct.pack('<II', CP_START, CP_END),
                    15: struct.pack('<II', 0x300000, 0x3FFFFF),
                    1: b'DM-32UV'}.get(i, b'\x01\x02')
            r = b'V' + bytes([i, len(body)]) + body
        elif d[:1] == b'G': r = b'S' + d[1:6] + bytes(256)
        elif d == b'PROGRAM': r = b'\x06'
        elif d == b'\x02': r = b'IDENT123'
        elif d == b'\x06': r = b'\x06'
        elif d[:1] == b'R':
            a = int.from_bytes(d[1:4], 'little'); n = int.from_bytes(d[4:6], 'little')
            r = b'W' + d[1:6] + bytes(flash[a:a + n])
        self.out += r
        return len(d)

serial.Serial = Fake
OUT = sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp()
sys.argv = ['dm32uv_read.py', 'FAKE', '-o', OUT, '--contacts']
runpy.run_path(os.path.join(os.path.dirname(__file__), '..', 'tools', 'dm32uv_read.py'), run_name='__main__')

pages = os.listdir(os.path.join(OUT, 'pages'))
assert len(pages) == len(tags), (len(pages), len(tags))
print('OK: read %d pages from the simulated radio' % len(pages))
