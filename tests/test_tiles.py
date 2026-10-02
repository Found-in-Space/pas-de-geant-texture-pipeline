from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pytest

from foundinspace.textures.processing import ProcessingError
from foundinspace.textures.tiles import _inspect_png


def _chunk(name: bytes, data: bytes) -> bytes:
    checksum = zlib.crc32(name)
    checksum = zlib.crc32(data, checksum) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + name + data + struct.pack(">I", checksum)


def _grayscale_png(size: int, *, transparent: bool = False) -> bytes:
    header = struct.pack(">IIBBBBB", size, size, 8, 0, 0, 0, 0)
    rows = b"".join(b"\x00" + bytes([row]) * size for row in range(size))
    chunks = [_chunk(b"IHDR", header)]
    if transparent:
        chunks.append(_chunk(b"tRNS", b"\x00\x00"))
    chunks.extend((_chunk(b"IDAT", zlib.compress(rows)), _chunk(b"IEND", b"")))
    return b"\x89PNG\r\n\x1a\n" + b"".join(chunks)


def test_png_inspection_accepts_opaque_grayscale(tmp_path: Path) -> None:
    tile = tmp_path / "tile.png"
    tile.write_bytes(_grayscale_png(16))

    details = _inspect_png(tile, tile_size=16)

    assert details["width"] == 16
    assert details["bit_depth"] == 8
    assert details["color_type"] == 0
    assert "tRNS" not in details["chunks"]


def test_png_inspection_rejects_transparency_chunk(tmp_path: Path) -> None:
    tile = tmp_path / "tile.png"
    tile.write_bytes(_grayscale_png(16, transparent=True))

    with pytest.raises(ProcessingError, match="transparency"):
        _inspect_png(tile, tile_size=16)


def test_png_inspection_rejects_corrupt_chunk_crc(tmp_path: Path) -> None:
    tile = tmp_path / "tile.png"
    payload = bytearray(_grayscale_png(16))
    payload[-1] ^= 0xFF
    tile.write_bytes(payload)

    with pytest.raises(ProcessingError, match="CRC mismatch"):
        _inspect_png(tile, tile_size=16)
