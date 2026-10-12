"""Bounded, local sparse preview builder; separate from opaque format v1 products.

Kaguya inputs are explicitly downloaded before this offline command. GDAL does
reprojection and direct-from-source averaging; NumPy maps bounded tile windows.
Fine archive pyramids remain referenced inputs, regridded by the study consumer.
"""

from __future__ import annotations

import math
import subprocess
import tomllib
from pathlib import Path
from xml.sax.saxutils import escape

import numpy as np
from PIL import Image

from .grid import LEGACY_LUNAR_GRID, TileGrid
from .processing import validate_grid_reference
from .toolchain import gdalinfo, run_command, tool_versions
from .util import atomic_write_json, identity_sha256, sha256_file, utc_now


def area_bounds(latitude: float, longitude: float, km: float, radius: float):
    half = km * 1000 / 2 * 180 / (math.pi * radius)
    lon_half = half / math.cos(math.radians(latitude))
    return [
        longitude - lon_half,
        latitude - half,
        longitude + lon_half,
        latitude + half,
    ]


def tile_range(bounds, zoom, grid=LEGACY_LUNAR_GRID):
    return grid.tile_range(bounds, zoom)


def display_pixels(values, low, high):
    # PDS saturation values are valid dark/bright terrain; zero is invalid.
    valid = (values > 0) & (values <= 32767)
    gray = np.rint(
        np.clip((values.astype(np.float32) - low) / (high - low), 0, 1) * 255
    ).astype(np.uint8)
    gray[values == 1] = 0
    gray[values == 32767] = 255
    return gray, valid.astype(np.uint8) * 255


def footprint_mask(polygons, bounds, size=1024, grid=LEGACY_LUNAR_GRID):
    """Sample a MultiPolygon using scanlines, keeping holes and islands."""
    west, south, east, north = bounds
    longitudes, latitudes = grid.pixel_coordinates(bounds, size)
    mask = np.zeros((size, size), dtype=bool)
    for polygon in polygons:
        inside = np.zeros_like(mask)
        for ring in polygon:
            points = np.asarray(ring)
            first, second = points[:-1], points[1:]
            for row, latitude in enumerate(latitudes):
                crosses = (first[:, 1] > latitude) != (second[:, 1] > latitude)
                a, b = first[crosses], second[crosses]
                intersections = np.sort(
                    a[:, 0]
                    + (latitude - a[:, 1]) * (b[:, 0] - a[:, 0]) / (b[:, 1] - a[:, 1])
                )
                inside[row] ^= (
                    np.searchsorted(intersections, longitudes, side="right") % 2 == 1
                )
        mask |= inside
    return mask


