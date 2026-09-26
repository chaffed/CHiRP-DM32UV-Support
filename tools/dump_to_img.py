#!/usr/bin/env python3
"""Build a CHIRP image for the DM-32UV driver from a dm32uv_read.py dump.

The image is the driver's logical layout: one 4 KB slot per tag in
IMAGE_TAGS (see driver/baofeng_dm32uv.py), all 0xFF where the dump has no
page with that tag.

    python3 dump_to_img.py dump7 dump7.img
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'driver'))
from baofeng_dm32uv import IMAGE_TAGS, PAGE  # noqa: E402


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    dump, out = sys.argv[1:]
    pages = {}
    for name in os.listdir(os.path.join(dump, 'pages')):
        tag = int(name[3:5], 16)
        if tag in IMAGE_TAGS:
            with open(os.path.join(dump, 'pages', name), 'rb') as f:
                pages[tag] = f.read()
    image = bytearray(b'\xFF' * (len(IMAGE_TAGS) * PAGE))
    for i, tag in enumerate(IMAGE_TAGS):
        if tag in pages:
            image[i * PAGE:(i + 1) * PAGE] = pages[tag]
    with open(out, 'wb') as f:
        f.write(image)
    print('%s: %d of %d tags present' % (out, len(pages), len(IMAGE_TAGS)))


if __name__ == '__main__':
    main()
