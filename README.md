# CHiRP DM-32UV Support

A [CHIRP](https://chirpmyradio.com) driver for the **Baofeng DM-32UV** DMR handheld, plus
the tools and notes used to build it.

> **Status:** download, upload, zones and the main DMR channel fields work, tested on a real
> radio (firmware DM32.01.01.047). The driver has been submitted to CHIRP as
> [pull request #1656](https://github.com/kk7ds/chirp/pull/1656)
> (issue [#11840](https://chirpmyradio.com/issues/11840)). Until it is merged, you can load
> it into CHIRP yourself as described below.

## Use it in CHIRP now

You need CHIRP (the current "next" build from
[chirpmyradio.com](https://chirpmyradio.com/projects/chirp/wiki/Download)) and the
programming cable that came with the radio.

1. **Download the driver file**
   [`baofeng_dm32uv.py`](https://raw.githubusercontent.com/chaffed/CHiRP-DM32UV-Support/main/driver/baofeng_dm32uv.py):
   open the link and save the page (Ctrl+S). Keep the name `baofeng_dm32uv.py`.
2. **Turn on developer mode** in CHIRP: **Help → Developer Mode**. Restart CHIRP if it
   asks you to.
3. **Load the driver**: **File → Load Module…** and pick `baofeng_dm32uv.py`.
   CHIRP forgets loaded modules when it closes, so repeat this step each time you start CHIRP.
4. **Download from the radio**: turn the radio on, connect the cable, then
   **Radio → Download From Radio** with vendor **Baofeng** and model **DM-32UV**. It takes
   about a minute.
5. **Save a backup** straight away (**File → Save As**), before you change anything.
6. Edit, then **Radio → Upload To Radio**.

The radio goes back to normal by itself a few seconds after a download or upload; there is no
need to switch it off and on.

### Good to know

- **Channels only show on the radio if they are in a zone.** In CHIRP, zones are in the
  **Banks** tab. To make a new zone, tick channels into the last column, **"New zone"**.
- **DMR settings** per channel (color code, time slot, TX contact, radio ID, RX group list,
  encryption key) are extra fields: turn on **View → Show extra fields**, or open a channel's
  properties.
- **Your DMR IDs, contacts (talkgroups) and RX group lists** are on CHIRP's **Settings**
  tab, under "DMR lists". Leave a name empty to delete an entry; empty rows at the end are
  for adding new ones.
- **What upload changes:** only the channels, zones, radio IDs, contacts and RX group lists
  that differ from the radio. Every page it writes is read back to check it. Radio-wide settings
  and encryption keys aren't changed.
- **Cable:** the usual cable has a CH340 chip. On Linux it appears as `/dev/ttyUSB0`; add
  yourself to the `dialout` group (`sudo usermod -aG dialout $USER`, then log out and
  back in). On macOS, Apple's built-in driver may not work; WCH's CH34x driver may help.
- **Other firmware versions** haven't been tested. If yours isn't DM32.01.01.047, save a
  backup first, and please report how it went in
  [issue #11840](https://chirpmyradio.com/issues/11840).

**Not supported yet:** radio-wide settings (menu options, welcome text, …) and editing
encryption keys (you can choose one per channel). See the [roadmap](docs/ROADMAP.md) for what's planned, in order.

## How it works, briefly

The radio keeps its codeplug in 4 KB flash pages. The last byte of each page is a tag saying
what the page holds, and the radio moves pages around as it rewrites them. The driver scans
the tags and keeps a fixed "logical" image, one slot per tag.

The programming cable tested here corrupts about 1 byte in 1000 on the way back from the
radio, and the protocol has no checksums, so every block is read three times and the copies
are merged byte by byte.

For writing, the radio's firmware erases a whole 4 KB sector on each page write. So the driver
only ever writes whole, aligned pages, reads each one back, and never touches pages that look
like calibration data.

All details are in [`docs/PROTOCOL.md`](docs/PROTOCOL.md).

## What's in this repository

| Path | Contents |
|------|----------|
| [`driver/baofeng_dm32uv.py`](driver/baofeng_dm32uv.py) | The CHIRP driver (the file you load) |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | Missing features, ordered by value to users |
| [`docs/PROTOCOL.md`](docs/PROTOCOL.md) | Protocol, page layout, channel record, zones, DMR lists, firmware notes, test log |
| [`tools/dm32uv_read.py`](tools/dm32uv_read.py) | Read-only dump tool; logs every byte. `--all-pages` makes a full backup |
| [`tools/dm32uv_write.py`](tools/dm32uv_write.py) | Careful single-page writes (no-op test, restore one page from a backup); dry run unless `--yes` |
| [`tools/dm32uv_diff.py`](tools/dm32uv_diff.py) | Compares two dumps page by page, labelling channel and VFO fields |
| [`tools/dump_to_img.py`](tools/dump_to_img.py) | Turns a dump into a CHIRP image |
| [`tools/make_test_image.py`](tools/make_test_image.py) | Builds the synthetic test image (made-up data only) |
| [`tests/`](tests/) | A simulated radio modelled on the firmware, plus read, upload and write-tool tests |
| [`re/`](re/) | Scripts for the analysis: Ghidra (vendor CPS) and C-SKY disassembly (radio firmware) |

### Running the tests

```sh
python3 -m venv .venv && .venv/bin/pip install pyserial
.venv/bin/pip install -e /path/to/chirp        # a clone of github.com/kk7ds/chirp
.venv/bin/python tests/fake_radio.py
.venv/bin/python tests/test_upload.py
.venv/bin/python tests/test_write_tool.py
```

### Reading a radio without CHIRP

```sh
python3 tools/dm32uv_read.py --list                            # find the cable's port
python3 tools/dm32uv_read.py /dev/ttyUSB0 --probe -o probe1    # identify only
python3 tools/dm32uv_read.py /dev/ttyUSB0 -o dump1             # full read
python3 tools/dm32uv_diff.py dump1 dump2                       # what changed between reads
```

Dumps contain personal data (radio ID, contacts), so don't publish them. `.gitignore` keeps
them out of git.

### Reproducing the analysis

The vendor software and firmware aren't included here; download them from Baofeng.

- **CPS (Windows programming software):** `re/run_decomp.sh` with
  [Ghidra](https://ghidra-sre.org) 12.1. `DMR CPS.exe` is file `16` in the extracted v1.60
  installer.
- **Radio firmware:** `re/fw_disasm.sh` disassembles it. It is unencrypted C-SKY code and needs
  `csky-elf` binutils; the script explains how to build them.

## License

GPL-3.0, the same as CHIRP.
