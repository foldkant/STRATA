"""Remove faint background-removal residue from the platform brand mark.

The source artwork contains very low-opacity pixels across the transparent
canvas. Those pixels are almost invisible on white, but form a rectangular
haze when the mark is placed on the platform's pale green background.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


MIN_VISIBLE_ALPHA = 48


def clean_transparency(source: Path, destination: Path) -> None:
    image = Image.open(source).convert("RGBA")
    pixels = bytearray(image.tobytes())
    alpha_span = 255 - MIN_VISIBLE_ALPHA

    for offset in range(0, len(pixels), 4):
        alpha = pixels[offset + 3]
        if alpha < MIN_VISIBLE_ALPHA:
            pixels[offset : offset + 4] = b"\x00\x00\x00\x00"
            continue

        # Preserve antialiased edges while remapping the retained foreground
        # across the full alpha range.
        pixels[offset + 3] = round((alpha - MIN_VISIBLE_ALPHA) * 255 / alpha_span)

    cleaned = Image.frombytes("RGBA", image.size, bytes(pixels))
    destination.parent.mkdir(parents=True, exist_ok=True)
    cleaned.save(destination, format="PNG", optimize=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    clean_transparency(args.source, args.destination)


if __name__ == "__main__":
    main()
