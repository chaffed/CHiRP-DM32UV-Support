# Baofeng DM-32UV programming protocol

Reverse engineered from `DMR CPS.exe` v1.60 (2026-06-08) with Ghidra.
Addresses such as `0x44a210` refer to that binary. Most of this comes from
static analysis. Steps 1–5 of the session (handshake and V queries) were
checked against a real radio on 2026-09-26 (firmware `DM32.01.01.047`); see
"Observed on a real radio" below. Everything from step 6 on is still unverified.

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
| 2 | `PASSSTA` | 3 bytes: `'P' rd wr` | `rd == 0xA5` means a read password is set; `wr == 0xA5` means a write password is set. |
| 2a | `PASWORD` | `0x06` | Only when the flag for the current direction is `0xA5`. |
| 2b | `'P' ('R'\|'W') pw[8]` (10 bytes) | 1 byte | Password is ASCII, padded with 0xFF, NUL-terminated if shorter than 8. |
| 3 | `SYSINFO` | 1 byte (`0x06`) | |
| 4 | `V 00 00 40 0D` | `'V' x n` then `n` bytes | Radio info blob |
| 5 | `V 00 00 00 i` for i = 1..16, except 12 | `'V' x n` then `n` bytes | See the V table below |
| 6r | read: `G 00 00 00 00 01` | 0x106 bytes: `'S'` + 5-byte header + 256 data bytes | 256-byte settings block |
| 6w | write: `S 00 00 00 00 01` + 256 bytes | `0x06` (5 s timeout) | Only sent if that block was loaded |
| 7 | `FF FF FF FF 0C` | — | Same bytes as CHIRP `baofeng_uv17` `_magics2` |
| 8 | `PROGRAM` | `0x06` | Radio enters programming mode |
| 9 | `02` | 8 bytes | Identification |
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
| 9 | Flash range | `0x6dc000 – 0xffffff` |
| 10 | Flash range of the **codeplug page area** | `0x001000 – 0x0c8fff` (200 pages) |
| 11 | Version string | `C1.00.01.001` |
| 13 | ? | empty (`n = 0`) |
| 14 | Flash range | `0x150000 – 0x175fff` |
| 15 | Flash range of the **digital contacts area** | `0x278000 – 0x6dbfff` |
| 16 | `u24`. The CPS analysis suggested contacts data length in bytes (44 = 0x2C bytes per contact). | `0x00c350` = 50000. Not a multiple of 44, so it is more likely a contact count limit. |

The flash ranges fit together without gaps from 0x001000 to 0xffffff, except
for 0x14a000–0x14ffff, 0x176000–0x17ffff and 0x265000–0x277fff.

Real `V 00 00 40 0D` payload (64 bytes): `03 4e 2d`, then zeros, with `3f` at
offset 0x20. Meaning unknown. (Stray `80` bytes seen at other offsets were link
bit errors.)

### Serial link reliability (2026-09-26, CH340 cable, Linux)

The link is **not clean**. Received bytes sometimes have bit 7 flipped from 0
to 1 (about 1 byte in 1000; 4 flips in 3400 bytes). All errors observed so far
are this one kind. That fits a small baud rate mismatch (the radio's UART
slightly fast), but a bad cable or plug contact is not ruled out. The protocol has no
known checksum, so:

- Reads must be checked (read twice and compare, or read until two copies agree).
- **Writes must not be attempted until the link is reliable**, because a
  corrupted byte in a `W` block would go straight into the codeplug.

The error rate varies between sessions: 0 in 1700 bytes, 3 in 3400, 16 in 8500.
Reseating the plug and power cycling made no difference.

Other baud rates are worse, not better. The CH340's nearest rates are 116505
(+1.1%), 117647 and 114286: at 116505 the handshake is already garbled, and
at 117647 about half the replies are missing. So the errors at 115200 are
probably not a steady baud mismatch. Noise, or timing jitter on the radio side,
are still candidates.

**The radio stops answering and needs a power cycle** after it receives garbled
commands (wrong baud rate). It also happened once after back-to-back sessions
at 115200. Waiting 5 s between sessions has been enough so far.
**Do not send it anything at a baud rate other than 115200.**

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
| 0x02, 0x03, 0x04, 0x06, 0x0A, 0x0B, 0x0F, 0x10, 0x11, 0x65, 0x66, 0x67 | 1 each | separate buffers | settings, zones, scan lists, etc. |
| 0x12 – 0x41 | 48 | one 192 KB buffer | probably channels (for example 4000 × 48 B) |
| 0x42 – 0x43 | 2 | | |
| 0x44 – 0x48 | 5 | continues the tag 0x0B buffer at +0x1000 | |
| 0x5C – 0x64 | 9 | | |

Digital contacts are stored **linearly** from `V15.start`, in 44-byte records, and read or written as 4 KB blocks. First `R start 04 00` returns 4 bytes of length information.

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

## Other routines in the CPS (not needed for CHIRP)

| Function | Purpose |
|----------|---------|
| `0x45e530` / `0x45f6b0` / `0x45fff0` | Factory calibration page (tag 0x02 at page end in its own region) plus `AT+...` alignment. **Never write.** |
| `0x44da70`, `0x450e10`, `0x452b20` | Call recording list and playback |
| `0x423a60` | Firmware upgrade (bootloader protocol) |
| `0x41d280`, `0x41fea0`, `0x42c9a0` | Voice prompt, font and boot image upload |
| `0x405490`, `0x405a30`, … | Factory test mode (`PCTESTM`, `AT+...`) |

## Open questions

- Meanings of V2, V13 and the `V 40 0D` blob.
- Cause of the bit-7 receive errors, and why the radio stops answering after some sessions.
- What V6, V7, V8, V9 and V14 hold (voice prompts, fonts, boot image, recordings?).
- Reply to `02` after `PROGRAM`, and everything from step 6 on (not yet tried on a real radio).
- Whether the radio needs an explicit end-of-session command. The CPS just closes the port.
- Which tag is which: diff captures after changing one setting at a time.
- The CPS `.enc` file format (only needed to import CPS files).
