"""Prepare opaque sparse XYZ tiles before a preview is used by a 3D viewer.

Archive regridding and masked priority compositing are producer operations.
The runtime receives only available opaque tiles and source resolution caps.
"""

from __future__ import annotations

import json
import math
import subprocess
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.client import IncompleteRead
from pathlib import Path

import numpy as np
from PIL import Image
from PIL import __version__ as pillow_version

from .grid import LEGACY_LUNAR_GRID, TileGrid
from .preview import footprint_mask, tile_range
from .util import atomic_write_json, identity_sha256, sha256_file, utc_now


def download_archive_tile(url, temporary):
    """Retry transient transport failures; never admit partial image bytes."""
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                if not response.headers.get_content_type().startswith("image/"):
                    raise ValueError("Archive response is not an image")
                temporary.write_bytes(response.read())
            return
        except (
            TimeoutError,
            ConnectionError,
            urllib.error.URLError,
            IncompleteRead,
        ) as error:
            if (
                isinstance(error, urllib.error.HTTPError)
                and error.code < 500
                and error.code != 429
            ):
                raise
            if attempt == 3:
                raise
            time.sleep(2**attempt)


def tile_bounds(z, x, y, grid=LEGACY_LUNAR_GRID):
    return grid.tile_bounds(z, x, y)


def archive_tiers(region):
    width, height = region["width"], region["height"]
    tiers = []
    while True:
        tiers.insert(0, (width, height))
        if width <= region["tileSize"] and height <= region["tileSize"]:
            return tiers
        width, height = width // 2, height // 2


def archive_url(region, tiers, level, x, y):
    size = region["tileSize"]
    earlier = sum(math.ceil(w / size) * math.ceil(h / size) for w, h in tiers[:level])
    columns = math.ceil(tiers[level][0] / size)
    group = (earlier + y * columns + x) // 256
    return f"{region['zoomifyUrl']}/TileGroup{group}/{level}-{x}-{y}.jpg"


def archive_window(region, bounds, size, grid=LEGACY_LUNAR_GRID):
    """Return exactly the bounded archive window used by one target tile."""
    west, south, east, north = bounds
    rw, rs, re, rn = region["bounds"]
    tiers = archive_tiers(region)
    step_x = (re - rw) / region["width"]
    step_y = (rn - rs) / region["height"]
    ratio = (east - west) / size / step_x
    if grid.projection == "web-mercator":
        _, latitude = grid.pixel_coordinates(bounds, size)
        ratio = min(
            ratio, (min(abs(np.diff(latitude))) if size > 1 else north - south) / step_y
        )
    level = max(0, min(len(tiers) - 1, math.ceil(len(tiers) - 1 - math.log2(ratio))))
    factor = 2 ** (len(tiers) - 1 - level)
    tile_size = region["tileSize"]
    sx, sy = step_x * factor, step_y * factor
    width, height = tiers[level]
    x0 = max(0, math.floor(((west - rw) / sx - 1) / tile_size))
    x1 = min(
        math.ceil(width / tile_size) - 1, math.floor(((east - rw) / sx + 1) / tile_size)
    )
    y0 = max(0, math.floor(((rn - north) / sy - 1) / tile_size))
    y1 = min(
        math.ceil(height / tile_size) - 1,
        math.floor(((rn - south) / sy + 1) / tile_size),
    )
    return tiers, level, x0, y0, x1, y1


def detail_archive_urls(detail, zoom, size, grid=LEGACY_LUNAR_GRID):
    """Plan a level's bounded source windows before rendering target pixels.

    Includes masked source pixels within the band's rectangle, but never
    source addresses outside the archive. Window selection is shared with
    regridding so a Mercator row cannot silently select a different tier.
    """
    x0, y0, x1, y1 = tile_range(detail["bounds"], zoom, grid)
    region = detail["region"]
    urls = set()
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            tiers, level, ax0, ay0, ax1, ay1 = archive_window(
                region, tile_bounds(zoom, x, y, grid), size, grid
            )
            for ay in range(ay0, ay1 + 1):
                for ax in range(ax0, ax1 + 1):
                    urls.add(archive_url(region, tiers, level, ax, ay))
    return sorted(urls)


