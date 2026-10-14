"""Authenticated, bounded source readers for matched display overlays."""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

from .grid import TileGrid
from .photometry import decode_srgb
from .preview import footprint_mask
from .preview_tiles import regrid_detail
from .toolchain import gdalinfo, run_command
from .util import atomic_write_json, identity_sha256, sha256_file

NODATA = -9999


def local_path(root, relative):
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or "$" in relative or "~" in relative:
        raise ValueError(f"Expected a portable relative input path: {relative}")
    return root / path


def authenticate(root, entry):
    path = local_path(root, entry["path"])
    if sha256_file(path) != entry["sha256"]:
        raise ValueError(f"Input checksum changed: {entry['path']}")
    return path


class ReferenceTiles:
    def __init__(self, root, descriptor_sha256, grid, size):
        self.root, self.grid, self.size = root, grid, size
        path = authenticate(root, {"path": "product.json", "sha256": descriptor_sha256})
        self.product = json.loads(path.read_text())
        tiles = self.product["tiles"]
        if (
            self.product.get("format_version") != 2
            or TileGrid.from_metadata(self.product["grid"]) != grid
        ):
            raise ValueError("Reference body/grid differs from overlay")
        if (
            tiles["tile_size"] != size
            or tiles["channels"] != "grayscale"
            or not tiles["opaque"]
        ):
            raise ValueError("Reference must have matching opaque grayscale tiles")
        self.minimum, self.maximum = tiles["minimum_zoom"], tiles["maximum_zoom"]
        self.template = tiles["path_template"]
        self.hashes, self.used = {}, {}
        self.tile = lru_cache(maxsize=64)(self._tile)

    def _tile(self, z, x, y):
        if z not in self.hashes:
            level = next(
                entry for entry in self.product["levels"] if entry["zoom"] == z
            )
            path = authenticate(
                self.root,
                {"path": level["manifest"], "sha256": level["manifest_sha256"]},
            )
            self.hashes[z] = dict(
                line.split("  ", 1)[::-1] for line in path.read_text().splitlines()
            )
        relative = self.template.format(z=z, x=x, y=y)
        path = authenticate(
            self.root, {"path": relative, "sha256": self.hashes[z][relative]}
        )
        with Image.open(path) as image:
            if (
                image.mode != "L"
                or image.size != (self.size, self.size)
                or "transparency" in image.info
            ):
                raise ValueError("Unexpected reference tile encoding")
            value = decode_srgb(np.asarray(image, dtype=np.float32) / 255)
        self.used[relative] = self.hashes[z][relative]
        return value

    def sample(self, bounds, size, zoom):
        z = max(self.minimum, min(zoom, self.maximum))
        world = self.size * 2**z
        west, south, east, north = bounds
        left, right = (west + 180) / 360 * world, (east + 180) / 360 * world
        top, bottom = (
            float(self.grid.normalized_y(north)) * world,
            float(self.grid.normalized_y(south)) * world,
        )
        x0, y0 = math.floor(left / self.size) - 1, math.floor(top / self.size) - 1
        x1, y1 = math.ceil(right / self.size) + 1, math.ceil(bottom / self.size) + 1
        if (x1 - x0) * (y1 - y0) * self.size**2 > 20_000_000:
            raise ValueError("Reference sample exceeds bounded window budget")
        atlas = np.empty(((y1 - y0) * self.size, (x1 - x0) * self.size), np.float32)
        for y in range(y0, y1):
            for x in range(x0, x1):
                tile = self.tile(z, x % 2**z, min(2**z - 1, max(0, y)))
                atlas[
                    (y - y0) * self.size : (y - y0 + 1) * self.size,
                    (x - x0) * self.size : (x - x0 + 1) * self.size,
                ] = tile
        return np.asarray(
            Image.fromarray(atlas).resize(
                (size, size),
                Image.Resampling.BILINEAR,
                box=(
                    left - x0 * self.size,
                    top - y0 * self.size,
                    right - x0 * self.size,
                    bottom - y0 * self.size,
                ),
            ),
            dtype=np.float32,
        )


