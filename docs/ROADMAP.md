# Roadmap

Features the DM-32UV driver doesn't have yet, **ordered by value to users against effort.**
The driver already handles download, upload, channels (analog and the main DMR fields) and
zones; see the [README](../README.md).

**Value** is how much a typical DM-32UV owner gains; **effort** S/M/L is a rough size
for the work; **risk** is the chance of harming a radio's data if the feature is wrong.

| # | Feature | Value | Effort | Risk | Status |
|---|---------|-------|--------|------|--------|
| 1 | [DMR radio ID](#1-dmr-radio-id) | Very high | S–M | Low | **done** |
| 2 | [Talkgroup / contact list editing](#2-talkgroup--contact-list-editing) | Very high | M | Medium | **done** |
| 3 | [RX group list editing](#3-rx-group-list-editing) | High | S | Low | **done** |
| 4 | [Remaining channel options](#4-remaining-channel-options) | Medium | S | Low | **done** |
| 5 | [Channel deletion and gaps](#5-channel-deletion-and-gaps) | Medium | S | Medium | **done** |
| 6 | [Scan lists](#6-scan-lists) | Medium | M | Low | **done** (simulator-tested; not checked on a radio) |
| 7 | [Common radio settings](#7-common-radio-settings) | Medium–high | M | Medium | **done** (simulator-tested; not checked on a radio) |
| 8 | [Firmware 1.01.048 check](#8-firmware-101048-check) | Medium (growing) | S* | Low | |
| 9 | [Zone management polish](#9-zone-management-polish) | Low–medium | S | Low | **done** (simulator-tested; not checked on a radio) |
| 10 | [Remaining radio settings](#10-remaining-radio-settings) | Low–medium | L | Medium | **done** except passwords (CHIRP can't enter them), BDC1200 and roaming; APRS, DTMF, two-tone, five-tone added per the [plan](PLAN.md) (simulator-tested; not checked on a radio) |
| 11 | [Automatic radio detection](#11-automatic-radio-detection) | Low | S | Low | **done** (model check and firmware warning; checked on the radio) |

\* needs a tester whose radio runs firmware .048.

**Out of scope for CHIRP:** power-on picture, voice prompts, recordings, firmware updates,
the full 50,000–150,000-entry user ID database (tools like the vendor CPS or RadioID-based
utilities do this better), and the factory calibration/test functions.

Items 1–3 together make CHIRP a complete tool for the usual DMR setup (your ID, a few
talkgroups, RX groups). Without them, a new owner still needs the vendor CPS once.

---

## 1. DMR radio ID

**Why first:** a DMR radio can't be used on a network without its owner's DMR ID. Right now
CHIRP users have to set it with the vendor software or the keypad.

**What:** show the radio ID list (up to 8 entries of ID + name, `[RadioIdList]` in the CPS)
on CHIRP's Settings tab, editable. Also, if confirmed, add the per-channel "DMR ID" choice:
channel byte `+0x2a` is a 1–8 selector in the CPS dialog, very likely this list.

**Work:** find the list's page and layout with the CPS accessors (same method as the channel
and zone work), add a Settings tab, and let upload write that page. It needs a keypad or
CHIRP test on the radio.

## 2. Talkgroup / contact list editing

**Why:** DMR hams need talkgroups (for example Brandmeister TG 91, 3100, local TGs) as TX
contacts. Today CHIRP can pick an existing contact per channel, but can't add or change one.

**What:** edit the TX contact list: up to 250 entries of name, TG/DMR ID and call type
(`[NormalContact]`). The names are in tag 0x67; the IDs and call types still need to be found,
probably in the linear contacts area (flash `0x278000–0x6dbfff`, 44-byte records) or a
nearby page. Present it on the Settings tab, or as an importable list.

**Work and risk:** the contacts area isn't a tagged page. Writing it needs its own careful path,
built with the same rules as upload (whole aligned 4 KB blocks, read back and verify), and
tested against the simulator first.

## 3. RX group list editing

**What:** edit RX group lists (up to 32; a name plus member contacts; tag 0x0F, layout
largely known). Small once item 2 exists, because members refer to contacts.

## 4. Remaining channel options

**Quick win.** These channel fields are already mapped in [PROTOCOL.md](PROTOCOL.md) and
only need adding as extras (and checking on the radio): TX admit, RX squelch mode, step, PTT ID,
VOX, compander, signalling type, emergency system and flags, APRS options, TDMA direct
mode, private/short-data confirm, lone worker.

## 5. Channel deletion and gaps

**Why:** correctness. The radio keeps a channel count and the CPS keeps channels numbered
1..count. Appending channels and adding them to zones works, but deleting a channel
in the middle, or leaving gaps, hasn't been tested on the radio. It could leave a
channel the radio can't show, or confuse its channel count.

**What:** test deletes and gaps on the radio. Then either handle them (for example
renumber, as the CPS "Delete" does, updating zones), or clearly refuse them in the driver.

## 6. Scan lists

**What:** scan lists (tag 0x11: name, channels, CTC scan mode, TX mode, stay time) and the
per-channel scan list selection (`+0x19`). Also map CHIRP's "skip" column to it if sensible.

## 7. Common radio settings

**What:** a first Settings tab with the options people change most. Examples: welcome/boot
text (in tag 0x04), squelch levels, backlight and display, key beep, VOX, TOT (transmit
timeout), power save, keypad lock, and the side-key functions.

**Work:** tag 0x04 alone has several hundred CPS accessor functions. The method is proven:
the accessors give offsets and bit masks, and the CPS language file gives labels and value lists.
Start with the ~20 most-used and add more over time. The settings pages must be written with
the same verified upload, and never tags 0x02/0x69.

## 8. Firmware 1.01.048 check

**Why:** Baofeng's current firmware (.048) "expands to 150K contacts", which may move the
contacts area or other data. Owners will increasingly be on .048.

**What:** a tester on .048 runs a download (and a backup read with `tools/dm32uv_read.py
--all-pages`) so the layouts can be compared. The firmware itself can also be compared
statically with `re/fw_disasm.sh`.

## 9. Zone management polish

**What:** reorder channels within a zone (CHIRP's bank index), delete or reorder zones
(today only the last zone is removed when emptied), and zone member limits in the UI.

## 10. Remaining radio settings

**What:** the rest of tag 0x04 and the other settings pages (0x03, 0x06, 0x0A, 0x0B, 0x65,
0x66): DTMF, two-tone and five-tone signalling, emergency systems, APRS, GPS, roaming,
menu configuration and so on. A lot of fields, each of interest to few users.

## 11. Automatic radio detection

**What:** let CHIRP's "Detect" identify the radio from its `PSEARCH` reply (`DP570UV`).
Also check whether other Baofeng DMR models share this protocol (same CPS family), so they
could be supported as aliases with testers.
