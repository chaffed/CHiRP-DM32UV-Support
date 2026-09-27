# Plan: review fixes, passwords, APRS, DTMF / two-tone / five-tone

Written 2026-09-27 after a review of `driver/baofeng_dm32uv.py`. Covers the rest of
[roadmap item 10](ROADMAP.md#10-remaining-radio-settings), plus fixes the review found.

Order: **Phase 0** (review fixes) → **A** passwords → **B** APRS → **C** DTMF, then
two-tone, then five-tone. Phase 0 and A fix wrong behaviour in the driver that's already
submitted. B only adds fields to a page upload already writes. C adds new pages to upload
and is the largest part.

Testing follows the project rule from 2026-09-27: CPS/firmware analysis plus simulator
tests, and new features are labelled "simulator-tested; not checked on a radio".

---

## Phase 0: fixes from the review

Items marked *confirmed* were reproduced against the simulator or measured.

| # | Issue | Severity |
|---|-------|----------|
| 0.1 | Emptied channel page never uploaded (*confirmed*) | High |
| 0.2 | Slow with large codeplugs (*measured*) | High |
| 0.3 | Write password ignored on upload (see part A) | Medium |
| 0.4 | Zone edits silently dropped with ≥ 222 zones (*confirmed*) | Medium |
| 0.5 | Non-ASCII names and out-of-range values can't be edited (*confirmed*) | Medium |
| 0.6 | Upload undoes the zone-pointer remap after a zone reorder | Low |
| 0.7 | Stale text in the prompts, docstrings, README and PROTOCOL.md | Medium (easy) |
| 0.8 | A lost write ACK aborts the upload; the simulator can't show it | Low |
| 0.9 | Upload order: references are written before what they point to | Low |
| 0.10 | Small ones | Low |

**0.1 Emptied channel page is never uploaded.** `do_upload` skips any slot whose first
4095 bytes are all 0xFF, treating it as "the radio has no such page". Deleting every channel
on one channel page (85 consecutive numbers, e.g. 85–169) while later channels exist makes
that page all 0xFF. Upload then skips it, and the radio keeps the old channels.
Reproduced: delete channel 90 when it is the only channel on page 0x13. Upload writes one
page (not 0x13), and channel 90 is still there after a re-read.
*Fix:* a slot counts as present if its tag byte (0xFFF) equals the tag, i.e. the page was
downloaded or created with `_put`. If it is present and the radio has that tag, compare and
write it even when its body is all 0xFF. Add this scenario to `tests/test_upload.py`.

**0.2 Slow with large codeplugs.** With 4000 channels and 800 contacts, `get_memory` takes
8.9 ms per channel, so about 35 s to open the image. The Banks tab adds about 3.5 ms per
channel. 80% of the time is `_contacts()`: it runs for every channel (for the TX contact
choice) and copies a 4 KB page for each used contact slot. `_dmr_names` also copies the
whole 311 KB image twice per channel.
*Fix:* read each contact page once, and cache the lookup lists (contacts, radio IDs, RX
groups, scan lists, key/emergency names, and a channel → zones index). Clear the caches in
`_put`, `set_settings`, the zone helpers, `set_memory` and `process_mmap`. Target:
< 1 ms per channel. Keep a benchmark script in `tests/` (not part of CHIRP's tests).

**0.3 Write password ignored.** The driver checks only the read-password flag. With a write
password set, the CPS asks for it, but the driver uploads without asking. See part A.

**0.4 Zone edits dropped with many zones.** The `zone_order` field has a 1000-character
limit. The list for 250 zones is 1141 characters, so from about 222 zones CHIRP can't load
the field. It leaves the field out of what it passes to `set_settings`, and the driver then
ignores every zone name, member and order edit, without an error.
*Fix:* size the limit from `ZONE_COUNT` and check the other list fields the same way. RX
groups (32 × 18 = 576 of 600) and zone members (382 of 400) fit.

**0.5 Names CHIRP can't show.** A zone, contact, radio ID, RX group or scan list name with a
byte ≥ 0x80 (for example a Chinese name entered in the vendor CPS) fails CHIRP's charset
check. The field shows empty and is dropped on save. For contacts, the ID and call type
edits of that contact are then ignored too, because the driver keys on the name field. The
same happens to a value out of range, such as a radio ID of 0xFFFFFF.
*Fix:* show non-ASCII characters as `?`, and keep the original bytes unless the user changes
the name. This is the same trick as the contact name padding. Clamp numbers into range for
display.

**0.6 Zone pointers after a reorder.** `_set_zone_list` remaps the radio's current-zone bytes
when zones are reordered or deleted. `_keep_display_state` then copies the radio's live bytes
over them at upload, so the radio ends up on a different zone. It also only checks the
position against the member count for zones 1–28, the ones on the first zone page.
*Fix:* at upload, map the radio's current zone to the new list by identity (name and
members), and check the position using the image for any zone number.

**0.7 Stale text.**
- `get_prompts()` "experimental" says upload changes only channel memories, and
  `pre_upload` says it writes only channel pages. Both have been wrong since roadmap items
  1–10.
- The module docstring and the `UPLOAD_TAGS` comment say the same.
- README "What upload changes" says radio-wide settings aren't changed.
- PROTOCOL.md had the PASSSTA flag bytes swapped, and gave the password block as
  0x430–0x443. It is 0x430–0x44A. PROTOCOL.md was corrected with this plan.

**0.8 Lost write ACK.** When no ACK arrives, `_write_page` waits 2.5 s before reading the
page back. The firmware ends the session after 2 s idle, so the read-back fails and the
upload stops partway. Re-running the upload recovers, because it skips pages that already
match. The simulator doesn't model the idle timeout, so no test can see this.
*Fix:* model the 2 s timeout in `fake_dm32uv.py`. After a lost ACK, redo the handshake
(`_identify`, `_enter_program`) and continue with the same page.

**0.9 Write order.** Upload writes channel pages before the lists they refer to, and the
contact index (0x0B) before the contact records (0x44–0x48). An interrupted upload can leave
references to data that isn't there yet.
*Fix:* write records before their index, lists before channels, and zones last.

**0.10 Small ones.**
- A settings edit elsewhere strips trailing spaces from contact, RX group and radio ID
  names, which rewrites their pages for nothing.
- Clamped channel extras (squelch > 9, unknown list values) are written back as the clamped
  value when the channel is edited.
- Download silently takes the first of two pages with the same tag. Upload refuses them;
  download should at least warn.
- A deleted channel stays as a scan list's "designed channel" if the list ends up empty.

Also worth saying in the README: a CHIRP image holds tag 0x04 in full, including any
passwords in clear text, as well as the radio ID and contacts. Don't attach real images to
public bug reports.

---

## Part A: passwords

### What is known

- **Storage, tag 0x04** (CPS accessors, dialog `0x445c10`):

  | Offset | Content |
  |--------|---------|
  | 0x430 | power-on password flag |
  | 0x431–0x438 | power-on password |
  | 0x439 | write password flag |
  | 0x43A | read password flag |
  | 0x43B–0x442 | write password |
  | 0x443–0x44A | read password |

  A flag is 0xA5 when set and 0x00 when not (test radio). Passwords are up to 8 ASCII
  characters, ended by 0x00 or 0xFF.
- **Protocol (firmware):**
  - `PASSSTA` replies `'P'`, then the byte at 0x439 (write flag), then the byte at 0x43A
    (read flag).
  - `PASWORD` → `06`, then `'P' 'W'|'R' pw[8]` → `06` if it matches, `15` if not.
- **Enforcement:** the firmware remembers nothing about the check, and `R`/`W` work either
  way. The protection lives entirely in the vendor CPS. The firmware also accepts a built-in
  factory password; the driver must never use it, and these docs don't record it.

### Plan

1. **CPS analysis.** Decompile `0x445c10` (dialog), the setters `0x445e50`, `0x445f30`,
   `0x446010` (passwords) and `0x4460f0`, `0x446130`, `0x446170` (flags), and `0x417bb0`.
   The last reads all three passwords, perhaps when a file is opened. Find the allowed
   characters and length, what "off" stores, and whether the CPS clears the password bytes
   when a flag is turned off.
2. **Upload with a write password** (fixes 0.3). If PASSSTA shows the write flag, the upload
   sends `PASWORD` with a password **the user typed**, and aborts before any `W` if the
   radio answers `15`. This matches the CPS. The driver never authenticates with the
   password it downloaded from the radio, because that would bypass the owner's protection.
   Where the user types it is decision 2 below.
3. **Download with a read password:** keep refusing (CHIRP can't ask for a password before a
   download). Improve the message: say how to remove the password with the vendor CPS.
4. **Settings tab, "Passwords" group:**
   - power-on password: on/off and value;
   - write password: on/off and value.

   Validate with the CPS rules. Labels warn that a forgotten power-on password locks the
   radio at power-on until it is cleared with a programming tool.
5. **Simulator.** Build the PASSSTA reply from the settings page. Implement `PASWORD`
   (`06`/`15`). Record as a violation any `W` sent while the write flag is set without a
   successful `PASWORD`: the firmware doesn't enforce this, but the driver must.
6. **Tests.**
   - A correct password uploads.
   - A wrong or missing password aborts before any `W`.
   - A read password refuses the download.
   - Changing the write password in CHIRP authenticates with the old one and writes the
     new one.
   - Passwords never change unless their fields do.

**Risk:** medium. A mistake could lock someone out at power-on. All writes stay on tag 0x04,
which upload already writes and verifies. A one-off radio check (set, upload, power cycle,
clear) would be worth it here if you want one.

---

## Part B: APRS

### What is known

- **Radio settings, tag 0x04, 0x301–0x333** (all accessors called from dialog `0x439c00`;
  its OK handler is `0x488580`):

  | Offset | Content |
  |--------|---------|
  | 0x301 | byte |
  | 0x302 | bit 0 |
  | 0x306–0x30E | latitude as ASCII (`23.000000` on the test radio); helper `0x43abc0` |
  | 0x30F | byte |
  | 0x310–0x318 | longitude as ASCII (`118.00000`); helper `0x43acb0` |
  | 0x319 | byte |
  | 0x31E | u16 |
  | 0x330 | byte |
  | 0x331 | bit 0 |
  | 0x332 | u16 (`0x01C8` on the test radio); helper `0x43ae00` |

  Language sections: `[AprsCallType]`, `[Latitude]`, `[Longitude]`, `[ChannelAprsReport]`.
- **Per channel, already in the driver as extras:** APRS receive (+0x1A), report type
  (+0x1C bits 3–2, Off/Digital), analog and digital APRS PTT mode (+0x1C bits 1/0).
  Byte +0x20 (1–8 in the CPS dialog) is still unlabelled and may be the APRS report channel.

### Plan

1. **CPS analysis.**
   - Decompile `0x439c00`, `0x488580` and the three helpers.
   - For each control: offset, type, range, and label (control ID → `[Resource]`, combo →
     language section).
   - Find out whether analog APRS (callsign, SSID, path, symbol) is on this page or
     elsewhere. "Analog APRS PTT mode" suggests it exists. If it's on another tag, that tag
     is new to upload and follows the rules in C.4.
   - Label channel +0x20 from the channel dialog.
2. **Firmware cross-check (optional).** Find the code that reads 0x300+ to confirm units
   (report interval, coordinate format).
3. **Driver.** Add an "APRS" group to `RADIO_SETTINGS`.
   - Coordinates need a new `latlon` kind: validated decimal text, zero-padded as the CPS
     writes it, with hemisphere lists.
   - Target IDs use integer settings.
   - Add +0x20 as a channel extra once it has a label.
4. **Tests.**
   - Round trip every field.
   - Invalid coordinates are refused.
   - Only the expected bytes of tag 0x04 change.
   - The password bytes stay unchanged.

**Risk:** low. One page, already written by upload.

---

## Part C: DTMF, two-tone, five-tone

### What is known

- **Per channel:**
  - signalling type +0x26 bits 3–1 (None, DTMF, Two Tone, Five Tone, BDC1200) and RX
    squelch mode (optional signalling), both already extras;
  - +0x27 holds two 4-bit code selections whose meaning depends on the signalling type
    (CPS `0x414470`).
- **CPS pages and accessor ranges:**

  | Tag | CPS accessors | Use on the test radio |
  |-----|---------------|-----------------------|
  | 0x03 | `0x479df0–0x47b740` | about 1200 bytes |
  | 0x06 | `0x47bb10–0x47d560` | nearly full, 16-byte records |
  | 0x65, 0x66 | `0x4843b0–0x485110` | nearly full |

  Which tag holds which system is not known yet.
- **Language sections:**
  - DTMF: `[DtmfEncode]`, `[DtmfGroupCode]`, `[DtmfIntervalSign]`, `[DtmfAutoAck]`;
  - two-tone: `[TwoToneDecode]`, `[TwoToneDecodeFormat]`, `[TwoToneDeocdeCall]`,
    `[TwoToneDeocdeAck]`, `[TwoToneEncode]`, `[TwoToneEncodeSendCode]`;
  - five-tone: `[FiveToneDecodeStandard]`, `[FiveToneDecodeResponse]`,
    `[FiveToneEncodeStandard]`, `[FiveToneMsgCode]`, `[FiveToneMsgCodeFunc]`,
    `[FiveToneMsgCodeResponse]`, `[FiveToneSpeialCall]`;
  - other: `[OptionOneTone]`, `[AnalogEmerSignalling]`.

### Plan

1. **Map the pages.**
   - Run the accessor pass used for tags 0x04/0x0B/0x0F/0x11/0x67 (`DecompRefs`, `BufRefs`,
     `acc_summary`) over the three accessor ranges.
   - Find the dialogs that call each accessor (system settings, encode list, decode list
     for each of DTMF, two-tone and five-tone).
   - Label everything from `[Resource]` and the sections above.
   - Don't assume 0x65/0x66 are signalling until a dialog proves it. Full pages could also
     be message texts or logs.
2. **Check against the test radio.** Decode its pages with the map. Factory defaults must
   come out plausible: DTMF codes as digits, two-tone frequencies in audio range, standards
   from the five-tone list.
3. **Rule out runtime data.** Check that the firmware doesn't write these pages during
   normal use (call logs or counters would be overwritten by an upload). Search for flash
   writes naming these tags.
4. **Upload.** Add a tag to `UPLOAD_TAGS` only once its whole page is understood, and never
   0x02/0x69. Write only when the page changed, as now.
5. **Driver, one system at a time.**
   - **DTMF first** (the one hams use: PTT ID/ANI codes and DTMF calling). System options
     as a `RADIO_SETTINGS`-style table on a new tag base. Encode/decode lists as rows (code
     with the DTMF charset `0-9 A-D * #`, and a name), shown like contacts. The +0x27
     channel selection becomes an extra listing the entry names for the channel's
     signalling type.
   - **Two-tone next** (tone A/B frequencies, durations, formats).
   - **Five-tone last** (standards, codes, message codes). This has the fewest users and
     the most fields.
6. **Tests.** Add synthetic signalling data to `tools/make_test_image.py`. Round-trip each
   list and option, check that upload touches only the intended pages, and run CHIRP's tox
   jobs (style, unit, driver).

**Risk:** medium. These are new pages for upload. Steps 3 and 4 keep it contained.

---

## Decisions needed

1. **Read password in CHIRP.** Recommendation: don't offer setting it. CHIRP can't ask for a
   password before a download, so setting it locks CHIRP out of the radio.
2. **Where the write password is typed for upload.** Recommendation: a "Password for upload"
   field on the Settings tab. It isn't written to the radio; it's kept in the image's
   metadata. The alternative is to refuse uploads while a write password is set.
3. **Which PR.** Recommendation: Phase 0 goes into PR #1656, because it fixes submitted
   code. Parts A–C go in follow-up PRs after it's merged, to keep the review small.

## Sizes

| Part | Effort | Mostly |
|------|--------|--------|
| Phase 0 | M | driver and simulator; 0.1, 0.2, 0.4 and 0.7 first |
| A passwords | S–M | CPS dialog, handshake, simulator |
| B APRS | M | one CPS dialog, one new setting kind |
| C DTMF | M | page mapping, list UI, channel selection |
| C two-tone | M | reuses the C list code |
| C five-tone | M–L | many fields |
