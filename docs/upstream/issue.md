**Tracker:** CHIRP → New issue → **Tracker: New Model**
**Subject:** Baofeng DM-32UV

---

Request for support for the Baofeng DM-32UV, a dual-band (VHF/UHF) DMR Tier II handheld. It identifies itself as `DP570UV` on the programming cable. The vendor programming software is "DMR CPS" v1.60. I tested with radio firmware DM32.01.01.047.

I have written a driver and will open a pull request referencing this issue. It supports:

- download and upload of channels 1–4000: name, RX/TX frequency, duplex, power (Low/Middle/High), FM/NFM/DMR, CTCSS/DCS
- DMR channel fields: color code, time slot, TX contact, RX group list, encryption key (chosen by name from the radio's lists)
- zones as CHIRP banks, including creating a new zone

The following are not supported yet: radio-wide settings, and editing the contact, RX group and key lists themselves.

It was tested on a real radio: downloads match an independent reader byte for byte, and uploads of each supported field were confirmed by reading the radio back and on its display.
