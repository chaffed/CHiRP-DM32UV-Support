# Replies to the review of PR #1656

Paste each reply under the matching review comment.

---

## 1–2. Tone masking (`_decode_tone`)

Done in e5e59e3. The tone is now a struct in the memory format:

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

You're right to be suspicious, and I agree it isn't good enough to ship as it is. Here's
what I know and what I'm doing about it.

**What we measured.** On one radio and one cable (the CH340 cable that comes with it,
Linux `ch341`), about 1 received byte in 700 was wrong. Every error had the same shape:

- only bytes from the radio to the PC; the radio's echoed command headers show the
  PC-to-radio direction arrived intact;
- only bit 7;
- only 0 → 1.

Bit 7 is the last data bit before the stop bit, and the stop bit is always 1. So the
receiver is sometimes sampling the stop bit instead of bit 7. That's the signature of a
baud-rate mismatch, with the radio's UART running a bit fast relative to 115200, rather
than random noise. The vendor programming software uses the same cable with no error
checking at all, so its users would get silent corruption.

**Next step.** Find the real rate: read the same blocks at a few rates close to 115200
and see where the error rate drops to zero. If one rate fixes it, the driver will use it
and the three-way read merge can go.

**Writes.** Nothing is ever written blind:

- only whole, aligned 4 KB pages go out;
- a page is only written if it differs from what's on the radio;
- each page is read back after writing;
- pages that look like calibration are never touched.

Even so, you're right that if a page still doesn't verify after the retries, the upload
stops and that page may be bad until the next upload. (CHIRP's pre-upload backup, or a
repeat upload, restores it.) I'm also looking at a safer write order the firmware seems
to allow: write the new copy to a free page, verify it, and only then retire the old one.
A failure would then leave the old page in place.

I'll report back with the measurements before asking you to look at this part again.
