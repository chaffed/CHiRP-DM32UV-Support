#!/bin/sh
# Disassemble the DM-32UV firmware (C-SKY CK80x) with GNU binutils.
#
# usage: fw_disasm.sh FIRMWARE.bin OUTDIR
#
# Needs csky-elf binutils (Debian's binutils-multiarch has no C-SKY):
#   ../binutils-2.44/configure --target=csky-elf --prefix=$HOME/opt/csky \
#       --disable-nls --disable-werror --disable-gdb --disable-sim && make && make install
# objdump aborts on raw binaries for C-SKY, so the code is wrapped in an ELF
# first, with the ELF flags set to ABI v2 / CK803 so 32-bit instructions decode.
#
# Output (vendor-derived, never commit): OUTDIR/fw.s (application at
# 0x300c000) and OUTDIR/ram.s (the code copied to RAM at 0x10000 at start-up,
# which includes the SPI flash routines).
set -e
BIN=${CSKY_BIN:-$HOME/opt/csky/bin}
FW=$1; OUT=$2
mkdir -p "$OUT"
dd if="$FW" of="$OUT/body.bin" bs=256 skip=1 status=none   # 256-byte BFUV32-V2 header
python3 - "$OUT" <<'EOF'
import sys
out = sys.argv[1]
body = open(out + '/body.bin', 'rb').read()
src = 0x30bd768 - 0x300c000          # start-up copies this to RAM 0x10000..0x2f098
open(out + '/ram.bin', 'wb').write(body[src:src + 0x2f098 - 0x10000])
EOF
for part in body ram; do
    "$BIN/csky-elf-objcopy" -I binary -O elf32-csky-little -B csky \
        --rename-section .data=.text,alloc,load,readonly,code,contents \
        "$OUT/$part.bin" "$OUT/$part.elf"
    python3 - "$OUT/$part.elf" <<'EOF'
import struct, sys
d = bytearray(open(sys.argv[1], 'rb').read())
struct.pack_into('<I', d, 0x24, (2 << 28) | 0x9)     # EF: ABI v2, CK803
open(sys.argv[1], 'wb').write(d)
EOF
done
"$BIN/csky-elf-objdump" -d --adjust-vma=0x300c000 "$OUT/body.elf" > "$OUT/fw.s"
"$BIN/csky-elf-objdump" -d --adjust-vma=0x10000 "$OUT/ram.elf" > "$OUT/ram.s"
echo "wrote $OUT/fw.s and $OUT/ram.s"
