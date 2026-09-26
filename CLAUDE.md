# Project context for Claude

This file tells Claude where the project stands and what has been decided.
The technical protocol details are in `docs/PROTOCOL.md`; read it before
changing any protocol code.

## Goal

Programming support for the Baofeng DM-32UV DMR radio in CHIRP (kk7ds/chirp).
As of 2026-09 CHIRP had no DM-32UV support.

## Decisions made

- **Ship a standalone CHIRP driver module, not a fork.** CHIRP's developer mode
  (Help → Developer Mode) enables File → Load Module… and "Load module from
  issue", which load a single driver `.py` into stock CHIRP. We develop
  `baofeng_dm32uv.py` that way, then submit the same file upstream when it's solid.
  A fork was rejected because of the maintenance burden and low discoverability.
- **Build on CHIRP's `chirp/drivers/baofeng_uv17.py` / `baofeng_uv17Pro.py`.** They use
  the same `PSEARCH`/`PASSSTA`/`SYSINFO` handshake and the `FF FF FF FF 0C` magic.
  Differences: the DM-32UV sends no XOR cipher over the link (the CHIRP
  `tblEncrySymbol` keys aren't in the CPS), and it uses 4 KB `R`/`W` blocks
  with a tagged-page layout.
- **DMR scope:** CHIRP has no real DMR data model. Plan: analog channels in full;
  DMR channels with basics in the normal columns plus color code, timeslot and
  contact as per-memory extra settings; radio ID and basic settings on the
  Settings tab. Contacts, RX groups and zones are probably left out of the first version.
- **Never write the factory calibration area** or send `AT+...` commands.
- **Repo hygiene:** never commit the vendor CPS binary, the Ghidra project, or
  decompiled `.c` output (vendor copyright). Never commit radio dumps (radio ID
  and contacts are personal data). `.gitignore` enforces this. Licence: GPL-3.0.

## CHIRP upstream PR requirements (for later)

Test image in `tests/images/`, tests passing (`tox`), `MemoryMapBytes`, GPLv3,
commits rebased onto master with no merge commits, first line like
`dm32uv: Add Baofeng DM-32UV driver`, and a chirpmyradio.com issue referenced
as `Fixes #NNNN`.

## Status (2026-09-26)

- Done: static analysis of CPS v1.60 → `docs/PROTOCOL.md`. Read-only tool
  `tools/dm32uv_read.py`, which passes `tests/fake_radio.py`.
- Development is on a Debian laptop: CH340 cable on `/dev/ttyUSB0` with the
  `ch341` driver, user in `dialout`, Python venv in `.venv` (pyserial, tox).
  The macOS CH340 driver rejected every `tcsetattr`, so macOS is not usable.
- **First contact with the radio worked** (`--probe`, identify only). The
  handshake and V queries match PROTOCOL.md. The radio reports model `DP570UV`,
  firmware `DM32.01.01.047`. V ranges are 24-bit addresses with a flag in
  the top byte (codeplug `0x001000–0x0c8fff`); the tool now masks them.

## Next steps

1. Full read: `.venv/bin/python tools/dm32uv_read.py /dev/ttyUSB0 -o dump1`.
   This is the first time `G`, `PROGRAM`, `02` and the page scan run on the
   real radio. Check `traffic.log` and update PROTOCOL.md. The radio may need
   a power cycle afterwards, because no end-of-session command is known.
2. Optional cross-check: run the vendor CPS under Wine (COM port → /dev/ttyUSB0)
   and capture its traffic with `usbmon` + Wireshark.
3. Map the page tags by changing one setting at a time in the CPS (under Wine),
   reading with the tool, and diffing the pages.
4. Write the CHIRP driver module: download, upload (write back to the same
   pages, keeping the tag byte), then the channel memory map.

## Analysis notes

Key CPS functions: `0x44a210` is the codeplug read/write worker (found via the
Program → Read/Write menu IDs 32778/32779 → message map → dialog). Serial
helpers: `0x48f570` send(buf, len, delay_ms, bytewise), `0x48f630`
recv(buf, len, timeout_ms), `0x48f400` open. Ghidra's auto-analysis misses
much of the code; `re/MakeFuncs.java` creates functions at given entry points.
The stack probe at `0x4b7320` needs the `alloca_probe` call fixup, which
`Decomp.java` applies, or the decompiled output is garbage.
