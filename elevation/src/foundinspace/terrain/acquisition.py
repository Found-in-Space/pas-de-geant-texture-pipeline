"""Authenticated public file and uncompressed raster-window acquisition."""

import hashlib
import json
import re
import time
import urllib.request
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import Affine


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def acquire_file(url, destination, expected_bytes, rate=4 * 1024 * 1024):
    """Resume an exact-sized file; authenticate every completed payload."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    receipt = destination.with_suffix(destination.suffix + ".receipt.json")
    if destination.exists():
        previous = json.loads(receipt.read_text())
        if (
            previous["url"] != url
            or destination.stat().st_size != expected_bytes
            or digest(destination) != previous["sha256"]
        ):
            raise ValueError(f"Acquisition conflict: {destination.name}")
        return previous
    partial = destination.with_suffix(destination.suffix + ".part")
    offset = partial.stat().st_size if partial.exists() else 0
    if offset > expected_bytes:
        raise ValueError("Partial file exceeds declared length")
    if offset < expected_bytes:
        request = urllib.request.Request(
            url,
            headers={
                "Range": f"bytes={offset}-{expected_bytes - 1}",
                "Accept-Encoding": "identity",
            },
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            if (
                response.status != 206
                or response.headers.get("Content-Range")
                != f"bytes {offset}-{expected_bytes - 1}/{expected_bytes}"
            ):
                raise ValueError("Server did not honor the exact byte range")
            received = 0
            start = time.monotonic()
            with partial.open("ab") as output:
                while block := response.read(1024 * 1024):
                    output.write(block)
                    received += len(block)
                    delay = received / rate - (time.monotonic() - start)
                    if delay > 0:
                        time.sleep(delay)
    if partial.stat().st_size != expected_bytes:
        raise ValueError("Incomplete acquisition")
    result = {"url": url, "bytes": expected_bytes, "sha256": digest(partial)}
    # A crash between receipt placement and payload promotion remains resumable.
    write_json(receipt, result)
    partial.replace(destination)
    return result


def acquire_grid_window(spec, destination):
    """Fetch exact full-row ranges, retain them, and extract a raw IMG window.

    The spec declares byte layout and pixel registration from an archived label.
    Retained range hashes authenticate every byte used in the extracted GeoTIFF.
    No implicit PDS units, half-pixel corrections or missing-value conventions.
    """
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    receipt_path = destination.with_suffix(".receipt.json")
    if destination.exists():
        receipt = json.loads(receipt_path.read_text())
        if receipt["spec"] != spec or digest(destination) != receipt["sha256"]:
            raise ValueError("Window acquisition conflict")
        for part in receipt["ranges"]:
            if digest(destination.parent / part["file"]) != part["sha256"]:
                raise ValueError("Range payload changed")
        return receipt
    dtype = np.dtype(spec["dtype"])
    width, height = spec["size"]
    x, y, columns, rows = spec["window"]
    if not (0 <= x < x + columns <= width and 0 <= y < y + rows <= height):
        raise ValueError("Window outside declared raster")
    row_bytes = width * dtype.itemsize
    total = spec["header_bytes"] + row_bytes * height
    temporary = destination.with_suffix(".part.tif")
    chunks = []
    transform = Affine(*spec["transform"]) * Affine.translation(x, y)
    with rasterio.open(
        temporary,
        "w",
        driver="GTiff",
        width=columns,
        height=rows,
        count=1,
        dtype=dtype.name,
        crs=spec["crs"],
        transform=transform,
        nodata=spec["nodata"],
        tiled=True,
        compress="deflate",
    ) as output:
        for first in range(y, y + rows, 64):
            count = min(64, y + rows - first)
            start = spec["header_bytes"] + first * row_bytes
            stop = start + count * row_bytes - 1
            payload = (
                destination.parent
                / f"{destination.stem}.{first}-{first + count - 1}.raw"
            )
            request = urllib.request.Request(
                spec["url"],
                headers={
                    "Range": f"bytes={start}-{stop}",
                    "Accept-Encoding": "identity",
                },
            )
            if not payload.exists():
                with urllib.request.urlopen(request, timeout=120) as response:
                    content_range = response.headers.get("Content-Range", "")
                    if response.status != 206 or not re.fullmatch(
                        f"bytes {start}-{stop}/{total}", content_range
                    ):
                        raise ValueError(f"Unexpected raster range: {content_range}")
                    data = response.read()
                if len(data) != count * row_bytes:
                    raise ValueError("Incomplete raster range")
                partial = payload.with_suffix(".part")
                partial.write_bytes(data)
                partial.replace(payload)
            data = payload.read_bytes()
            if len(data) != count * row_bytes:
                raise ValueError("Invalid retained range size")
            values = np.frombuffer(data, dtype=dtype).reshape(count, width)[
                :, x : x + columns
            ]
            output.write(
                values, 1, window=rasterio.windows.Window(0, first - y, columns, count)
            )
            chunks.append(
                {
                    "file": payload.name,
                    "byteRange": [start, stop],
                    "sha256": digest(payload),
                }
            )
    result = {
        "spec": spec,
        "ranges": chunks,
        "sha256": digest(temporary),
        "method": "Exact uncompressed row ranges, native grid window; no resampling or value conversion",
    }
    write_json(receipt_path, result)
    temporary.replace(destination)
    return result
