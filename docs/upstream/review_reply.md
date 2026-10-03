# Replies to the review of PR #1656

Paste each reply under the matching review comment.

---

## 1–2. Tone masking (`_decode_tone`)

Done in aa53d01. The tone is now a struct in the memory format:

```
struct tone {
  lbcd low;
  u8 dcs:1, inverted:1, hundreds:2, tens:4;
};
```

Decoding and encoding just read and set those fields; the masking and the string
round-trips are gone. I checked that the new code writes the same bytes as the old for
every CTCSS tone and every DCS code in both polarities.

---

## 3. Zones as banks

Happy to explain. Most DMR handhelds (AnyTone, TYT, Radioddity, and this Baofeng) work
like this:

- **Channels** are a flat list of up to 4000. Each is an ordinary channel: RX/TX
  frequency, power, mode. A DMR channel adds color code, timeslot, the TX contact
  (the talkgroup or person to call) and an RX group list (which talkgroups to hear). So
  "which frequency" is still per channel; talkgroups ride on top via contacts.
- **Zones** are named, ordered groups of up to 64 channels (up to 250 zones). The
  channel knob only steps through the current zone, and you switch zones from the menu.
  **A channel that isn't in any zone can't be selected on the radio at all.** A channel
  can be in several zones.

Zones are only the user's own grouping ("Local repeaters", "Hotspot", "FRS/GMRS"). They
aren't tied to a network or trunking system. That's why I used CHIRP banks: a zone is a
named list of existing memories, a memory can be in several, and the order matters. In
the Banks tab, a spare "New zone" column creates the next zone, because the radio keeps
zones numbered 1..count without gaps. Reordering channels within a zone, and deleting or
reordering zones, are on the Settings tab.

---

## 4. `MEM_FORMAT` built at import time

Yes, that's intentional, and the format really is static. The radio stores its codeplug
in 4 KB flash pages that it moves around for wear levelling; the last byte of each page is
a tag saying what it holds. At download the driver scans the tags and copies each page
into a fixed slot for that tag (one slot per tag, in `IMAGE_TAGS` order), so the image
CHIRP saves always has the same layout regardless of where the radio keeps the pages.
Upload does the reverse. `_mem_format()` only computes the slot offsets from
`IMAGE_TAGS` instead of hard-coding about 60 `#seekto` addresses. I can write it out as a
literal string if you'd prefer that.

---

## 5. Link reliability

You were right: the link shouldn't need that, and it doesn't. It was the cable. That's just
what you said about testing more than one cable before blaming the radio.

The errors were always bit 7 flipping 0 → 1, and only on bytes from the radio, which looked
like a clock mismatch. So I tried a second cable on the same radio. The original was the
bundled CH340 cable (1a86:7523); the new one has an FTDI FT231X:

| Cable | Data | Errors |
|-------|------|--------|
| CH340 | info queries, two sessions | 1 byte in 700, and 1 in 47 |
| FTDI | info queries, 3,200 bytes | 0 |
| FTDI | full read, 1,181 commands / 2.16 MB | 0 |

A download with the simplified driver (one read per block) then matched the old three-copy
dump in every page.

So in aace83e the compensation is gone:

- Each block is read once. A reply is only requested again if it's short or has the
  wrong header, which a sound USB link can still produce now and then.
- No bit-7 merging, no majority voting, and reply markers are checked exactly.
- What a bad cable produces is treated as an error, not used: a page tag with bit 7 set
  (real tags stop at 0x7c) or a non-ASCII model ID. That way a bad link can't make upload
  think a page is missing.
- A CH340 cable (USB 1a86:7523/5523) gets a log warning. If a transfer then fails, the
  error message suggests an FTDI or CP2102 cable, since the CH340 cable is what comes in
  the box with this radio.
- Writes are still read back once and rewritten once if they don't match. If that fails
  too, the upload stops with a message pointing at CHIRP's pre-upload backup.

Downloads also got faster (about 70 s down to 30 s).