class RasterSource:
    """Linearize before averaging; keep full-resolution intermediates on disk."""

    def __init__(self, spec, root, work, crs, grid, tools):
        self.spec, self.work, self.crs, self.grid = spec, work, crs, grid
        work.mkdir(parents=True, exist_ok=True)
        for entry in spec["inputs"]:
            authenticate(root, entry)
        declared = {entry["path"] for entry in spec["inputs"]}
        self.vrts = []
        for index, raster in enumerate(spec["rasters"]):
            if raster["path"] not in declared:
                raise ValueError("Raster must be listed in authenticated inputs")
            path = local_path(root, raster["path"])
            info, _ = gdalinfo(path)
            if (
                info["size"] != raster["size"]
                or len(info["bands"]) != 1
                or info["bands"][0]["type"] != raster["data_type"]
            ):
                raise ValueError(f"Unexpected raster metadata: {raster['path']}")
            # GDAL reports sidecar dependencies (including detached PDS pixels).
            # All must be explicitly admitted; a label hash alone is insufficient.
            admitted = {local_path(root, name).resolve() for name in declared}
            if any(Path(name).resolve() not in admitted for name in info["files"]):
                raise ValueError("Raster has undeclared file dependencies")
            binary, vrt, receipt = (
                work / f"{index}.bin",
                work / f"{index}.vrt",
                work / f"{index}.json",
            )
            key = identity_sha256(
                {"source": spec, "raster": raster, "tools": tools, "stage": 1}
            )
            reused = False
            if receipt.exists():
                record = json.loads(receipt.read_text())
                reused = record["key"] == key and all(
                    (work / name).exists() and sha256_file(work / name) == digest
                    for name, digest in record["files"].items()
                )
            if not reused:
                run_command(
                    [
                        "gdal_translate",
                        "-q",
                        "-of",
                        "ENVI",
                        "-ot",
                        "Float32",
                        "-co",
                        "INTERLEAVE=BSQ",
                        str(path),
                        str(binary),
                    ]
                )
                width, height = info["size"]
                data = np.memmap(binary, dtype="<f4", mode="r+", shape=(height, width))
                for row in range(0, height, 128):
                    block = np.asarray(data[row : row + 128]).copy()
                    valid = (
                        np.isfinite(block)
                        & (block >= spec["valid_range"][0])
                        & (block <= spec["valid_range"][1])
                    )
                    for value in spec.get("nodata", []):
                        valid &= block != value
                    block = block * spec["scale"] + spec.get("offset", 0)
                    if spec["encoding"] == "srgb":
                        block = decode_srgb(np.clip(block, 0, 1))
                    data[row : row + 128] = np.where(valid, block, NODATA)
                data.flush()
                del data
                run_command(
                    [
                        "gdal_translate",
                        "-q",
                        "-of",
                        "VRT",
                        "-a_nodata",
                        str(NODATA),
                        str(binary),
                        str(vrt),
                    ]
                )
                files = [binary, binary.with_suffix(".hdr"), vrt]
                auxiliary = binary.with_suffix(".bin.aux.xml")
                if auxiliary.exists():
                    files.append(auxiliary)
                atomic_write_json(
                    receipt,
                    {"key": key, "files": {p.name: sha256_file(p) for p in files}},
                )
            self.vrts.append(vrt)
        self.mosaic = work / "mosaic.vrt"
        run_command(
            ["gdalbuildvrt", "-q", "-overwrite", str(self.mosaic), *map(str, self.vrts)]
        )
        self.level = None

    def warp(self, bounds, width, height, destination):
        run_command(
            [
                "gdalwarp",
                "-q",
                "-overwrite",
                "-wm",
                "128",
                "-t_srs",
                str(self.crs),
                "-te",
                *map(str, self.grid.project_bounds(bounds)),
                "-ts",
                str(width),
                str(height),
                "-r",
                "average",
                "-srcnodata",
                str(NODATA),
                "-dstnodata",
                str(NODATA),
                "-of",
                "ENVI",
                "-ot",
                "Float32",
                str(self.mosaic),
                str(destination),
            ],
            env={"GDAL_CACHEMAX": "128"},
        )

    def sample(self, bounds, size, zoom):
        address = self.grid.tile_range(bounds, zoom)
        if size <= 256 and address[0] == address[2] and address[1] == address[3]:
            # Warp each complete source level once on disk, then read bounded
            # windows. Never invoke GDAL once per production output tile.
            if self.level is None or self.level[0] != (zoom, size):
                self.level = None
                x0, y0, x1, y1 = self.grid.tile_range(self.spec["bounds"], zoom)
                width, height = (x1 - x0 + 1) * size, (y1 - y0 + 1) * size
                if width * height > 1_000_000_000:
                    raise ValueError("Raster level exceeds the four-GB staging budget")
                nw, se = (
                    self.grid.tile_bounds(zoom, x0, y0),
                    self.grid.tile_bounds(zoom, x1, y1),
                )
                destination = self.work / "level.bin"
                self.warp([nw[0], se[1], se[2], nw[3]], width, height, destination)
                data = np.memmap(
                    destination, dtype="<f4", mode="r", shape=(height, width)
                )
                self.level = (zoom, size), (x0, y0), data
            _, (x0, y0), data = self.level
            x, y = address[:2]
            data = np.array(
                data[
                    (y - y0) * size : (y - y0 + 1) * size,
                    (x - x0) * size : (x - x0 + 1) * size,
                ]
            )
        else:
            destination = self.work / "window.bin"
            self.warp(bounds, size, size, destination)
            data = np.array(
                np.memmap(destination, dtype="<f4", mode="r", shape=(size, size))
            )
        valid = np.isfinite(data) & (data != NODATA)
        return np.where(valid, data, 0), valid


class ArchiveSource:
    def __init__(self, spec, root, archive, grid):
        self.spec, self.archive, self.grid = spec, archive, grid
        for entry in spec["inputs"]:
            authenticate(root, entry)
        if spec["metadata"] not in {entry["path"] for entry in spec["inputs"]}:
            raise ValueError("Archive metadata must be an authenticated input")
        region = json.loads(local_path(root, spec["metadata"]).read_text())
        self.detail = {"region": region, "bounds": spec["bounds"]}
        self.used = {}

    def acquire(self, url):
        path = self.archive / f"{identity_sha256(url)}.jpg"
        if url not in self.used:
            record = json.loads(path.with_suffix(".json").read_text())
            if record["url"] != url or sha256_file(path) != record["sha256"]:
                raise ValueError("Archive cache identity changed")
            self.used[url] = {"url": url, "sha256": record["sha256"]}
        return path

    def sample(self, bounds, size, zoom):
        result = regrid_detail(self.detail, bounds, size, self.acquire, grid=self.grid)
        if result is None:
            return np.zeros((size, size), np.float32), np.zeros((size, size), bool)
        image, mask = result
        value = np.asarray(image, dtype=np.float32) / 255
        return decode_srgb(value), np.asarray(mask) > 0


def source_mask(spec, bounds, size, grid, exclusions):
    longitude, latitude = grid.pixel_coordinates(bounds, size)
    west, south, east, north = spec["bounds"]
    mask = (
        (longitude[None, :] >= west)
        & (longitude[None, :] < east)
        & (latitude[:, None] >= south)
        & (latitude[:, None] < north)
    )
    if exclusions:
        mask &= ~footprint_mask(exclusions, bounds, size, grid)
    return mask