def build_preview(
    project_path: Path,
    source_root: Path,
    detail_root: Path,
    work_root: Path,
    output_root: Path,
):
    project = tomllib.loads(project_path.read_text())
    if (
        project["format_version"] not in {1, 2}
        or project["kind"] != "sparse-detail-preview"
    ):
        raise ValueError("Expected sparse-detail-preview format 1 or 2")
    grid = (
        LEGACY_LUNAR_GRID
        if project["format_version"] == 1
        else TileGrid(project["grid"]["projection"], project["grid"]["radius_metres"])
    )
    if grid.radius_metres != project["radius_metres"]:
        raise ValueError("Preview body and grid radii differ")
    if not (0 <= project["minimum_zoom"] <= project["context_maximum_zoom"]):
        raise ValueError("Invalid context zoom range")
    if project["display_dn_range"][0] >= project["display_dn_range"][1]:
        raise ValueError("Display endpoints must increase")
    for directory in (work_root, output_root):
        directory.mkdir(parents=True, exist_ok=True)
    (output_root / "product.json").unlink(missing_ok=True)
    atomic_write_json(
        output_root / "state.json", {"status": "building", "startedAt": utc_now()}
    )
    crs = (project_path.parent / project["target_crs"]).resolve()
    if project["format_version"] == 2:
        validate_grid_reference(crs, grid)
    bounds = area_bounds(
        project["latitude"],
        project["longitude"],
        project["extent_km"],
        project["radius_metres"],
    )
    versions = tool_versions()
    commands = []

    def run(argv):
        result = run_command(argv)
        # Evidence is portable: use logical root labels instead of local paths.
        roots = [
            (source_root, "<source>"),
            (work_root, "<work>"),
            (output_root, "<output>"),
            (crs.parent, "<crs>"),
        ]

        def portable(arg):
            for root, replacement in roots:
                arg = str(arg).replace(str(root), replacement)
            return arg

        commands.append({"argv": [portable(a) for a in argv], "stderr": result.stderr})

    sources = []
    inputs = []
    for specification in project["context_sources"]:
        stem = specification["stem"]
        label = source_root / f"{stem}.lbl"
        image = source_root / f"{stem}.img"
        if image.stat().st_size != 10800 * 10800 * 2:
            raise ValueError(f"Incomplete Kaguya source: {stem}")
        info, _ = gdalinfo(label)
        if (
            info["size"] != [10800, 10800]
            or len(info["bands"]) != 1
            or info["bands"][0]["type"] != "UInt16"
        ):
            raise ValueError(f"Unexpected Kaguya dimensions or encoding: {stem}")
        for suffix, path in [("img", image), ("lbl", label)]:
            inputs.append(
                {
                    "url": specification["url"].removesuffix(".img") + f".{suffix}",
                    "sha256": sha256_file(path),
                    "bytes": path.stat().st_size,
                }
            )
        # Normalize masks before interpolation; never average PDS sentinels.
        raster = np.memmap(image, dtype=">u2", mode="r", shape=(10800, 10800))
        binary = work_root / f"{stem}.display.bin"
        display = np.memmap(binary, dtype="u1", mode="w+", shape=(2, 10800, 10800))
        for row in range(0, 10800, 512):
            gray, alpha = display_pixels(
                raster[row : row + 512], *project["display_dn_range"]
            )
            display[0, row : row + 512] = gray
            display[1, row : row + 512] = alpha
        display.flush()
        del display, raster
        gt = info["geoTransform"]
        srs = escape(info["coordinateSystem"]["wkt"])
        vrt = work_root / f"{stem}.vrt"
        bands = "".join(
            f'<VRTRasterBand dataType="Byte" band="{b + 1}" subClass="VRTRawRasterBand"><ColorInterp>{color}</ColorInterp>'
            f'<SourceFilename relativeToVRT="1">{binary.name}</SourceFilename><ImageOffset>{b * 10800 * 10800}</ImageOffset>'
            "<PixelOffset>1</PixelOffset><LineOffset>10800</LineOffset><ByteOrder>LSB</ByteOrder></VRTRasterBand>"
            for b, color in enumerate(("Gray", "Alpha"))
        )
        vrt.write_text(
            f'<VRTDataset rasterXSize="10800" rasterYSize="10800"><SRS>{srs}</SRS><GeoTransform>{",".join(map(str, gt))}</GeoTransform>{bands}</VRTDataset>'
        )
        sources.append(vrt)

    # Mosaic first so a coarse pixel spanning source boundaries averages all
    # four inputs together rather than overwriting the previous source's sample.
    mosaic = work_root / "context.vrt"
    run(["gdalbuildvrt", "-q", "-overwrite", str(mosaic), *map(str, sources)])
    levels = []
    sample_size = 1024
    sample_x = (
        bounds[0]
        + (np.arange(sample_size) + 0.5) * (bounds[2] - bounds[0]) / sample_size
    )
    sample_y = (
        bounds[3]
        - (np.arange(sample_size) + 0.5) * (bounds[3] - bounds[1]) / sample_size
    )
    checksum_lines = []
    tile_size = project["tile_size"]
    for zoom in range(project["minimum_zoom"], project["context_maximum_zoom"] + 1):
        x0, y0, x1, y1 = tile_range(bounds, zoom, grid)
        width, height = (x1 - x0 + 1) * tile_size, (y1 - y0 + 1) * tile_size
        northwest = grid.tile_bounds(zoom, x0, y0)
        southeast = grid.tile_bounds(zoom, x1, y1)
        geographic_extent = [northwest[0], southeast[1], southeast[2], northwest[3]]
        extent = grid.project_bounds(geographic_extent)
        raw = work_root / f"z{zoom}.bin"
        run(
            [
                "gdalwarp",
                "-q",
                "-overwrite",
                "-wm",
                "128",
                "-t_srs",
                str(crs),
                "-te",
                *map(str, extent),
                "-ts",
                str(width),
                str(height),
                "-r",
                "average",
                "-srcalpha",
                "-dstalpha",
                "-of",
                "ENVI",
                "-co",
                "INTERLEAVE=BSQ",
                str(mosaic),
                str(raw),
            ]
        )
        data = np.memmap(raw, mode="r", dtype="u1", shape=(2, height, width))
        if zoom == project["context_maximum_zoom"]:
            columns = (
                (sample_x - geographic_extent[0])
                / (geographic_extent[2] - geographic_extent[0])
                * width
            ).astype(int)
            top, bottom = (
                grid.normalized_y(geographic_extent[3]),
                grid.normalized_y(geographic_extent[1]),
            )
            rows = (
                (grid.normalized_y(sample_y) - top) / (bottom - top) * height
            ).astype(int)
            context_mask = data[1, rows[:, None], columns[None, :]] > 0
        present = []
        valid_pixels = 0
        inside_pixels = 0
        for y in range(y0, y1 + 1):
            _, latitudes = grid.pixel_coordinates(
                grid.tile_bounds(zoom, x0, y), tile_size
            )
            for x in range(x0, x1 + 1):
                longitudes, _ = grid.pixel_coordinates(
                    grid.tile_bounds(zoom, x, y), tile_size
                )
                pixels = np.array(
                    data[
                        :,
                        (y - y0) * tile_size : (y - y0 + 1) * tile_size,
                        (x - x0) * tile_size : (x - x0 + 1) * tile_size,
                    ]
                )
                inside = (
                    (latitudes[:, None] >= bounds[1])
                    & (latitudes[:, None] <= bounds[3])
                    & (longitudes[None, :] >= bounds[0])
                    & (longitudes[None, :] <= bounds[2])
                )
                pixels[1, ~inside] = 0
                inside_pixels += int(np.count_nonzero(inside))
                if not pixels[1].any():
                    continue
                valid_pixels += int(np.count_nonzero(pixels[1]))
                relative = f"imagery/{zoom}/{x}/{y}.png"
                path = output_root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_suffix(".partial.png")
                Image.fromarray(np.moveaxis(pixels, 0, -1)).save(
                    temporary, compress_level=3
                )
                temporary.replace(path)
                checksum_lines.append(f"{sha256_file(path)}  {relative}\n")
                present.append([x, y])
        del data
        levels.append(
            {
                "zoom": zoom,
                "tiles": present,
                "tileCount": len(present),
                "validPixels": valid_pixels,
                "insidePixels": inside_pixels,
                "coveragePercent": valid_pixels / inside_pixels * 100
                if inside_pixels
                else 0,
            }
        )
        print(f"z{zoom}: {len(present)} tiles", flush=True)

    import json

    details = []
    for specification in sorted(
        project["detail_sources"], key=lambda source: source["priority"]
    ):
        path = detail_root / specification["metadata"]
        region = json.loads(path.read_text())
        details.append(
            {
                "id": specification["id"],
                "bounds": area_bounds(
                    project["latitude"],
                    project["longitude"],
                    specification["extent_km"],
                    project["radius_metres"],
                ),
                "maximumZoom": specification["maximum_zoom"],
                "priority": specification["priority"],
                "region": region,
            }
        )
        inputs.append(
            {"metadata": specification["metadata"], "sha256": sha256_file(path)}
        )
    claimed = np.zeros((sample_size, sample_size), dtype=bool)
    resolution_coverage = []
    for detail in reversed(details):
        mask = footprint_mask(detail["region"]["coverage"], bounds, sample_size)
        west, south, east, north = detail["bounds"]
        mask &= (
            (sample_y[:, None] >= south)
            & (sample_y[:, None] <= north)
            & (sample_x[None, :] >= west)
            & (sample_x[None, :] <= east)
        )
        resolution_coverage.append(
            {
                "id": detail["id"],
                "metresPerPixel": detail["region"]["metresPerPixel"],
                "coveragePercent": float(np.mean(mask & ~claimed) * 100),
            }
        )
        claimed |= mask
    resolution_coverage.append(
        {
            "id": "context",
            "metresPerPixel": project["context_metres_per_pixel"],
            "coveragePercent": float(np.mean(context_mask & ~claimed) * 100),
        }
    )
    resolution_coverage.append(
        {
            "id": "global-fallback",
            "metresPerPixel": 100,
            "coveragePercent": float(np.mean(~context_mask & ~claimed) * 100),
        }
    )
    repository = Path(__file__).parents[3]
    code_hashes = {
        str(path.relative_to(repository)): sha256_file(path)
        for path in [
            Path(__file__),
            Path(__file__).with_name("cli.py"),
            Path(__file__).with_name("util.py"),
            Path(__file__).with_name("grid.py"),
            Path(__file__).with_name("toolchain.py"),
            repository / "uv.lock",
            repository / "pyproject.toml",
        ]
    }
    git = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=Path(__file__).parents[3],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    identity = identity_sha256(
        {
            "project": project,
            "inputs": inputs,
            "producerGitSha": git,
            "versions": versions,
            "codeHashes": code_hashes,
        }
    )
    manifest = {
        "formatVersion": project["format_version"],
        "grid": grid.metadata(),
        "kind": "sparse-detail-preview",
        "id": project["product_id"],
        "identity": identity,
        "status": "local-preview",
        "bounds": bounds,
        "tileSize": tile_size,
        "minimumZoom": project["minimum_zoom"],
        "maximumZoom": max(d["maximumZoom"] for d in details),
        "contextMaximumZoom": project["context_maximum_zoom"],
        "contextMetresPerPixel": project["context_metres_per_pixel"],
        "contextSourceUrl": "https://darts.isas.jaxa.jp/en/datasets/sln-l-tc-5-ortho-map-seamless-v2.0",
        "pathTemplate": "imagery/{z}/{x}/{y}.png",
        "levels": levels,
        "details": details,
        "resolutionCoverage": resolution_coverage,
        "coverageMethod": "Approximate source footprint fractions across the 100 km region, sampled at 1024 by 1024 cell centres with declared priorities. NAC masks come from the 20 m browse products. This estimates geometric coverage, not uniform image quality or illumination.",
        "inputs": inputs,
        "recipe": project,
        "producerGitSha": git,
        "producerCodeHashes": code_hashes,
        "producerDirty": bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=Path(__file__).parents[3],
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        ),
        "tools": versions,
        "commands": commands,
        "createdAt": utc_now(),
        "method": f"Materialized {grid.projection} XYZ Kaguya context with pixel alpha. Referenced NAC archive pyramids are clipped to inner bounds and regridded on demand; lower-resolution context is retained in holes and above its maximum zoom. No seam correction. This is scratch preview evidence, not a publication.",
    }
    (output_root / "checksums.sha256").write_text("".join(sorted(checksum_lines)))
    atomic_write_json(output_root / "product.json", manifest)
    atomic_write_json(
        output_root / "state.json",
        {"status": "complete", "identity": identity, "completedAt": utc_now()},
    )
    return {
        "identity": identity,
        "tileCount": sum(level["tileCount"] for level in levels),
    }
