# Replies to the second review round of PR #1656 (2026-10-03)

Each section is a reply under the review comment named in its heading.

---

## Tones: "isn't this just one of the `kenwood_tone` variants?" (thread 4116254346)

It is. With `dcs_base=0x8000, pol_mask=0x4000, tone_init=0xFFFF, tone_flag=0x0000` and BCD
for both CTCSS and DCS (`dcs_enc_base=16, tone_enc_base=16`), `KenwoodToneModel` produces
exactly the bytes this radio uses for all 258 CTCSS tones and DCS codes (both polarities),
including `ff ff` for no tone. Switched to it in e8f1458, so the driver's own tone code is
gone and the fields are plain `ul16 rxtone/txtone`.

---

## Static memory format (thread 4116270468)

Understood and done in e8f1458: `MEM_FORMAT` is now one static string with the slot addresses
written out, like the other drivers. The layout is unchanged (the test image is
byte-identical), and a test checks the addresses still line up with the slots download
fills.

---

## Retries: "are you ever seeing this happen?" (thread 4174619799)

No. With the new cable (a BTECH PC03, which has an FTDI FT231X), a full read had 0 of
1,125 block reads that needed a retry.

So in e8f1458 the recovery code is gone:

- Every block and info query is read once; any bad or missing reply stops the transfer.
- Each page write is read back once. A missing ACK or a mismatch stops the upload, with no
  rewrite and no reconnect.

The one thing I kept is the handshake: `PSEARCH` is still sent up to 5 times. In 2 of 8
logged sessions the radio ignored the first one or two and answered the next, and the
vendor CPS also sends it up to 5 times. Happy to drop that too if you'd rather.

On refusing the broken cable, I'd like your preference before I do it, since it touches the
port inspection you flagged. I've only tested one CH340 cable, and a CH340 cable is what
ships in the box with this radio (and many others). So:

1. **Refuse any CH340 by USB ID** before transferring, with the "this cable is known to be
   broken for this radio, get a new one" message. That catches every bad session, but it
   also blocks CH340 cables that may work fine, and it keeps the port inspection.
2. **No port inspection:** fail with that message only when the data is visibly garbled (a
   page tag with bit 7 set, or a non-ASCII model ID). The catch is that only about 180 bytes
   per session can be sanity-checked. At the bad cable's worse rate (1 byte in 47) that
   catches about 98% of sessions, but at its better rate (1 in 700) only about 1 in 4; the
   rest would get corrupted data without an error.

Right now it does a mix of the two: a log warning for a CH340, and the error (with cable
advice) when the data is visibly garbled. Which way would you like it?
