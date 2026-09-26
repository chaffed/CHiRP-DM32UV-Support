"""Print the argument pushes before each serial send/recv call in a function range."""
import sys, pefile, capstone
pe = pefile.PE('DMR_CPS.exe')
base = pe.OPTIONAL_HEADER.ImageBase
text = next(s for s in pe.sections if s.Name.startswith(b'.text'))
code = text.get_data(); va0 = base + text.VirtualAddress
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
NAMES = {0x48f570: 'SEND', 0x48f630: 'RECV', 0x48f400: 'OPEN'}
start, end = int(sys.argv[1], 16), int(sys.argv[2], 16)
insns = list(md.disasm(code[start - va0:end - va0], start))
for i, ins in enumerate(insns):
    if ins.mnemonic == 'call' and ins.op_str.startswith('0x') and int(ins.op_str, 16) in NAMES:
        pushes = [p for p in insns[max(0, i - 12):i] if p.mnemonic in ('push', 'lea', 'mov') ]
        args = [p.op_str for p in insns[max(0, i - 12):i] if p.mnemonic == 'push']
        print(f"{ins.address:#x} {NAMES[int(ins.op_str,16)]:4} pushes(last=arg1): {args[-5:]}")