def regrid_detail(detail, bounds, size, acquire, prefetch=None, grid=LEGACY_LUNAR_GRID):
    """A bounded archive window, sampled onto one target-grid tile."""
    region = detail["region"]
    west, south, east, north = bounds
    rw, rs, re, rn = region["bounds"]
    dw, ds, de, dn = detail["bounds"]
    longitude, latitude = grid.pixel_coordinates(bounds, size)
    mask = footprint_mask(region["coverage"], bounds, size, grid)
    mask &= (
        (longitude[None, :] >= dw)
        & (longitude[None, :] < de)
        & (latitude[:, None] >= ds)
        & (latitude[:, None] < dn)
    )
    if not mask.any():
        return None
    tiers, level, x0, y0, x1, y1 = archive_window(region, bounds, size, grid)
    step_x = (re - rw) / region["width"]
    step_y = (rn - rs) / region["height"]
    factor = 2 ** (len(tiers) - 1 - level)
    tile_size = region["tileSize"]
    sx, sy = step_x * factor, step_y * factor
    width, height = tiers[level]
    window = Image.new("L", ((x1 - x0 + 1) * tile_size, (y1 - y0 + 1) * tile_size))
    if prefetch:
        prefetch(
            [
                archive_url(region, tiers, level, x, y)
                for y in range(y0, y1 + 1)
                for x in range(x0, x1 + 1)
            ]
        )
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            path = acquire(archive_url(region, tiers, level, x, y))
            with Image.open(path) as image:
                expected = (
                    min(tile_size, width - x * tile_size),
                    min(tile_size, height - y * tile_size),
                )
                if image.format != "JPEG" or image.size != expected:
                    raise ValueError(f"Unexpected archive tile dimensions: {path.name}")
                window.paste(
                    image.convert("L"), ((x - x0) * tile_size, (y - y0) * tile_size)
                )
    extent = (
        (west - rw) / sx - x0 * tile_size,
        (rn - north) / sy - y0 * tile_size,
        (east - rw) / sx - x0 * tile_size,
        (rn - south) / sy - y0 * tile_size,
    )
    if grid.projection == "geographic":
        sampled = window.transform(
            (size, size), Image.Transform.EXTENT, extent, Image.Resampling.BILINEAR
        )
    else:
        # Mercator rows are nonlinear in latitude. Sample source pixel centres
        # explicitly; a rectangular image stretch would silently keep the old grid.
        data = np.asarray(window, dtype=np.float32)
        sample_x = np.clip(
            (longitude - rw) / sx - x0 * tile_size - 0.5, 0, data.shape[1] - 1
        )
        sample_y = np.clip(
            (rn - latitude) / sy - y0 * tile_size - 0.5, 0, data.shape[0] - 1
        )
        left, top = np.floor(sample_x).astype(int), np.floor(sample_y).astype(int)
        right, bottom = (
            np.minimum(left + 1, data.shape[1] - 1),
            np.minimum(top + 1, data.shape[0] - 1),
        )
        ax, ay = sample_x - left, sample_y - top
        north_pixels = (
            data[top[:, None], left[None, :]] * (1 - ax)
            + data[top[:, None], right[None, :]] * ax
        )
        south_pixels = (
            data[bottom[:, None], left[None, :]] * (1 - ax)
            + data[bottom[:, None], right[None, :]] * ax
        )
        sampled = Image.fromarray(
            np.rint(
                north_pixels * (1 - ay[:, None]) + south_pixels * ay[:, None]
            ).astype(np.uint8)
        )
    return sampled, Image.fromarray(mask.astype(np.uint8) * 255)


