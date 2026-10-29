# Baofeng DM-32UV programming protocol

Reverse engineered from `DMR CPS.exe` v1.60 (2026-06-08) with Ghidra.
Addresses such as `0x44a210` refer to that binary. Most of this comes from
static analysis. The whole read session (steps 1–11 below, with a page scan
and block reads) was checked against a real radio on 2026-09-26 (firmware
`DM32.01.01.047`); see "First full read" below. **Nothing about writing
has been tested.**

## Serial link

- 115200 baud, 8N1, DTR and RTS asserted (`FUN_0048f400`, `[com]` section of `cps.ini`)
- The CPS waits 10 ms before each send. Default receive timeout is 500 ms;
  4 KB block reads and writes use 5000 ms.

## Session (codeplug read/write, `FUN_0044a210`)

Menu IDs: Program → Read = 32778, Write = 32779. Both open the same dialog.
It passes mode 0 for read and 1 for write, and runs `FUN_0044a210` in a worker thread.

| # | Send | Expect | Notes |
|---|------|--------|-------|
| 1 | `PSEARCH` | 8 bytes, `[0] == 0x06` | Retried up to 5 times. Bytes 1–7 are a model ID: `DP570UV` on a real DM-32UV. |
| 2 | `PASSSTA` | 3 bytes: `'P' wr rd` | The firmware replies with settings bytes 0x439 (`wr`) and 0x43A (`rd`). `0xA5` means that password is set, `0x00` that it isn't. The CPS checks `wr` when writing and `rd` when reading. |
| 2a | `PASWORD` | `0x06` | Only when the flag for the current direction is `0xA5`. |
| 2b | `'P' ('R'\|'W') pw[8]` (10 bytes) | 1 byte | Password is ASCII, padded with 0xFF, NUL-terminated if shorter than 8. The firmware compares it with settings 0x443 (`R`) or 0x43B (`W`) and replies `0x06` if it matches, `0x15` if not. It stores no result: `R`/`W` work without it, so only the CPS enforces passwords. |
| 3 | `SYSINFO` | 1 byte (`0x06`) | |
| 4 | `V 00 00 40 0D` | `'V' x n` then `n` bytes | Radio info blob |
| 5 | `V 00 00 00 i` for i = 1..16, except 12 | `'V' x n` then `n` bytes | See the V table below |
| 6r | read: `G 00 00 00 00 01` | 0x106 bytes: `'S'` + 5-byte header + 256 data bytes | 256-byte settings block |
| 6w | write: `S 00 00 00 00 01` + 256 bytes | `0x06` (5 s timeout) | Only sent if that block was loaded |
| 7 | `FF FF FF FF 0C` | — | Same bytes as CHIRP `baofeng_uv17` `_magics2` |
| 8 | `PROGRAM` | `0x06` | Radio enters programming mode |
| 9 | `02` | 8 bytes | Identification. The real radio replies `ff` × 8. |
| 10 | `06` | `0x06` | |
| 11 | page scan, block transfer | | See below |

### V queries

The payload for each is `n` bytes. Multi-byte values are little-endian.
The reply header is `'V' i n`, except for `V 00 00 40 0D`, which returns `'V' 0D 40`.

