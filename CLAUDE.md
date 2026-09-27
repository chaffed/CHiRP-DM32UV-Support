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

- Protocol, page layout and the full channel record are documented in
  `docs/PROTOCOL.md`: from the CPS (Ghidra, `re/`) plus keypad tests on the radio
  (change one thing, read, `tools/dm32uv_diff.py`).
- Development is on a Debian laptop: CH340 cable on `/dev/ttyUSB0` with the
  `ch341` driver, user in `dialout`, Python venv in `.venv` (pyserial, tox,
  CHIRP installed editable from `../chirp`, a clone of kk7ds/chirp). Ghidra
  12.1.4 in `~/ghidra_12.1.4_PUBLIC`. The extracted CPS installer is in the
  project folder (gitignored); `DMR CPS.exe` is file `16`, the English UI
  text is file `10`.
- **The serial link is unreliable**: about 1 received byte in 1000 has bit 7
  flipped 0→1. The vendor CPS has no error handling either. Every read is
  done 3 times and the copies are merged byte by byte. Writes will need
  read-back verification. Never send anything at a baud rate other than 115200: the radio
  hangs until power-cycled. After a normal session no power cycle is needed: the radio
  ends the session after 2 s idle and returns to its home screen by itself.
- **CHIRP driver works, download and upload** (`driver/baofeng_dm32uv.py`): a real
  download matched the read tool's dump byte for byte; upload writes only changed
  channel pages and verifies each (see PROTOCOL.md "First real edit"). It passes CHIRP's
  driver tests, flake8 and mypy (run from `../chirp` with the driver and an
  image symlinked into `chirp/drivers/` and `tests/images/`), and works in the
  stock CHIRP GUI as a loaded module (download tested there; upload not yet from the GUI).
- Tags 0x02 and 0x69 look like band limits and calibration. Never write them.

## Next steps

1. (Done: tones (CTCSS, DCS) and power uploaded from CHIRP and confirmed on the radio.)
   DMR fields mapped from the CPS and in the driver as extras chosen by name: TX contact
   (+0x2b → tag 0x67), RX group list (+0x1f → tag 0x0F), encryption key (+0x1e → tag
   0x10), time slot, all confirmed with an upload from the GUI. (Done: the driver works in the stock CHIRP GUI via
   Help → Developer Mode, File → Load Module; download and channel names as expected.)
2. Upload works and is enabled in the driver. Proven on the radio: a no-op write of
   page 0x13, then a rename via do_upload, with a full re-read differing from the
   backup (backup-2026-09-26/, all 200 pages) in only the 7 name bytes. Next: try an
   upload from the CHIRP GUI and editing tones on the radio. (Done: a channel appended past
   the count works; it only shows on the radio once it's in a zone.)
   Zones are CHIRP banks, with a spare "New zone" bank for creating the next zone (also
   proven on the radio). Proven on the radio: a channel added to a zone in the GUI's Banks tab and uploaded appeared correctly,
   and only the zone page changed. Upload from the GUI therefore works too.
3. Feature work follows `docs/ROADMAP.md` (ranked by value). Items 1-3 (radio IDs,
   contacts, RX groups on the Settings tab; TX contact from the 0x42/0x43 table) are
   implemented and verified on the radio (contact rename, RX group edit, radio ID choice).
   Items 4-5 done and verified on the radio. Item 6 (scan lists on the Settings tab,
   per-channel scan list, deleted channels removed from lists) implemented and
   simulator-tested, not checked on the radio. From here on the user has chosen to skip manual
   radio tests: rely on CPS/firmware analysis + tests/fake_dm32uv.py, and label features
   "not checked on a radio" in docs. Item 7 (common radio settings, tag 0x04) done the same
   way. Item 9 (zone management on the Settings tab) done. Item 8 skipped (needs a .048
   tester). Next: 10 (remaining settings), 11 (auto-detect). Method: CPS accessors (`re/BufRefs.java`, `re/DecompRefs.java`).
4. Upstream: prepared. Branch `dm32uv` in `../chirp` (one commit by chaffed, driver +
   synthetic image from `tools/make_test_image.py` + tester line; tox style/unit/driver
   pass). It references the existing issue #11840 ("New Model: Baofeng DM-UV32").
   Texts in `docs/upstream/`: the PR description, and a comment for #11840 to post after
   the PR is open. **PR opened 2026-09-27: https://github.com/kk7ds/chirp/pull/1656**
   (fork chaffed/chirp, branch dm32uv, commit 3d2264d). Next: post the #11840 comment,
   then respond to review; any fixes go on the same branch.
   Publish as "chaffed" only (see memory), never a real name.

## Firmware notes

The radio firmware (Baofeng's download, gitignored like the CPS) is unencrypted C-SKY
code at `0x300c000`. csky-elf binutils 2.44 is built in `~/opt/csky`, and
`re/fw_disasm.sh` disassembles it. Protocol handler: `0x3029438`. Write semantics and the
rules they imply are in PROTOCOL.md "Radio firmware". The radio must stay on firmware .047.

## Analysis notes

Key CPS functions: `0x44a210` is the codeplug read/write worker (found via the
Program → Read/Write menu IDs 32778/32779 → message map → dialog). Serial
helpers: `0x48f570` send(buf, len, delay_ms, bytewise), `0x48f630`
recv(buf, len, timeout_ms), `0x48f400` open. Ghidra's auto-analysis misses
much of the code; `re/MakeFuncs.java` creates functions at given entry points.
The stack probe at `0x4b7320` needs the `alloca_probe` call fixup, which
`Decomp.java` applies, or the decompiled output is garbage.
