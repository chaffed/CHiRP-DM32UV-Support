# CHiRP DM-32UV Support

Open-source programming support for the **Baofeng DM-32UV** DMR radio. The
goal is a [CHIRP](https://chirpmyradio.com) driver: first as a standalone
module you load into stock CHIRP, then submitted upstream.

> **Status: early.** The programming protocol has been reverse engineered from
> the vendor's Windows software (CPS v1.60), but **it has not been checked
> against a real radio yet.** No write support exists.

## What's here

| Path | Contents |
|------|----------|
| [`docs/PROTOCOL.md`](docs/PROTOCOL.md) | The serial programming protocol: handshake, block commands, tagged-page codeplug layout |
| [`tools/dm32uv_read.py`](tools/dm32uv_read.py) | Read-only tool that downloads the codeplug and logs all traffic |
| [`tests/fake_radio.py`](tests/fake_radio.py) | Runs the tool against a simulated radio |
| [`re/`](re/) | Headless Ghidra scripts used for the analysis |

## Reading a radio

The tool only reads. It never sends a write command.

```sh
pip install pyserial                                  # Debian: sudo apt install python3-serial
python3 tools/dm32uv_read.py --list                   # find the cable's port
python3 tools/dm32uv_read.py /dev/ttyUSB0 --probe -o probe1   # identify only
python3 tools/dm32uv_read.py /dev/ttyUSB0 -o dump1            # full read
```

On Linux, add yourself to the `dialout` group to use the port. Each run saves
`traffic.log` (every byte sent and received), `info.json`, and the pages it read.
Please attach these to an issue if something fails.

The usual cable uses a CH340 chip. It works with Linux's `ch341` driver. On
macOS, Apple's built-in driver may reject serial settings with
`Invalid argument`. WCH's CH34xVCPDriver may fix that.

## Reproducing the analysis

The scripts in `re/` need [Ghidra](https://ghidra-sre.org) (tested with 12.1)
and a copy of the vendor CPS. The CPS isn't included here; get it from
Baofeng. `DMR CPS.exe` is file `16` in the extracted v1.60 installer.

```sh
cd re
GHIDRA_HOME=/path/to/ghidra CPS_EXE=/path/to/16 ./run_decomp.sh out.c 0044a210
python3 callsites.py 0x44a210 0x44c700    # send/recv lengths and timeouts
```

## Roadmap

1. Confirm the read protocol against a real radio
2. Map the codeplug pages (channels, zones, contacts, settings) by diffing reads
3. CHIRP driver module: download, upload, channels
4. Submit upstream to CHIRP

## License

GPL-3.0, the same as CHIRP.
