**Where:** comment on the existing issue https://chirpmyradio.com/issues/11840 ("New Model: Baofeng DM-UV32"), after the pull request is open.

---

I've written a driver for this radio (the Baofeng DM-32UV; it identifies itself as `DP570UV`) and opened a pull request: PR_LINK

It supports download and upload of channels 1–4000 (name, frequencies, duplex, power, FM/NFM/DMR, CTCSS/DCS), the main DMR channel fields (color code, time slot, TX contact, RX group list, encryption key) and zones as banks, including creating a new zone. Radio-wide settings and editing the contact lists aren't supported yet.

I tested it on a real radio with firmware DM32.01.01.047. Anyone with a different firmware version who can try it is very welcome to: in CHIRP, use Help → Developer Mode, then File → Load Module with the driver file from the pull request. Please download and save a backup image before uploading anything.
