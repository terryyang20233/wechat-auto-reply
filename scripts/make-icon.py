#!/usr/bin/env python3
"""Generate a chat-bubble PNG for the macOS app icon."""
from __future__ import annotations

import math
import struct
import sys
import zlib
from pathlib import Path


def write_png(path: Path, size: int, rgba_at) -> None:
    raw = bytearray()
    for y in range(size):
        raw.append(0)
        for x in range(size):
            raw.extend(rgba_at(x, y, size))

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(png)


def _in_round_rect(x: float, y: float, left: float, top: float, right: float, bottom: float, radius: float) -> bool:
    if left + radius <= x <= right - radius and top <= y <= bottom:
        return True
    if left <= x <= right and top + radius <= y <= bottom - radius:
        return True
    corners = (
        (left + radius, top + radius),
        (right - radius, top + radius),
        (left + radius, bottom - radius),
        (right - radius, bottom - radius),
    )
    return any(math.hypot(x - cx, y - cy) <= radius for cx, cy in corners)


def pixel(x: int, y: int, size: int) -> bytes:
    cx = cy = (size - 1) / 2
    r = math.hypot(x - cx, y - cy) / (size / 2)
    if r > 0.98:
        return b"\x00\x00\x00\x00"
    # rounded-square plate
    if r > 0.88:
        return bytes((36, 92, 78, 255))
    bg = bytes((47, 122, 104, 255))

    s = float(size)
    left_bubble = _in_round_rect(x, y, s * 0.18, s * 0.22, s * 0.62, s * 0.52, s * 0.08)
    right_bubble = _in_round_rect(x, y, s * 0.38, s * 0.48, s * 0.82, s * 0.78, s * 0.08)
    if left_bubble:
        return bytes((232, 246, 240, 255))
    if right_bubble:
        return bytes((196, 232, 214, 255))
    return bg


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "icon.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    write_png(out, 1024, pixel)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