def sample_parent(path, address, parent, size):
    z, x, y = address
    pz, px, py = parent
    factor = 2 ** (z - pz)
    left, top = (x - px * factor) * size / factor, (y - py * factor) * size / factor
    with Image.open(path) as image:
        return image.convert("L").transform(
            (size, size),
            Image.Transform.EXTENT,
            (left, top, left + size / factor, top + size / factor),
            Image.Resampling.BILINEAR,
        )


def prepare_preview_tiles(
    preview_root: Path,
    source_root: Path,
    output_root: Path,
    *,
    allow_download=False,
    download_concurrency=8,
):
    with ThreadPoolExecutor(max_workers=download_concurrency) as executor:
        return _prepare_preview_tiles(
            preview_root, source_root, output_root, allow_download, executor
        )


def validate_preview_tiles(output_root: Path):
    """Authenticate and decode every tile declared by the prepared product."""
    product = json.loads((output_root / "product.json").read_text())
    if product["kind"] != "sparse-opaque-xyz" or product["formatVersion"] not in {1, 2}:
        raise ValueError("Expected sparse-opaque-xyz format 1 or 2")
    grid = TileGrid.from_metadata(product.get("grid", LEGACY_LUNAR_GRID.metadata()))
    if product["formatVersion"] == 2 and "grid" not in product:
        raise ValueError("Format 2 requires an explicit grid")
    if product["formatVersion"] == 1 and grid != LEGACY_LUNAR_GRID:
        raise ValueError("Format 1 bytes must retain their geographic lunar grid")
    if product["identity"] != identity_sha256(
        {k: v for k, v in product.items() if k not in {"createdAt", "identity"}}
    ):
        raise ValueError("Product descriptor identity changed")
    if "matchingReportSha256" in product:
        matching_path = output_root / "matching.json"
        if (
            sha256_file(matching_path) != product["matchingReportSha256"]
            or json.loads(matching_path.read_text()) != product["matching"]
        ):
            raise ValueError("Matching report changed")
    checksum_path = output_root / "checksums.sha256"
    if sha256_file(checksum_path) != product["payloadManifestSha256"]:
        raise ValueError("Payload checksum manifest changed")
    hashes = dict(
        line.split("  ", 1)[::-1] for line in checksum_path.read_text().splitlines()
    )
    declared = set()
    counts = {}
    byte_count = 0
    for source in product["sources"]:
        count = 0
        for level in source["levels"]:
            z = level["zoom"]
            if not source["minimumZoom"] <= z <= source["maximumZoom"]:
                raise ValueError("Level outside declared source cap")
            for x, y in level["tiles"]:
                if not 0 <= x < 2**z or not 0 <= y < 2**z:
                    raise ValueError("Invalid XYZ tile address")
                relative = source["pathTemplate"].format(z=z, x=x, y=y)
                if relative in declared:
                    raise ValueError("Duplicate declared tile")
                declared.add(relative)
                path = output_root / relative
                if hashes.get(relative) != sha256_file(path):
                    raise ValueError(f"Tile checksum changed: {relative}")
                with Image.open(path) as image:
                    if (
                        image.format != "PNG"
                        or image.mode != "L"
                        or image.size != (product["tileSize"], product["tileSize"])
                        or "transparency" in image.info
                    ):
                        raise ValueError(f"Unexpected tile encoding: {relative}")
                    image.load()
                byte_count += path.stat().st_size
                count += 1
        counts[source["id"]] = count
    if declared != hashes.keys():
        raise ValueError("Declared tiles do not match payload checksum manifest")
    report = {
        "status": "passed",
        "identity": product["identity"],
        "grid": grid.metadata(),
        "tileCount": len(declared),
        "sourceTileCounts": counts,
        "payloadBytes": byte_count,
        "validatedAt": utc_now(),
        "method": "Full declared-payload SHA-256, PNG decoding, dimensions, "
        "opacity, address and source-cap validation.",
    }
    atomic_write_json(output_root / "validation.json", report)
    return report