Flash ranges are two u32 values, `start, end` (inclusive). The addresses fit
in 24 bits and the top byte has always been 0 on a clean read. (One read gave
`0x80001000` for V10's start; that was a link bit error, see "Serial link
reliability".)

| i | Meaning | Real radio (2026-09-26) |
|---|---------|-------------------------|
| 1 | Model / firmware string (shown in the dialog title) | `DM32.01.01.047` |
| 2 | ? | `00 00 00 00 00 00 09 b6 00 00 09 b6` |
| 3 | Date string | `2022-06-27` |
| 4 | Version string | `D1.01.01.004` |
| 5 | Version string | `R1.00.01.001` |
| 6 | Flash range | `0x201000 – 0x264fff` |
| 7 | Flash range | `0x0c9000 – 0x149fff` |
| 8 | Flash range | `0x180000 – 0x200fff` |
| 9 | Flash range (recordings; gone on .048, see below) | `0x6dc000 – 0xffffff` |
| 10 | Flash range of the **codeplug page area** | `0x001000 – 0x0c8fff` (200 pages) |
| 11 | Version string | `C1.00.01.001` |
| 13 | ? | empty (`n = 0`) |
| 14 | Flash range | `0x150000 – 0x175fff` |
| 15 | Flash range of the **digital contacts area** | `0x278000 – 0x6dbfff` |
| 16 | `u24`, the digital contact limit | `0x00c350` = 50000 (`0x0249f0` = 150000 on .048) |

The flash ranges fit together without gaps from 0x001000 to 0xffffff, except
for 0x14a000–0x14ffff, 0x176000–0x17ffff and 0x265000–0x277fff.

**Firmware .048 compared with .047 (2026-10-29).** From the serial trace and image a
.048 radio's owner attached to chirpmyradio bug #12652 (`DM32.01.L01.048`), against our
.047 radio's full backup. Differences: V1; V2 (`09b6` → `1737`, meaning still unknown); V9
is `000000-000000`; V15 grew to `0x278000 – 0xffffff`, taking over the V9 area; V16 is
150000. That matches the .048 changelog ("Expand to 150K Contacts, cancel the
recording"): the recordings area became digital contact space. Everything the driver
uses is unchanged: V10 (codeplug area, 200 pages), the `G` block, the 64-byte blob and
V3–V8, V11, V14 are identical; the .048 radio has no page tag that the .047 radio lacks
(pages only our radio has: 0x4F–0x5B, which the driver skips, and zone pages the other
owner doesn't use); every slot the driver fills carries the expected tag; and the
settings page differs from ours in 9 of 4096 bytes (user settings). The driver parsed
the .048 image correctly: 38 channels, 20 contacts, 3 zones, 3 radio IDs, settings.
Not checked on .048: uploading. The CPS leaves stale bytes after a name's NUL
terminator (`52 Simplex\0Dv`), which the driver now cuts off; that is a CPS habit, not
a .048 change.

Real `V 00 00 40 0D` payload (64 bytes): `03 4e 2d`, then zeros, with `3f` at
offset 0x20. Meaning unknown. (Stray `80` bytes seen at other offsets were link
bit errors.)

### Serial link reliability: it was the cable

**Summary (2026-10-02):** the received-byte errors came from the CH340-based programming
cable, not the radio. With an FTDI FT231X cable on the same radio, 50 info queries (3200
bytes) and a full read (1181 commands, 2.16 MB) had no errors at all, and a download by the
driver reading each block once matched the three-copy dump in every page. The driver
therefore reads each block once and stops on any bad reply (only PSEARCH is repeated, as the
vendor CPS does). It doesn't inspect the port (the CHIRP lead developer preferred not to,
since not every CH340 cable may be faulty); a visibly garbled reply (page tag or model ID
with bit 7 set) stops the transfer with advice about the cable.

With the CH340 cable (rev 2.64, Linux `ch341`), received bytes had bit 7 flipped from 0 to 1,
never anything else and never in the PC-to-radio direction. The rate varied from 1 in 1000 or
so (2026-09-26) to 1 in 47 (2026-09-27). That's a sampling-time error at the end of each
byte, so most likely the cable's clock (CH340 variants without a crystal) against the radio's.
Rates near 115200 didn't help: the CH340's nearest rates (116505, 117647, 114286) garbled the
handshake or lost replies.

**The radio stops answering and needs a power cycle** after it receives garbled
commands (wrong baud rate). **Do not send it anything at a baud rate other than 115200.**

## Block commands

```
Read:   'R' a0 a1 a2 l0 l1          -> 'W' a0 a1 a2 l0 l1 data[l]
Write:  'W' a0 a1 a2 l0 l1 data[l]  -> 0x06
```

The address is 24-bit little-endian and the length is 16-bit little-endian. Normal transfers use l = 0x1000 (one 4 KB flash page).

## Codeplug storage: tagged 4 KB pages

The codeplug is not one contiguous image. The flash between `V10.start` and
`V10.end` is split into 4 KB pages, and **the last byte of each page (offset
0xFFF) is a tag** saying what the page holds. `0xFF` means the page is free.

1. **Scan:** for each page, read 1 byte at `page + 0xFFF` (`R .. 01 00` returns 7 bytes, the last being the tag).
2. **Read:** for each wanted tag, find its page and read the whole 4 KB.
3. **Write:** for each tag, write to the page that already has that tag,
   or else to the first free page. The tag byte stays at offset 0xFFF.

| Tags | Pages | CPS buffer | Probable contents (unverified) |
|------|-------|------------|-------------------------------|
| 0x02, 0x03, 0x04, 0x06, 0x0A, 0x0B, 0x0F, 0x10, 0x11, 0x65, 0x66, 0x67 | 1 each | separate buffers | 0x03 two-tone and five-tone, 0x04 radio settings, 0x06 DTMF (and BDC1200), 0x0B contact index, 0x0F RX groups, 0x10 emergency systems and encryption keys, 0x11 scan lists, 0x65/0x66 roaming (CPS roam channel/zone code), 0x67 radio IDs |
| 0x12 – 0x41 | 48 | one 192 KB buffer | probably channels (for example 4000 × 48 B) |
| 0x42 – 0x43 | 2 | | |
| 0x44 – 0x48 | 5 | continues the tag 0x0B buffer at +0x1000 | |
| 0x5C – 0x64 | 9 | | |

Digital contacts are stored **linearly** from `V15.start`, in 44-byte records, and read or written as 4 KB blocks. First `R start 04 00` returns 4 bytes of length information.

## First full read (2026-09-26)

Done with `tools/dm32uv_read.py` reading every block 3 times and merging
the copies (see "Serial link reliability"): 776 commands in 70 s, 117
bit-7 errors corrected, no other errors. The radio accepted repeated `R`
reads of the same address.

- `G 00 00 00 00 01` returned `S 00 00 00 00 01` and 256 bytes of `ff`.
- **Pages are scattered** across the 200-page area, and 101 are in use. The order looks
  like wear levelling, not tag order, so a driver must always scan.
- **Tag `0x00` is on 30 pages.** Probably stale pages: NOR flash can clear
  bits without erasing, so writing the tag byte to 0 marks a page as obsolete.
  Unconfirmed. No tag the CPS reads appears on more than one page.
- **Channel tags `0x12–0x41` are only partly present** (17 of 48 on this radio).
  Probably a page is only allocated once it holds channels.
- **Tags in use that the CPS worker does not read:** 01, 05, 07, 08, 09, 0c,
  0d, 0e, 4b, 4f–5b, 69–6e, 74, 75, 7c. They may belong to other CPS
  functions (for example the recording list or boot image). A second read (`dump3`, all 101 pages) gave a first look at them:

  | Tags | Contents |
  |------|----------|
  | 00 | Stale copies of other pages. One holds `Zone 1` and `Func Demo`, so it's an old zones page. |
  | 07, 09, 0e, 4f, 50, 52–55, 57–59, 5b | About 99% `ff`: allocated but empty |
  | 69 | Labels `RxVL`, `RxVM`, `RxVH`, `RxUL`…: looks like **calibration**, do not write |
  | 51, 6b | Long runs of one repeated 16-bit value (`c2 18`, `5e 3d`): probably RGB565 image data |
  | 56 | Increasing 16-bit values (`9615`, `9616`, …): some index table |
  | 01, 05, 08, 0c, 0d, 4b, 5a, 6a, 6c–6e, 74, 75, 7c | Binary, not identified yet |

- **Reads repeat exactly.** Across two separate sessions (`dump2`, `dump3`),
  the page map, all V/G/`02` replies and all 40 pages read both times were
  identical byte for byte, although each session corrected different bit
  errors (117 and 1831). The bit-7 error rate was 0.15% of received bytes.

### Channel pages (tags 0x12–0x41)

The CPS keeps the 48 pages in one 192 KB buffer, page p (tag 0x12 + p) at
p × 0x1000. Records never cross a page boundary. Its channel accessors (for example
`0x47dcc0`, which gets a channel's name) locate channel n (1–4000) like this:

| Channel | Page | Offset in page |
|---------|------|----------------|
| 1–84 | 0 (tag 0x12) | 0x10 + 0x30 × (n − 1), after a 16-byte header |
| 85–4000 | n / 85 | 0x30 × (n mod 85) |
| VFO A (n = 4001) | 47 (tag 0x41) | 0xF9F |
| VFO B (n = 4002) | 47 | 0xFCF |

The header starts with a u16 channel count (`0x47dc80` writes it). On this
radio it is `0x19` = 25, and there are exactly 25 programmed channels. An
earlier note here described the pages as a continuous stream. That was wrong: it
agreed with this layout only on page 0, where all 25 channels are. VFO B's
record ends at 0xFFE, just before the tag byte. Known fields, as offsets from the start of the record:

Field map from the CPS channel accessors (`0x47dc50`–`0x482530`, one
getter and one setter per field). Labels come from the channel dialog
`0x4121c0`: which language section fills each combo box, or which
checkbox control ID (looked up in `[Resource]`) each value goes to. Value lists are the
sections of the CPS language file (installer file `10`). **Check** says what
confirms the field: *keypad* = changed on the radio and seen in a diff; *data* =
consistent with all 25 channels on the test radio, e.g. a channel named "DTMF Call"
has signaling type DTMF; *upload* = written by the driver from CHIRP and confirmed on the
radio's display; *CPS* = accessor and dialog only.

| Offset | Bits | Field | Values | Check |
|--------|------|-------|--------|-------|
| 0x00 | 16 bytes | Name | ASCII, NUL-padded; all `ff` = no name | data |
| 0x10 | 4 bytes | RX frequency | 8-digit BCD, little-endian, 10 Hz units; `ff`×4 = empty | data |
| 0x14 | 4 bytes | TX frequency | same | data |
| 0x18 | 7–4 | Channel type | 0 Analog, 1 Digital, 2 Fixed Analog, 3 Fixed Digital `[ChannelMode]` | data |
| 0x18 | 3 | Forbid TX | checkbox | CPS |
| 0x18 | 2–1 | Power | 0 Low, 1 Middle, 2 High `[PowerSelect]`, stored as `bits >> 1` (so `0x04` = High) | keypad, upload |
| 0x18 | 0 | Lone Work | checkbox | CPS |
| 0x19 | 7 | Bandwidth | 0 12.5 kHz, 1 25 kHz | data |
| 0x19 | 6 | Auto Scan | checkbox | CPS |
| 0x19 | 5–0 | Scan list | 0 none, n = scan list n (names from tag 0x11) | CPS |
| 0x1A | 7 | Forbid Talkaround | checkbox | CPS |
| 0x1A | 6–4 | TX admit | analog: 0 Allow TX, 1 Channel Idle, 2 Match CTC, 3 Non Match CTC; digital: 0 Always, 1 Channel Idle, 2 Color Code Idle | CPS |
| 0x1A | 2 | APRS Receive | checkbox | data |
| 0x1A | 1–0 | VFO only: repeater offset direction | 0 none, 1 +, 2 − `[PinCha]` | CPS |
| 0x1B | 7 | Emergency Indicator | checkbox | data |
| 0x1B | 6 | Emergency ACK | checkbox | data |
| 0x1B | 4–0 | Emergency system (digital) | 0 none, n = entry n of the tag 0x10 emergency list (`[DigitalEmergency]`) | data |
| 0x1C | 7–4 | Squelch level | 0–9 | data (all 3) |
| 0x1C | 3–2 | APRS report type | 0 Off, 1 Digital `[ChannelAprsReport]` | data |
| 0x1C | 1 | Analog APRS PTT mode | checkbox | CPS |
| 0x1C | 0 | Digital APRS PTT mode | checkbox | CPS |
| 0x1D | 7 | Private Confirm | checkbox | CPS |
| 0x1D | 6 | Short Data Confirm | checkbox | CPS |
| 0x1D | 5 | TDMA Direct Mode | checkbox. The channel named "TDMA Direct Mode" does not have it set. | CPS |
| 0x1D | 4 | Time slot | 0 Slot 1, 1 Slot 2 | upload |
| 0x1D | 3–0 | Color code | 0–15 | data |
| 0x1E | byte | Encryption key | 0 none, n = entry n of the tag 0x10 key list (`[PrivacyType]` dialog). 1 on "Digital Encrypt". | data |
| 0x1F | 6 | Encryption | checkbox | data |
| 0x1F | 5–0 | RX group list | 0 none, n = list n of tag 0x0F. 1 on all digital channels. | data, upload |
| 0x20 | byte | APRS report channel: one of the 8 report channels of the APRS settings (control 0x5a2, label "APRS Report Channel") | index 0–7 = 1–8 | CPS |
| 0x21 | 2 bytes | CTC/DCS decode | see tones below | upload |
| 0x23 | 2 bytes | CTC/DCS encode | see tones below | upload |
| 0x25 | 5 | Compander | checkbox | CPS |
| 0x25 | 4 | VOX | checkbox | CPS |
| 0x25 | 3–0 | Unknown: Off, 1–4 (maybe scramble) | | CPS |
| 0x26 | 7 | PTT ID Display | checkbox | CPS |
| 0x26 | 6–4 | RX squelch mode | 0 Carrier/CTC, 1 Optional Signaling, 2 CTC & Opt., 3 CTC or Opt. | data |
| 0x26 | 3–1 | Signaling type | 0 None, 1 DTMF, 2 Two Tone, 3 Five Tone, 4 BDC1200 | data |
| 0x27 | 7–4, 3–0 | RX signaling system (high nibble), TX signaling system (low nibble): None, or entry 1–8 for two-tone, 1–4 for BDC1200; unused for DTMF and five-tone (`0x414470`) | 0 = None | CPS |
| 0x29 | 7–4 | Step | 2.5, 5, 6.25, 10, 12.5, 25, 50, 100 kHz `[ChannelStepFreq]` | CPS |
| 0x29 | 3–2 | PTT ID | 0 Off, 1 BOT, 2 EOT, 3 Both `[ChannelPttId]` | data |
| 0x2A | byte | Unknown, 1–8 in the dialog | index 0–7 | CPS |
| 0x2B | byte | Radio ID | 0 = default, n = radio ID n of tag 0x67 (up to 250). *Was mislabelled "TX contact" at first; the TX contact is in a separate table (see DMR lists).* | upload |
| 0x2C | 4 bytes | VFO only: repeater offset, BCD like the frequencies | | CPS |

**DMR lists.** From the CPS accessors and the dialogs that use them (`[RadioIdList]`,
`[NormalContact]`, `[RxGroupList]` in the language file), checked against the test radio.
Entries are 1-based; names are NUL- or `ff`-padded.

*Radio IDs* (tag 0x67; the radio's own DMR IDs; CPS `0x474140`–`0x474450`): byte 0 = count
(max 250); entry n at 16 × n = u24 LE DMR ID + 12-char name. Channel byte `+0x2b` selects
one (0 = default). *An earlier version of these notes called this list "TX contacts"; that was
wrong.*

*Contacts* (talkgroups and private IDs; up to 800; CPS `0x474b50`–`0x4758e0`):

| Where | Contents |
|-------|----------|
| tag 0x0B +0x00 | u16 number of contacts |
| tag 0x0B +0x02 | u16 number of Group Call contacts; +0x04 u8 number of All Call contacts |
| tag 0x0B +0x10 | 100-byte bitmap, bit k−1 set = slot k **free** |
| tag 0x0B +0x100 | used contacts sorted by name (byte order), 2 bytes each: slot (12 bits) with the call-type code (3/4/5) in the top nibble; the rest `ff` |
| tag 0x0B +0x740 | the same entries sorted by DMR ID |
| tags 0x44–0x48 | records: slot k on page 0x44 + (k−1)/170 at 24 × ((k−1) mod 170) |
| record +0x02 | name, 16 bytes |
| record +0x13 | u24 LE DMR ID (1–16776415, or 16777215 for All Call) |
| record +0x16 | call type code: 3 Private, 4 Group, 5 All Call |
| record +0x00, +0x12, +0x17 | 0 on the test radio (unknown) |

The index is rebuilt from the records whenever contacts change (CPS `0x474c00`); a rebuild
from the test radio's records reproduced its index page exactly.

*TX contact per channel* is **not** in the channel record: 2 bytes per channel on tags
0x42/0x43 (CPS `0x480050`). Channel n < 2048: page 0x42 at 2 × (n − 1); n ≥ 2048: page 0x43
at 2 × (n mod 2048); VFO A/B: page 0x43 at 0xFFA/0xFFC. First byte: high nibble = contact slot
bits 8–11, bit 0 = channel is digital; second byte = slot bits 0–7. 0 = none.

*RX group lists* (tag 0x0F; up to 32; CPS `0x477c50`–`0x478280`): bytes 0–3 = bitmap of
used groups; group n at 0x6D × n − 0x5C: 11-char name, 32 members as **u24 LE DMR IDs**
(not contact slots), 2 unknown bytes (and one before each record, `01` before group 1).

*Scan lists* (tag 0x11; up to 32; CPS `0x483050`–`0x484160`, export `0x4ad9c0`): byte 0 =
number of lists; list n at 0x39 × n − 0x38 (57 bytes):

| Offset | Contents |
|--------|----------|
| +0x00 | name, 11 bytes |
| +0x0B | number of members (max 16) |
| +0x0C | low nibble CTC scan mode (`[ScanCtcDcsMode]`), high nibble scan TX mode (`[ScanTxMode]`) |
| +0x0D | hang time (CPS shows (value) × 5 units) |
| +0x0E | priority types (nibbles) |
| +0x0F | u16 designed channel |
| +0x11, +0x13 | u16 priority channels 1 and 2 (encoding not fully known) |
| +0x15 | bit 1 talkback, bits 2–7 priority sweep time |
| +0x16, +0x17 | unknown |
| +0x18 | up to 16 × u16 channel numbers |

The members start at +0x18 itself. The CPS accessors seemed to start one slot later, but
the radio's own display settles it: factory Scan List 2 (`1 … 9`, count 9) shows channels
1–9, and Scan List 1 (count 16) shows 1–15 with 15 twice, exactly as stored. The driver keeps
unused list slots and the option bytes it doesn't know as they are.

### Radio settings (tag 0x04)

From the CPS option dialogs: each dialog fills a combo from a language section (or a number
range) and sets it from one accessor, and checkboxes carry control IDs whose labels are in
`[Resource]`. Stored values are the list positions unless noted. Decoding the test radio gave
plausible values (TOT 120 s, TBST 1750 Hz, "Welcome"/"DM-32UV").

| Offset | Field | Values |
|--------|-------|--------|
| 0x00 | power-on screen | Power On Picture, Custom Message, Battery Volt |
| 0x01, 0x0F | power-on text lines 1 and 2 | 14 chars each |
| 0x1D bit 0 | allow reset | |
| 0x1E | auto power off | Off, 30/60/120/240/480 min |
| 0x20 | tone bits: 7 radio silent, 6 key tone, 5 SMS alert, 4 group call, 3 private call, 2 call end, 1 talk permit, 0 startup sound | |
| 0x21 | 7 voice prompt, 6 battery low, 5–4 analog TX end tone (Off, Tone, BDC) | |
| 0x30 | backlight brightness | 1–6 |
| 0x31 | auto backlight duration | not decoded |
| 0x32 | menu exit time | Off, 5–60 s step 5 |
| 0x33 | 4 volume change prompt, 3 date format, 0 time display | |
| 0x34, 0x35, 0x38–0x3B | colours: call display, standby text, A/B channel name, A/B zone (`[DisplayColor]`: White, Black, Orange, Red, Yellow, Green, Cyan, Blue) | |
| 0x36, 0x37 | TX backlight delay (Off, 1–30), RX backlight delay (Always, 1–30) | |
| 0x40 | 6 GPS display format, 5–4 speed unit, 3–2 GPS mode (GPS, BDS, GPS+BDS), 1 distance unit, 0 GPS on | |
| 0x41 | time zone (UTC −12 … +13) | |
| 0x42 | GPS measure period, 5–255 s (stored − 5) | |
| 0x45 | 2–1 record type (RX, TX, both), 0 recording on | |
| 0x60 | 1 group call match, 0 private call match | |
| 0x61 | call hold time 1–60 s | |
| 0x62 | active wait time 300–4800 ms step 30 (stored = position + 1) | |
| 0x63 | active retries 1–8 (stored = position + 1) | |
| 0x64 | pre-carrier time 120–8640 ms step 120 | |
| 0x65 | 7 remote monitor decode, 6 radio disable decode, 5 radio check decode, 4 radio enable decode, 3 call alert decode, 2–1 SMS format (H/M/D-SMS), 0 missed call alert | |
| 0x66 | remote monitor time 10–120 s step 10 | |
| 0x67 | 7–6 name data format, 3 send TX name, 2 name display priority | |
| 0x80 | 7–6 dual watch (Single, Double Wait, Single Wait), 5 main line A/B, 4/3 B/A display mode, 2/1 B/A work mode (VFO/MR), 0 only channel mode | bits 1–5 are the radio's live display state: upload keeps the radio's own |
| 0x81 | dual watch hang time | 0–6500 ms step 500 |
| 0x85 | 3 forbid lock key, 2 side key lock, 1 knob lock, 0 keypad lock Manual/Auto | |
| 0x86 | auto keypad lock delay 5–60 s | |
| 0x87–0x92 | key functions (`[KeyFuncData]`, 43 entries), short/long pairs: SK1, SK2, TK, P1, P2, P3. From the CPS keys dialog: the accessor behind each control (0x430760) and the control's label (DDX 0x430600). Corrected 2026-09-27: driver versions before then had TK/SK1 and P1/P3 swapped | |
| 0x93 | long press time 1–5 | |
| 0xA0 | TOT | Off, 15–495 s step 5 |
| 0xA1 | TOT pre-alert | Off, 1–10 s |
| 0xA2 | VOX level | 1–5 |
| 0xA3 | VOX delay | stored value − 3 = list position; 0.3–5.0 s (units assumed) |
| 0xA4 | 7–4 power save (None, 1:1, 1:2, 1:4), 2 weather alarm, 1 language (Chinese/English), 0 disable LEDs | |
| 0xA5 | 7–4 TBST (1000/1450/1750/2100 Hz), 1–0 tail noise reduction (None, 120, 180, 55 Hz) | |
| 0xA6, 0xA7 | analog mic level (1–5); digital mic (Enhance MIC 1–3, not decoded) | |
| 0x301 | APRS scheduled send time: Off, 30–7200 s step 30 | |
| 0x302 | bit 0 fixed beacon | |
| 0x306, 0x30F | latitude: 9 ASCII chars as the CPS formats it (`0%.06f` below 10, `%.06f` below 90, else `90.000000`); N/S | |
| 0x310, 0x319 | longitude: 9 ASCII chars (`0%.06f` below 10, `%.06f` below 100, `%.05f` below 180, else `180.00000`); E/W | |
| 0x31E | 8 × u16 report channels (0 = current channel, else a digital channel number) | |
| 0x330 | repeater active delay: Off, 100–1000 ms step 100 | |
| 0x331 | bit 0 call type (Private, Group) | |
| 0x332 | upload number: u24 DMR ID (factory 456) | |
| 0x430–0x44A | passwords: 0x430 power-on flag, 0x431 power-on password (8), 0x439 write flag, 0x43A read flag, 0x43B write password (8), 0x443 read password (8); flags 0xA5 = set | not in the driver (kept as read) |
| 0x500–0x507 | menu items the radio shows (45 bits, labels from the CPS; 0x503 bits 0–1 unknown) | |

*Emergency systems* (tag 0x10, 8 × 20 bytes, 10-char names) and *encryption keys* (tag 0x10
from 0x301, 32 × 44 bytes: 10-char name, type byte, key) are chosen per channel, not edited
by the driver.

### Signalling: DTMF (tag 0x06), two-tone and five-tone (tag 0x03)

From the CPS dialogs (DTMF `0x421bc0`, two-tone `0x45a760`/`0x45ac30`/`0x45ae20`, five-tone
`0x4254c0`/`0x426240`/`0x426590`), their accessors and DDX control labels. Codes are one
digit value per byte, ended by 0xFF: DTMF uses 0–9, A–D = 10–13, `*` = 14, `#` = 15;
five-tone uses hex digits 0–F.

| Tag | Offset | Field |
|-----|--------|-------|
| 0x06 | 0x000 | 16 DTMF codes × 16 bytes |
| 0x06 | 0x100–0x104 | pre-carrier (300–5000 ms step 50, stored + 15), first digit time (100–1000 ms step 50), send duration and interval (80–2000 ms step 10), auto reset (1–255 s, stored as seconds) |
| 0x06 | 0x105 bit 0 | side tone |
| 0x06 | 0x106 | self ID, 3 digits, left-padded with 0 |
| 0x06 | 0x109–0x10E | group code (0xFF Off, else digit value A–#), interval sign (digit value), auto answer (Off, Alert Tone, Alert Tone And Ack), PTT ID pause (0 Off, else 5–75 s), —, dial code minimum duration (25–2500 ms step 25) |
| 0x06 | 0x110, 0x120, 0x130, 0x140 | PTT ID up (BOT), PTT ID down (EOT), stun code, kill code; 16 digits each |
| 0x06 | 0x1FF, 0x200 | DTMF (analog) contacts: count, then up to 64 × 0x20: 16-char name, 5 digits, 11 bytes (0 on the radio) |
| 0x06 | 0xA20 on | BDC1200 system and ID lists (not in the driver; kept) |
| 0x03 | 0x001 | two-tone encode count (1–32) |
| 0x03 | 0x030–0x036 | two-tone pre-carrier (0–5.0 s), first and second tone (0.5–4.0 s), long tone (0.5–10.0 s), interval (0–2.0 s), —, polite wait (0–5.0 s); all in 0.1 s |
| 0x03 | 0x037–0x03E | tones A–D, u16 in 0.1 Hz (the CPS allows 288.5–3106.8 Hz) |
| 0x03 | 0x03F, 0x040 | bit 0 idle ack, bit 1 side tone; auto reset (1–255 s) |
| 0x03 | 0x041 | 4 decode entries × 4 bytes: format code (0xFF None, 0x01 A-B … 0x3F Long D), call type, bit 0 reply |
| 0x03 | 0x220 | 32 encode entries × 0x28: UTF-16 name (16 chars), bit 0 single tone, byte, tone 1, tone 2 (u16, 0.1 Hz) |
| 0x03 | 0x730–0x73F | five-tone self ID (5 digits), decode standard, decode response (low nibble), pre-carrier (as DTMF), auto reset (stored s), delay after code (10–2550 ms, stored /10), PTT ID pause (as DTMF), first delay (stored /10), bit 0 side tone |
| 0x03 | 0x750 | 8 message codes × 16: function, response (low nibble), 12 digits |
| 0x03 | 0x7D0, 0x7F0 | PTT ID start (BOT) and end (EOT): 16 digits, standard, tone long (30–100 ms, stored /10) |
| 0x03 | 0x820 | 32 special calls × 0x30: type (0xFF Off, 0 ANI, 1 data), 5 digits, delimiter, standard, tone long, —, 16 data digits, 16-char name |

**Tones** (0x21, 0x23), two bytes; the second holds the flags:
`ff ff` = none. CTCSS: tenths of a Hz as 4 BCD digits, little-endian
(88.5 Hz → `85 08`). DCS: byte 1 = `0x80` (normal) or `0xC0` (inverted) OR'd with the
first octal digit, byte 0 = the other two digits (D023N → `23 80`, D754I → `54 c7`).

### Keypad tests

Change one thing on the radio, read, `tools/dm32uv_diff.py old new`.

| # | Change | Result |
|---|--------|--------|
| 1 | TX power high → low (mode not recorded, probably VFO A) | VFO A `+18`: `04` → `00`. Tag 04 `+080`: `9e` → `9c`. Both pages moved; the old copies and 2 blank pages became tag 00. |
| 2 | Same setting back to high | VFO A `+18`: `00` → `04` only. So tag 04 `+080` in test 1 was something else, not power. |
| 3 | Renamed "channel 5" to `hello world`; appended ` analog` to channel 6's name | Ch 6 name → `Channel 6 analog`. **Record 13** (old name `Channel 13`) → `hello world`, not record 5, which is unchanged. Tag 5c header u16 at +3: 13 → 6 (line B's current channel?). Tag 04 `+080`: `9c` → `be`. VFO A frequency 434.33833 → 434.33583. Test 4 explains it: the rename went to the channel selected on the other display line (B, on channel 13). |
| 4 | Controlled: only the upper line active, channel mode, Channel 3 renamed `TEST3` | Record 3 name → `TEST3`: **the radio's channel number is the record number**. Tag 5c +1: 6 → 3 (line A's current channel). Tag 04 `+080`: `be` → `9e`. |

**Tag 04 byte 0x80** (seen in tests 1, 3, 4: `9e` → `9c` → `be` → `9e`) looks like the display state,
not a setting. Bit 5 is probably the active line (1 = B, set when line B was edited in test 3)
and bit 1 probably line A's channel/frequency mode (cleared when power was changed in VFO mode
in test 1). To be checked against the CPS tag 04 accessors.

### Zones (tags 0x5C–0x64)

Confirmed by the CPS zone accessors (`0x482740`–`0x482cd0`, buffer `DAT_0150c13c`).
The 9 pages form one buffer, page p = tag 0x5C + p. Zone z (1–250) is at page `(z−1)/28`,
offset `0x91 × ((z−1) mod 28)`, plus 0x10 on page 0 only (the header), so 28 zones per
page. Limits in the CPS: 250 zones (`0xfa`), 64 members per zone (`0x40`).

| Offset | Contents |
|--------|----------|
| header +0 | u8 zone count (2 on the test radio) |
| header +1, +3 | u8 current **position within the zone** for display lines A and B (1–64) |
| header +5, +7 | u8 current **zone** for lines A and B (1–250) |
| header +2, +4, +6 | 0 (unknown) |
| zone +0x00 | name, 16 bytes, NUL-padded then `ff` |
| zone +0x10 | u8 member count |
| zone +0x11 | 64 × u16 LE channel numbers (1-based, zero-filled) |

The radio shows only channels that are in a zone, in the zone's member order. The driver
exposes zones as CHIRP banks (a channel can be in several zones), plus one spare "New zone"
(count + 1): adding a channel to it creates that zone, keeping zone numbers gap-free, and a
last zone left empty is removed. A zone past 28 needs the next zone page (tag 0x5D…),
which upload places on a free page if the radio has none. When uploading the zone
page it keeps the radio's current header bytes 1–7 (they change whenever someone browses)
and resets a pointer that would fall outside its zone.

## Radio firmware (v1.01.048)

From a static look at the radio's own firmware, `DM32_L01_048_20250821.bin`
from Baofeng's firmware download. The radio tested here runs .047. The .048 changelog says
"Expand to 150K Contacts, cancel the recording"; a comparison with a real .048 radio (see
"Firmware .048 compared with .047" above) shows that only the digital contact database
area changed, which the driver doesn't touch. The codeplug layout is the same. Keeping
the radio on .047 is still the choice here, because there is no .047 file to flash back
(see "Firmware upgrade protocol"). How to reproduce the disassembly: `re/fw_disasm.sh`
(needs csky-elf binutils, see the script).

- The file is a 256-byte header (`BFUV32-V2`) followed by **unencrypted C-SKY
  (CK80x) code** linked at `0x300c000`, so there is a bootloader below. Start-up copies
  `0x306fdc0` → RAM `0x18000800` and `0x30bd768` → RAM `0x10000–0x2f098`, which holds the
  SPI flash routines.
- Command strings are in a table at `0x30ad6b4`: `PROGRAM`, `PSEARCH`, `DP570UV`
  (the model ID sent in the PSEARCH reply), `PASSSTA`, `PASWORD`, `PCTESTM`,
  `RTCITEM`, `DEL-RCD`, `IDCHECK`, `SYSINFO`, `588999`. The CPS doesn't use `RTCITEM`,
  `DEL-RCD` or `IDCHECK`.
- **Top-level loop** `0x302a324`: waits for 7-byte commands. `PROGRAM` sets a
  "programming" flag and runs the session `0x3029438`. When the session returns,
  `0x305d8f4` writes to the system-control block at `0x11000000`, then the flag is
  cleared. On the radio this is **not a visible reboot**: after a read the radio simply
  goes back to its home screen by itself (checked 2026-09-26). So no power cycle is needed
  after a session.
- **Session** `0x3029438`: sends `06`, expects `02` and replies with 8 bytes of
  `ff` (the identification reply always seen), expects `06` and replies `06`, then loops:
  - Reads a 6-byte frame `cmd a0 a1 a2 l0 l1` (address 24-bit LE, length 16-bit LE),
    waiting up to 2 s. **If nothing arrives within 2 s the session ends** and the radio
    returns to normal, so no end-of-session command is needed. (`V` queries are 5 bytes.)
  - `R`: reads flash and replies with the *received* frame, first byte changed to `W`,
    plus data. So a reply header echoes exactly what the radio received.
  - `W`: receives `length` data bytes (2 s timeout; if fewer arrive, no reply). If the
    address is 4 KB-aligned it **erases that sector** first. It then programs the data
    (`0x2baac`); **if the data crosses into the next sector, that sector is erased
    too**. Replies `06`. No checksum and no read-back.
  - `D`: another read (reply `W`), from a different store (maybe recordings), in
    512-byte units.
  - `G` / `S`: read / write a *different* memory (reply `S` / ack `06`), with the same
    erase-on-aligned-address rule. The CPS sends `S 00 00 00 00 01` + 256 bytes when
    writing, which erases that memory's first sector. **Our tools must never send `S`.**

**Rules for writing, from the above:** only `W` frames of exactly 0x1000 bytes at a
4 KB-aligned address (never cross a sector; never write tags 0x02/0x69); read every
written page back and compare; keep the tag byte at 0xFFF; stop sending when done
and let the 2 s timeout end the session.

**First write (2026-09-26).** Before it, a backup of all 200 codeplug pages
(`dm32uv_read.py --all-pages`). Then `dm32uv_write.py --noop 13`: one `W 00 50 01 00 10` + 4096
bytes, rewriting page 0x015000 (tag 0x13) with its own contents. The radio answered `06`
at once, the read-back matched first time, and the tags were unchanged. A full re-read afterwards
was byte for byte identical to the backup in all 200 pages. So `W` behaves as the firmware
analysis says, and the page stays where it was.

**First real edit (2026-09-26).** Driver download, channel 3 renamed `TEST3` → `WRITE OK`,
driver `do_upload`: it wrote one page (`W 00 70 07 00 10`, tag 0x12 in place), got `06`,
verified, and skipped every other page as unchanged. A full re-read against the backup: one page
differs, in exactly 7 bytes (0x070–0x077, the name). The radio showed `WRITE OK` straight away.

**Adding a channel (2026-09-26).** Channel 26 uploaded from the CHIRP GUI: the channel
count in the page 0x12 header went 25 → 26 and the record was written in place; a re-read
matched. But the radio only lists channels through **zones** (tag 0x5C), and channel 26
is in none (zone 1 = 1–16, zone 2 = 17–25), so it does not appear on the radio. A new
channel needs adding to a zone as well.

**Zone edit from the CHIRP GUI (2026-09-26).** Channel 6 added to zone "Func Demo" in the
Banks tab and uploaded. A re-read showed only the zone page changed: zone 2 count 9 → 10,
member 10 = 6. (The same diff also held channel 26 added to zone 1 earlier on the keypad,
the line B position, and a page move from that keypad edit.) No channel page changed.

**Tones and power from CHIRP (2026-09-26).** Channel 10 TX tone 88.5 Hz, channel 11 DCS 023N
both ways, channel 12 power Low, uploaded from the GUI. The diff was exactly the predicted
bytes (ch 10 `+23` `85 08`; ch 11 `+21..+24` `23 80 23 80`; ch 12 `+18` `04` → `00`), in one
page written in place, and the radio showed all three as set.

**DMR fields from CHIRP (2026-09-26).** Channel 1: TX contact "Radio 2", RX group list 2,
time slot 2, uploaded from the GUI. The diff was exactly `+1d` `01` → `11`, `+1f` `01` → `02`, `+2b`
`00` → `02`, in place, and the radio showed all three. (The same diff held a VFO B change and a
line-B position change made on the radio, and the G block had changed too.)

**Zone created from CHIRP (2026-09-26).** Channel 1 put in the spare "New zone" bank and
uploaded: zone count 2 → 3, zone 3 = "Zone 3" with channel 1; the radio lists it (select it
with the zone switch). The same re-read showed the radio had **cleaned up its stale pages**:
pages in use fell from 191 to 71, and the zone page had moved. The radio reclaims stale
(tag 0x00) pages by itself at some point.

**Contact edit from CHIRP (2026-09-27).** Contact 1 renamed "Contacts 1" (ID 1) → "TG 91" (ID 91)
on the Settings tab and uploaded. The diff showed exactly the record's name and ID bytes on page 0x44
and the rebuilt index on page 0x0B (name- and ID-sorted lists re-ordered). The radio's index is
byte-identical to the CPS rebuild algorithm, and the radio showed "TG 91" as the contact and as
channel 1's TX contact.

**RX group and radio ID from CHIRP (2026-09-27).** RX group 1's members edited by name
(`TG 91, Contacts 2, …`) and channel 1's radio ID set to Default, uploaded from the GUI. The
diff was exactly member 1 of group 1 (`01` → `5b`, ID 91) and channel 1 `+2b` `02` → `00`,
and the radio showed both.

**Channel options from CHIRP (2026-09-27).** Channel 10: VOX on, PTT ID BOT, TX admit Channel
Idle; channel 2: TX admit Color Code Idle. The diff was exactly ch 2 `+1a` `00` → `20`, ch 10
`+1a` `00` → `10`, `+25` `00` → `10`, `+29` `00` → `04`, and the radio showed all four.

**Deleted channel and gap (2026-09-27).** Channel 20 deleted in CHIRP (not "shift up") and channel
30 added past the count (26), then channel 30 added to a zone. On the radio: record 20 all `ff`,
removed from its zone and its TX contact cleared; records 27–29 erased (they held factory template
data, 400.000 MHz, which would otherwise have become phantom channels); count 30; the zone lists
channel 30 last. So an erased record inside 1..count is tolerated as long as nothing refers to it.
**Scan lists** can still refer to a deleted channel; handled with roadmap item 6.

**Link direction.** Checking the echoed `R` headers in six full-read logs (5496
requests, 32976 bytes sent): 19 corrupted reply headers, every one a bit-7 flip with the data
from the right page. **No request ever arrived corrupted.** So the PC→radio direction
is much cleaner than radio→PC (below about 1e-4 per byte, against about 1.5e-3). The
bit-7 fault is on the cable's receive side.

## Vendor error handling

Checked in `DMR CPS.exe` (the serial helpers `0x48f400`/`0x48f570`/`0x48f630` and
the worker `0x44a210`) and in `PowerOnPicture.exe`, the vendor's separate
power-on picture uploader (file `7` in the installer), which has its own copy
of the serial code. **Neither program does any error detection or recovery
beyond checking reply lengths and first bytes:**

- The receive helper calls `ClearCommError` before every `ReadFile` but
  ignores the error flags it returns (framing, parity and overrun errors).
- There are no checksums anywhere in the wire protocol, in either direction.
- A block read is accepted if the reply is 0x1006 bytes and starts with `'W'`.
  The echoed address and length are not compared with the request.
- Only `PSEARCH` is retried (5 times). Any other bad or missing reply
  ends the session with an error message (`IDS_COMM_FAIL` in the
  uploader, a status code in the CPS). The user has to start again.
- Writes are acknowledged by a single `0x06` per 4 KB block. There is no read-back
  check. The radio can't detect corrupted data either, since there's nothing to check it against.

So the vendor tools rely on a clean link. With the bit errors seen here,
the CPS would silently accept corrupted reads and write corrupted data.
A CHIRP driver has to add its own checks: read each block until
two copies agree, and after a write, read the block back and compare.

## Firmware upgrade protocol (CPS Tool → Firmware Upgrade, `0x423a60`)

Static analysis of the CPS only (2026-10-29). **Nothing here has been sent to a radio.** The
radio-side receiver is the bootloader, which is not in the firmware file (see "What this does
not tell us"). Written up so the flashing process could be rebuilt as a standalone tool; CHIRP
does not flash firmware.

**Firmware file** (`DM32_L01_048_20250821.bin`, 860,416 bytes): a 256-byte header followed by
the raw application image (860,160 bytes, linked at `0x300c000`). The header is `0xFF`-filled
except for the model ID string at offset 0 (`BFUV32-V2`) and `END` at `0xFD..0xFF`. No
checksum, no size field. The upgrade dialog's hidden "Generate Bin" button (`0x4236f0`, shown
only in a factory mode) builds exactly this from a typed ID and a raw image. The header is not
sent to the radio. (The CPS's own file check tests `E`, `N`, `D` with OR, so one matching byte
passes.)

**Link:** the same port and `[com] baudrate` from `cps.ini` as the codeplug protocol (115200
8N1, `0x48f400`), 10 ms pause before every send. The radio must be in upgrade mode first (SK1 +
PTT held while switching on, green LED, then plug in the cable); the application firmware is not
running then, so none of the codeplug commands apply.

**Transfer** (PC → radio / radio → PC; timeouts are the CPS's receive timeouts; any other reply
makes the CPS abort with a message box, there are no retries):

| Step | PC sends | Radio answers | Timeout | Notes |
|---|---|---|---|---|
| 1 | `R` | `06` | 0.5 s | |
| 2 | `M 00 00 00 01` | `M xx len`; PC sends `06`; radio sends `len` bytes | 0.5 s each | The `len` bytes must equal the first `len` bytes of the file header (the model ID), else "model error". |
| 3 | `E 00 00 00 00` | `06` | 0.5 s | Presumably erase; the parameters are constants in the CPS. |
| 4 | `1` | `C` | 5 s | |
| 5 | `01` (SOH) | `C` | 5 s | |
| 6 | YMODEM block 0, 132 bytes: `00 FF`, file name, `00`, image size in decimal (`%d`), zero padding to 128 data bytes, CRC | `06 43` | 20 s | Size = file length − 256. The long wait suggests the erase happens here, once the size is known. |
| 7a | per block: `02` (STX, 1 KB) or `01` (SOH, 128 B) | `C` | 10 s | 1 KB blocks while ≥ 1 KB remains, then 128-byte blocks; the last one padded with `0x1A`. |
| 7b | block body: `seq`, `~seq`, data, `CRC_hi`, `CRC_lo` (1028 or 132 bytes) | `06` | 10 s | `seq` starts at 1 and wraps 255 → 0. |
| 8 | `04` (EOT) | 1 byte, ignored | 5 s | The CPS then closes the port and reports "Upgrade successful!". |

The CRC is CRC-16/XMODEM (`0x424ea0`: polynomial 0x1021, init 0, no reflection, no final
XOR), big-endian, over the data bytes only (128 or 1024). Compared with standard YMODEM: the
custom steps 1–4, the SOH/STX byte sent alone and answered with `C` before the body, and no
closing empty block 0, NAK handling or retransmission.

**What this does not tell us**

- The receiver is the bootloader at `0x3000000..0x300bfff`, which is not in the firmware file,
  so its command set is unknown: whether `M` and `E` take other parameters, whether there is a
  read-back command (the CPS uses none, so the radio's .047 cannot be saved this way as far as
  the CPS shows), and how the image is checked beyond the per-block CRC.
- The stream carries no addresses; the bootloader decides where it writes. The image is linked
  above the bootloader and the file contains no bootloader, so a normal upgrade should leave the
  bootloader intact and a failed transfer should be recoverable by entering upgrade mode again.
  That is an inference from the layout, not something verified.
- "Allow Reset" (settings byte 0x1D bit 0, `allow_reset` in the driver) must be on before the
  upgrade so the radio accepts the SK1 + SK2 reset afterwards, per Baofeng's guide. What the
  firmware does with the bit was not analysed.

**Rebuilding it:** a sender is small (pyserial and the table above). The risks: a wrong or
interrupted image leaves the radio without a working application until a flash succeeds; a
sender cannot be tested without flashing a radio; and there is no .047 file to flash back.

## Other routines in the CPS (not needed for CHIRP)

| Function | Purpose |
|----------|---------|
| `0x45e530` / `0x45f6b0` / `0x45fff0` | Factory calibration page (tag 0x02 at page end in its own region) plus `AT+...` alignment. **Never write.** |
| `0x44da70`, `0x450e10`, `0x452b20` | Call recording list and playback |
| `0x423a60` | Firmware upgrade; see "Firmware upgrade protocol" above |
| `0x41d280`, `0x41fea0`, `0x42c9a0` | Voice prompt, font and boot image upload |
| `0x405490`, `0x405a30`, … | Factory test mode (`PCTESTM`, `AT+...`) |

## Open questions

- Meanings of V2, V13 and the `V 40 0D` blob.
- Cause of the bit-7 receive errors, and why the radio stops answering after some sessions.
- What V6, V7, V8, V9 and V14 hold (voice prompts, fonts, boot image, recordings?).
- Reply to `02` after `PROGRAM`, and everything from step 6 on (not yet tried on a real radio).
- ~~End-of-session command~~: none needed. The firmware ends the session after 2 s idle and the radio returns to its home screen by itself (confirmed on the radio).
- Which tag is which: diff captures after changing one setting at a time.
- The CPS `.enc` file format (only needed to import CPS files).
