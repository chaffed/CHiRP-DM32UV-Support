**Title:** dm32uv: Add Baofeng DM-32UV driver

---

Adds a driver for the Baofeng DM-32UV DMR handheld. Fixes #NNNN.

**What it supports**
- Download and upload, channels 1–4000: name, frequencies, duplex, 3 power levels, FM/NFM/DMR, CTCSS/DCS.
- Per-channel extras: channel type, color code, time slot, TX contact / RX group list / encryption key (chosen by name from the radio's lists), squelch, forbid TX, talkaround.
- Zones as banks. The model offers one spare "New zone" bank; adding a channel to it creates the next zone.

**Radio specifics a reviewer may want to know**
- **Codeplug storage.** The codeplug is 4 KB flash pages tagged by content (last byte) and moved around by wear levelling. The driver scans the tags and keeps a fixed logical image, one 4 KB slot per tag, so the image does not depend on where the pages happen to be.
- **Unreliable link.** On the tested cable about 1 received byte in 1000 arrives with bit 7 set, and the protocol has no checksums. The vendor CPS doesn't check anything either. Every block is read three times and merged byte by byte, so downloads are reproducible.
- **Upload safety.** The radio firmware erases a 4 KB sector on a page-aligned write, and also erases the next sector when a write crosses a boundary. Upload therefore:
  - writes only whole aligned pages;
  - writes only channel and zone pages that differ from the radio;
  - reads every page back and retries on mismatch;
  - never writes pages that look like calibration.

**Testing**
- On a real radio (firmware DM32.01.01.047): downloads were byte-identical to an independent reader. Uploads of names, tones, power, DMR contact / RX group / time slot, zone membership and a new zone were each verified by a full re-read and on the radio's display.
- Outside CHIRP, the upload logic was tested against a simulator of the radio firmware's programming protocol, including a noisy link and injected write errors.
- `tests/images/Baofeng_DM-32UV.img` is synthetic (generated; no real user data).
- `tox` style, unit and driver jobs pass locally.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