def _prepare_preview_tiles(
    preview_root: Path,
    source_root: Path,
    output_root: Path,
    allow_download,
    executor,
):
    product_path = preview_root / "product.json"
    preview = json.loads(product_path.read_text())
    if preview["kind"] != "sparse-detail-preview" or preview["formatVersion"] not in {
        1,
        2,
    }:
        raise ValueError("Expected sparse-detail-preview format 1 or 2")
    size = preview["tileSize"]
    if not isinstance(size, int) or size <= 0 or size > 256 or size & (size - 1):
        raise ValueError("Preview tileSize must be a power of two no larger than 256")
    grid = (
        LEGACY_LUNAR_GRID
        if preview["formatVersion"] == 1
        else TileGrid.from_metadata(preview["grid"])
    )
    if preview.get("grid", grid.metadata()) != grid.metadata():
        raise ValueError("Preview format and declared grid differ")
    if output_root == preview_root or source_root == output_root:
        raise ValueError("Input, archive cache and output roots must be distinct")
    source_root.mkdir(parents=True, exist_ok=True)
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "product.json").unlink(missing_ok=True)
    atomic_write_json(
        output_root / "state.json", {"status": "building", "startedAt": utc_now()}
    )
    inputs = {
        "previewManifestSha256": sha256_file(product_path),
        "contextTiles": [],
        "archiveTiles": [],
    }
    acquired = {}
    used_archive_urls = set()

    def acquire(url):
        key = identity_sha256(url)
        path = source_root / f"{key}.jpg"
        receipt = source_root / f"{key}.json"
        if url in acquired:
            return path
        if path.exists() and receipt.exists():
            record = json.loads(receipt.read_text())
            if record["url"] != url or record["sha256"] != sha256_file(path):
                raise ValueError("Archive cache identity changed")
        else:
            if not allow_download:
                raise ValueError(
                    "Missing archive tile; use --allow-download for acquisition"
                )
            temporary = path.with_suffix(".partial")
            download_archive_tile(url, temporary)
            # Decode before admitting the object to the cache.
            with Image.open(temporary) as image:
                image.verify()
            temporary.replace(path)
            record = {
                "url": url,
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
                "retrievedAt": utc_now(),
            }
            atomic_write_json(receipt, record)
        acquired[url] = record
        return path

    def acquire_used(url):
        path = acquire(url)
        used_archive_urls.add(url)
        return path

    checksums = []
    sources = []
    available = []
    size = preview["tileSize"]

    def emit(source_id, address, image):
        z, x, y = address
        relative = f"{source_id}/{z}/{x}/{y}.png"
        path = output_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".partial.png")
        image.convert("L").save(temporary, compress_level=3)
        temporary.replace(path)
        checksums.append(f"{sha256_file(path)}  {relative}\n")
        return path

    context = {}
    for level in preview["levels"]:
        for x, y in level["tiles"]:
            address = (level["zoom"], x, y)
            relative = preview["pathTemplate"].format(z=address[0], x=x, y=y)
            path = preview_root / relative
            inputs["contextTiles"].append(
                {"path": relative, "sha256": sha256_file(path)}
            )
            with Image.open(path) as image:
                if image.size != (size, size) or image.mode != "LA":
                    raise ValueError("Unexpected context tile encoding")
                if image.getchannel("A").getextrema() != (255, 255):
                    continue  # Incomplete boundary tiles belong to the global provider.
                context[address] = emit("context", address, image)
    if not context:
        raise ValueError("No complete context tiles available")
    available.append(context)

    def add_source(source_id, priority, attribution, tiles):
        zooms = sorted({address[0] for address in tiles})
        sources.append(
            {
                "id": source_id,
                "priority": priority,
                "attribution": attribution,
                "minimumZoom": min(zooms),
                "maximumZoom": max(zooms),
                "pathTemplate": f"{source_id}/{{z}}/{{x}}/{{y}}.png",
                "levels": [
                    {
                        "zoom": z,
                        "tiles": sorted([x, y] for tz, x, y in tiles if tz == z),
                    }
                    for z in zooms
                ],
            }
        )

    add_source("context", 0, "ISAS/JAXA · SELENE TC", context)
    print(f"context: {len(context)} opaque tiles", flush=True)

    def underlay(address):
        z, x, y = address
        for pz in range(z, -1, -1):
            factor = 2 ** (z - pz)
            parent = (pz, x // factor, y // factor)
            for tiles in reversed(available):
                if parent in tiles:
                    return sample_parent(tiles[parent], address, parent, size)
        return None

    for detail in sorted(preview["details"], key=lambda entry: entry["priority"]):
        tiles = {}
        minimum_zoom = min(address[0] for address in context)
        for z in range(minimum_zoom, detail["maximumZoom"] + 1):
            x0, y0, x1, y1 = tile_range(detail["bounds"], z, grid)
            if allow_download:
                urls = detail_archive_urls(detail, z, size, grid)
                print(
                    f"{detail['id']} z{z}: acquiring {len(urls)} archive tiles",
                    flush=True,
                )
                list(executor.map(acquire, urls))
            for y in range(y0, y1 + 1):
                for x in range(x0, x1 + 1):
                    address = (z, x, y)
                    image = underlay(address)
                    if image is None:
                        continue
                    result = regrid_detail(
                        detail,
                        tile_bounds(*address, grid=grid),
                        size,
                        acquire_used,
                        lambda urls: list(executor.map(acquire, urls)),
                        grid=grid,
                    )
                    if result is None:
                        continue
                    overlay, mask = result
                    image.paste(overlay, (0, 0), mask)
                    tiles[address] = emit(detail["id"], address, image)
            print(
                f"{detail['id']} z{z}: {sum(a[0] == z for a in tiles)} tiles",
                flush=True,
            )
        if tiles:
            available.append(tiles)
            add_source(detail["id"], detail["priority"], "NASA/GSFC/ASU · LROC", tiles)
    inputs["archiveTiles"] = [acquired[url] for url in sorted(used_archive_urls)]
    repository = Path(__file__).parents[3]
    code_paths = [
        Path(__file__),
        Path(__file__).with_name("preview.py"),
        Path(__file__).with_name("cli.py"),
        Path(__file__).with_name("util.py"),
        Path(__file__).with_name("grid.py"),
        repository / "pyproject.toml",
        repository / "uv.lock",
    ]
    code_hashes = {
        str(path.relative_to(repository)): sha256_file(path) for path in code_paths
    }
    git_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    manifest = {
        "kind": "sparse-opaque-xyz",
        "formatVersion": preview["formatVersion"],
        "grid": grid.metadata(),
        "tileSize": size,
        "sources": sources,
        "inputs": inputs,
        "preview": {
            key: value
            for key, value in preview.items()
            if key not in {"levels", "commands"}
        },
        "producerGitSha": git_sha,
        "producerCodeHashes": code_hashes,
        "producerDirty": bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=repository,
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        ),
        "tools": {"pillow": pillow_version, "numpy": np.__version__},
        "method": f"Opaque {grid.projection} XYZ. Bilinear archive regridding; declared "
        "footprint and band masks; priority over best complete parent. "
        "Incomplete context tiles omitted. No seam or tone correction.",
        "createdAt": utc_now(),
    }
    checksum_path = output_root / "checksums.sha256"
    checksum_path.write_text("".join(sorted(checksums)))
    manifest["payloadManifestSha256"] = sha256_file(checksum_path)
    manifest["identity"] = identity_sha256(
        {k: v for k, v in manifest.items() if k != "createdAt"}
    )
    atomic_write_json(output_root / "product.json", manifest)
    atomic_write_json(
        output_root / "state.json",
        {
            "status": "complete",
            "identity": manifest["identity"],
            "tileCount": len(checksums),
            "completedAt": utc_now(),
        },
    )
    return {
        "identity": manifest["identity"],
        "tileCount": len(checksums),
        "archiveTileCount": len(used_archive_urls),
    }
