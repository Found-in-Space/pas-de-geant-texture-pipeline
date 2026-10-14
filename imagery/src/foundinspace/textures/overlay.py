"""Opt-in matched overlay producer; emits the existing sparse opaque contract."""

from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import numpy as np
import scipy
from PIL import Image
from PIL import __version__ as pillow_version
from scipy.ndimage import map_coordinates

from .grid import TileGrid
from .overlay_sources import (
    ArchiveSource,
    RasterSource,
    ReferenceTiles,
    authenticate,
    local_path,
    source_mask,
)
from .photometry import ALGORITHM, blend_field, decode_srgb, display_pixels, fit_affine
from .preview_tiles import validate_preview_tiles
from .processing import validate_grid_reference
from .toolchain import tool_versions
from .util import atomic_write_json, identity_sha256, sha256_file, utc_now


def load_overlay_project(path):
    project = tomllib.loads(path.read_text())

    def fields(value, required, optional=()):
        missing, unknown = (
            set(required) - value.keys(),
            value.keys() - set(required) - set(optional),
        )
        if missing or unknown:
            raise ValueError(
                f"Overlay project fields: missing={sorted(missing)}, unknown={sorted(unknown)}"
            )

    fields(
        project,
        (
            "format_version",
            "kind",
            "algorithm",
            "tile_size",
            "minimum_zoom",
            "target_crs",
            "reference_descriptor_sha256",
            "grid",
            "matching",
            "sources",
        ),
        ("product_id", "admission_descriptor_sha256"),
    )
    fields(project["grid"], ("projection", "radius_metres"))
    fields(
        project["matching"],
        (
            "calibration_zoom",
            "block_pixels",
            "contrast_fraction",
            "trim_fraction",
            "maximum_canvas_pixels",
        ),
    )
    if Path(project["target_crs"]).is_absolute() or any(
        c in project["target_crs"] for c in ("$", "~")
    ):
        raise ValueError("Target CRS must be a portable project-relative path")
    if project.get("format_version") != 1 or project.get("kind") != "matched-overlay":
        raise ValueError("Expected matched-overlay project format 1")
    if project.get("algorithm") != ALGORITHM:
        raise ValueError("Unsupported overlay matching algorithm")
    grid = TileGrid(project["grid"]["projection"], project["grid"]["radius_metres"])
    if grid.projection != "web-mercator":
        raise ValueError("Matched overlay v1 requires a projected Mercator grid")
    size = project["tile_size"]
    if not isinstance(size, int) or size < 1 or size > 256 or size & (size - 1):
        raise ValueError("Overlay tiles must be powers of two no larger than 256")
    settings = project["matching"]
    for value in (
        project["minimum_zoom"],
        settings["calibration_zoom"],
        settings["block_pixels"],
        settings["maximum_canvas_pixels"],
    ):
        if type(value) is not int:
            raise ValueError("Zoom, block size and canvas budget must be integers")
    if not 0 <= project["minimum_zoom"] <= settings["calibration_zoom"] <= 20:
        raise ValueError("Invalid minimum/calibration zoom")
    if (
        not 1 <= settings["block_pixels"] <= 64
        or not 0 <= settings["contrast_fraction"] <= 1
        or not 0 <= settings["trim_fraction"] < 0.25
    ):
        raise ValueError("Invalid source matching parameters")
    if not 65_536 <= settings["maximum_canvas_pixels"] <= 16_777_216:
        raise ValueError(
            "Calibration canvas budget must be between 65536 and 16777216 pixels"
        )
    sources = project["sources"]
    if (
        not sources
        or len({s["id"] for s in sources}) != len(sources)
        or len({s["priority"] for s in sources}) != len(sources)
    ):
        raise ValueError("Sources need unique IDs and priorities")
    for source in sources:
        if (
            type(source["maximum_zoom"]) is not int
            or type(source["priority"]) is not int
        ):
            raise ValueError("Source zoom and priority must be integers")
        common = (
            "id",
            "kind",
            "priority",
            "credit",
            "bounds",
            "maximum_zoom",
            "blend_metres",
            "inputs",
        )
        fields(
            source,
            (
                *common,
                *(
                    ("encoding", "scale", "valid_range", "rasters")
                    if source["kind"] == "raster"
                    else ("metadata",)
                ),
            ),
            ("quality_mask", "offset", "nodata", "fit_block_pixels")
            if source["kind"] == "raster"
            else ("quality_mask", "fit_block_pixels"),
        )
        fit_block = source.get("fit_block_pixels", settings["block_pixels"])
        if type(fit_block) is not int or not 1 <= fit_block <= 64:
            raise ValueError("Source fit_block_pixels must be an integer from 1 to 64")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", source["id"]):
            raise ValueError("Unsafe source ID")
        west, south, east, north = source["bounds"]
        if not (
            -180 < west < east < 180
            and -grid.latitude_limit < south < north < grid.latitude_limit
        ):
            raise ValueError(
                "Source bounds must fit inside one Mercator world without wrapping"
            )
        if not settings["calibration_zoom"] <= source["maximum_zoom"] <= 20:
            raise ValueError(
                "Source cap must be at least calibration zoom and at most 20"
            )
        if not math.isfinite(source["blend_metres"]) or source["blend_metres"] <= 0:
            raise ValueError("Blend width must be positive projected metres")
        if source["kind"] not in {"raster", "zoomify"}:
            raise ValueError("Unsupported overlay source kind")
        if source["kind"] == "raster":
            if (
                source["encoding"] not in {"srgb", "linear"}
                or not math.isfinite(source["scale"])
                or source["scale"] <= 0
            ):
                raise ValueError("Declare a valid raster encoding and scale")
            if source["valid_range"][0] >= source["valid_range"][1]:
                raise ValueError("Source valid range must increase")
            if not all(
                math.isfinite(value)
                for value in (
                    *source["valid_range"],
                    source.get("offset", 0),
                    *source.get("nodata", []),
                )
            ):
                raise ValueError("Raster range, offset and nodata must be finite")
        for entry in source["inputs"]:
            fields(entry, ("path", "sha256"), ("url",))
            local_path(Path("."), entry["path"])
            if not re.fullmatch("[a-f0-9]{64}", entry["sha256"]):
                raise ValueError("Input needs a SHA-256 digest")
        if "quality_mask" in source:
            fields(source["quality_mask"], ("path", "sha256"))
        for raster in source.get("rasters", []):
            fields(raster, ("path", "size", "data_type"))
            if len(raster["size"]) != 2 or any(
                not isinstance(n, int) or n <= 0 for n in raster["size"]
            ):
                raise ValueError("Raster dimensions must be positive integers")
    return project, grid


class BlendField:
    """Globally aligned mipmaps of correction/weight, shared by every tile."""

    def __init__(self, correction, weight, zoom, origin):
        self.levels = {zoom: (np.stack([correction, weight]), origin)}
        self.zoom = zoom
        for z in range(zoom - 1, -1, -1):
            value, (x, y) = self.levels[z + 1]
            top, left = y % 2, x % 2
            height, width = value.shape[1:]
            value = np.pad(
                value, ((0, 0), (top, (height + top) % 2), (left, (width + left) % 2))
            )
            value = value.reshape(
                2, value.shape[1] // 2, 2, value.shape[2] // 2, 2
            ).mean(axis=(2, 4))
            self.levels[z] = value, (x // 2, y // 2)

    def sample(self, address, size):
        z, x, y = address
        level = min(z, self.zoom)
        data, (ox, oy) = self.levels[level]
        ratio = 2 ** (level - z)
        columns = (x * size + np.arange(size) + 0.5) * ratio - ox - 0.5
        rows = (y * size + np.arange(size) + 0.5) * ratio - oy - 0.5
        yy, xx = np.meshgrid(rows, columns, indexing="ij")
        return tuple(
            map_coordinates(
                value, [yy, xx], order=1, mode="grid-constant", cval=0, prefilter=False
            )
            for value in data
        )


def best_parent(available, address, minimum_zoom):
    """Same resolution-first, then priority ordering as the sparse consumer."""
    z, x, y = address
    for pz in range(z, minimum_zoom - 1, -1):
        parent = pz, x >> (z - pz), y >> (z - pz)
        for tiles in reversed(available):
            if parent in tiles:
                return tiles[parent], parent
    return None


def calibration_canvas(spec, grid, size, settings):
    zoom = settings["calibration_zoom"]
    step = 2 * math.pi * grid.radius_metres / (size * 2**zoom)
    levels = max(0, math.ceil(math.log2(max(1, spec["blend_metres"] / (2 * step)))))
    width = 2 * 2**levels * step
    padding = math.ceil(width / (step * size)) + 1
    x0, y0, x1, y1 = grid.tile_range(spec["bounds"], zoom)
    x0, y0 = x0 - padding, y0 - padding
    count = max(x1 - x0 + 1 + padding, y1 - y0 + 1 + padding)
    pixels = count * size
    if pixels**2 > settings["maximum_canvas_pixels"]:
        raise ValueError(
            "Calibration canvas exceeds budget; choose a coarser calibration zoom or smaller regional project"
        )
    if x0 < 0 or y0 < 0 or x0 + count > 2**zoom or y0 + count > 2**zoom:
        raise ValueError(
            "Calibration halo crosses the supported Mercator world boundary"
        )
    northwest = grid.tile_bounds(zoom, x0, y0)
    southeast = grid.tile_bounds(zoom, x0 + count - 1, y0 + count - 1)
    bounds = [northwest[0], southeast[1], southeast[2], northwest[3]]
    return zoom, x0, y0, count, bounds, levels, step


def build_overlay(
    project_path,
    *,
    source_root,
    archive_root,
    reference_root,
    work_root,
    output_root,
    maximum_zoom=None,
):
    project, grid = load_overlay_project(project_path)
    size, settings = project["tile_size"], project["matching"]
    if (
        maximum_zoom is not None
        and not settings["calibration_zoom"] <= maximum_zoom <= 20
    ):
        raise ValueError("Review cap must be at least calibration_zoom")
    roots = [source_root.resolve(), archive_root.resolve(), reference_root.resolve()]
    output_root, work_root = output_root.resolve(), work_root.resolve()
    for writable in (output_root, work_root):
        if any(
            writable.is_relative_to(root) or root.is_relative_to(writable)
            for root in roots
        ):
            raise ValueError("Work/output roots must be separate from immutable inputs")
    if output_root.is_relative_to(work_root) or work_root.is_relative_to(output_root):
        raise ValueError("Work and output roots must be separate")
    if output_root.exists():
        raise ValueError("Output already exists; use a new immutable product directory")
    crs = (project_path.parent / project["target_crs"]).resolve()
    validate_grid_reference(crs, grid)
    reference = ReferenceTiles(
        reference_root, project["reference_descriptor_sha256"], grid, size
    )
    if reference.minimum > project["minimum_zoom"]:
        raise ValueError("Reference does not reach the overlay minimum zoom")
    raster_bytes, tile_bytes, largest_canvas = 0, 0, 0
    for spec in project["sources"]:
        canvas = calibration_canvas(spec, grid, size, settings)
        largest_canvas = max(largest_canvas, (canvas[3] * size) ** 2)
        raster_bytes += sum(
            math.prod(raster["size"]) * 4 for raster in spec.get("rasters", [])
        )
        cap = (
            min(spec["maximum_zoom"], maximum_zoom)
            if maximum_zoom is not None
            else spec["maximum_zoom"]
        )
        largest_level = 0
        for z in range(project["minimum_zoom"], cap + 1):
            x0, y0, x1, y1 = grid.tile_range(spec["bounds"], z)
            pixels = (x1 - x0 + 1) * (y1 - y0 + 1) * size**2
            tile_bytes += pixels * 1.1
            largest_level = max(largest_level, pixels)
        if spec["kind"] == "raster":
            if largest_level > 1_000_000_000:
                raise ValueError("Raster level exceeds the four-GB staging budget")
            raster_bytes += largest_level * 4
        for entry in spec["inputs"]:
            authenticate(source_root, entry)
        if "quality_mask" in spec:
            authenticate(project_path.parent, spec["quality_mask"])
    disk_budget = int(raster_bytes + tile_bytes + largest_canvas * 8 + 256_000_000)
    for directory in (work_root, output_root.parent):
        probe = directory
        while not probe.exists():
            probe = probe.parent
        if shutil.disk_usage(probe).free < disk_budget:
            raise ValueError(
                f"Insufficient disk space; estimated build budget {disk_budget} bytes"
            )
    versions = {
        **tool_versions(),
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "pillow": pillow_version,
    }
    repository = Path(__file__).parents[3]
    code_files = [
        *Path(__file__).parent.glob("*.py"),
        repository / "uv.lock",
        repository / "pyproject.toml",
    ]
    code_hashes = {
        str(p.relative_to(repository)): sha256_file(p) for p in sorted(code_files)
    }
    run_key = identity_sha256(
        {
            "project": project,
            "crs": sha256_file(crs),
            "code": code_hashes,
            "tools": versions,
            "maximumZoomOverride": maximum_zoom,
        }
    )
    staging = output_root.with_name(output_root.name + ".building")
    if staging.exists():
        state = staging / "state.json"
        if not state.exists() or json.loads(state.read_text()).get("runKey") != run_key:
            raise ValueError(
                "Staging directory belongs to a different run; use a new output directory"
            )
    staging.mkdir(parents=True, exist_ok=True)
    work_root = work_root / run_key
    work_root.mkdir(parents=True, exist_ok=True)
    # A failed retry cannot retain a descriptor advertising complete output.
    (staging / "product.json").unlink(missing_ok=True)
    atomic_write_json(staging / "state.json", {"status": "building", "runKey": run_key})
    atomic_write_json(
        work_root / "preflight.json",
        {
            "runKey": run_key,
            "estimatedDiskBudgetBytes": disk_budget,
            "maximumCanvasPixels": largest_canvas,
            "gdalWarpMemoryMiB": 128,
            "gdalCacheMiB": 128,
        },
    )
    available, sources, checksums, reports, archive_inputs = [], [], [], [], {}

    def underlay(address):
        z, x, y = address
        selected = best_parent(available, address, project["minimum_zoom"])
        if selected is not None:
            path, (pz, px, py) = selected
            factor = 2 ** (z - pz)
            left, top = (
                (x - px * factor) * size / factor,
                (y - py * factor) * size / factor,
            )
            with Image.open(path) as image:
                linear = decode_srgb(np.asarray(image, dtype=np.float32) / 255)
            return np.asarray(
                Image.fromarray(linear).resize(
                    (size, size),
                    Image.Resampling.BILINEAR,
                    box=(left, top, left + size / factor, top + size / factor),
                ),
                dtype=np.float32,
            )
        return reference.sample(grid.tile_bounds(*address), size, z)

    for spec in sorted(project["sources"], key=lambda item: item["priority"]):
        source_id = spec["id"]
        exclusions, mask_evidence = [], None
        if "quality_mask" in spec:
            path = authenticate(project_path.parent, spec["quality_mask"])
            mask_evidence = json.loads(path.read_text())
            if mask_evidence["format_version"] != 1 or mask_evidence[
                "source_inputs_sha256"
            ] != identity_sha256(spec["inputs"]):
                raise ValueError(
                    "Quality mask is not bound to these exact source inputs"
                )
            exclusions = mask_evidence["exclude_multipolygon"]
            for polygon in exclusions:
                if not polygon:
                    raise ValueError(
                        "Quality polygons must contain a closed outer ring"
                    )
                for ring in polygon:
                    points = np.asarray(ring, dtype=np.float64)
                    if (
                        points.ndim != 2
                        or points.shape[1] != 2
                        or len(points) < 4
                        or not np.isfinite(points).all()
                        or not np.array_equal(points[0], points[-1])
                    ):
                        raise ValueError(
                            "Quality masks require finite, closed longitude/latitude rings"
                        )
        reader = (
            RasterSource(spec, source_root, work_root / source_id, crs, grid, versions)
            if spec["kind"] == "raster"
            else ArchiveSource(spec, source_root, archive_root, grid)
        )
        z, x0, y0, count, bounds, levels, step = calibration_canvas(
            spec, grid, size, settings
        )
        pixels = count * size
        base, raw, valid = (
            np.empty((pixels, pixels), np.float32),
            np.zeros((pixels, pixels), np.float32),
            np.zeros((pixels, pixels), bool),
        )
        for row in range(count):
            for column in range(count):
                address = z, x0 + column, y0 + row
                tile_bounds = grid.tile_bounds(*address)
                section = np.s_[
                    row * size : (row + 1) * size, column * size : (column + 1) * size
                ]
                base[section] = underlay(address)
                # One target tile at a time bounds archive read windows.
                if spec["kind"] == "zoomify":
                    raw[section], valid[section] = reader.sample(tile_bounds, size, z)
        if spec["kind"] == "raster":
            raw, valid = reader.sample(bounds, pixels, z)
        valid &= source_mask(spec, bounds, pixels, grid, exclusions)
        fit_block = spec.get("fit_block_pixels", settings["block_pixels"])
        fit = fit_affine(
            raw,
            base,
            valid,
            block_pixels=fit_block,
            contrast_fraction=settings["contrast_fraction"],
            trim_fraction=settings["trim_fraction"],
        )
        corrected = raw * fit["gain"] + fit["offset"]
        blended, extended, weight = blend_field(base, corrected, valid, levels=levels)
        correction = blended - base - weight * (extended - base)
        field = BlendField(correction, weight, z, (x0 * size, y0 * size))
        report = {
            "source": source_id,
            "fit": fit,
            "calibrationBounds": bounds,
            "calibrationPixels": pixels**2,
            "calibrationStepProjectedMetres": step,
            "fitCellProjectedMetres": step * fit_block,
            "blendLevels": levels,
            "broadestBlendProjectedMetres": 2 * 2**levels * step,
            "qualityMask": mask_evidence,
        }
        reports.append(report)
        print(
            f"{source_id}: gain={fit['gain']:.6g}, offset={fit['offset']:.6g}, held-out display MAE={fit['heldoutDisplayMAE']:.3f}",
            flush=True,
        )
        atomic_write_json(work_root / f"{source_id}-matching.json", report)
        del base, raw, valid, corrected, blended, extended, weight, correction
        tiles, level_records = {}, []
        cap = (
            min(spec["maximum_zoom"], maximum_zoom)
            if maximum_zoom is not None
            else spec["maximum_zoom"]
        )
        clipped, rendered = 0, 0
        for zoom in range(project["minimum_zoom"], cap + 1):
            tx0, ty0, tx1, ty1 = grid.tile_range(spec["bounds"], zoom)
            present = []
            for y in range(ty0, ty1 + 1):
                for x in range(tx0, tx1 + 1):
                    address = zoom, x, y
                    bounds = grid.tile_bounds(*address)
                    raw, valid = reader.sample(bounds, size, zoom)
                    valid &= source_mask(spec, bounds, size, grid, exclusions)
                    if not valid.any():
                        continue
                    base = underlay(address)
                    correction, weight = field.sample(address, size)
                    result = np.where(
                        valid,
                        base
                        + correction
                        + weight * (fit["gain"] * raw + fit["offset"] - base),
                        base,
                    )
                    clipped += int(np.count_nonzero((result < 0) | (result > 1)))
                    rendered += result.size
                    relative = f"{source_id}/{zoom}/{x}/{y}.png"
                    path = staging / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    temporary = path.with_suffix(".partial.png")
                    Image.fromarray(display_pixels(result)).save(
                        temporary, compress_level=3
                    )
                    temporary.replace(path)
                    checksums.append(f"{sha256_file(path)}  {relative}\n")
                    tiles[address] = path
                    present.append([x, y])
            level_records.append(
                {"zoom": zoom, "tiles": present, "tileCount": len(present)}
            )
            print(f"{source_id} z{zoom}: {len(present)} tiles", flush=True)
        if not tiles:
            raise ValueError(f"Source produced no valid tiles: {source_id}")
        report["renderedClippingFraction"] = clipped / rendered
        available.append(tiles)
        sources.append(
            {
                "id": source_id,
                "priority": spec["priority"],
                "attribution": spec["credit"],
                "minimumZoom": project["minimum_zoom"],
                "maximumZoom": cap,
                "pathTemplate": f"{source_id}/{{z}}/{{x}}/{{y}}.png",
                "levels": level_records,
            }
        )
        if isinstance(reader, ArchiveSource):
            archive_inputs.update(reader.used)
        del field, reader
    (staging / "checksums.sha256").write_text("".join(sorted(checksums)))
    matching = {
        "algorithm": ALGORITHM,
        "settings": settings,
        "sources": reports,
        "colorSpace": "display-linear arithmetic; sRGB-encoded opaque output; no viewing gamma",
        "nativeDetail": "Shared calibration field plus source detail residual; globally aligned field mipmaps",
        "referenceDescriptorSha256": project["reference_descriptor_sha256"],
    }
    atomic_write_json(staging / "matching.json", matching)
    manifest = {
        "kind": "sparse-opaque-xyz",
        "formatVersion": 2,
        "grid": grid.metadata(),
        "tileSize": size,
        "sources": sources,
        "recipe": project,
        "maximumZoomOverride": maximum_zoom,
        "inputs": {
            "referenceTiles": reference.used,
            "archiveTiles": [archive_inputs[url] for url in sorted(archive_inputs)],
        },
        "matching": matching,
        "matchingReportSha256": sha256_file(staging / "matching.json"),
        "producerGitSha": subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip(),
        "producerDirty": bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=repository,
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        ),
        "producerCodeHashes": code_hashes,
        "targetCrsSha256": sha256_file(crs),
        "tools": versions,
        "payloadManifestSha256": sha256_file(staging / "checksums.sha256"),
        "createdAt": utc_now(),
        "method": ALGORITHM,
        "runKey": run_key,
    }
    manifest["identity"] = identity_sha256(
        {k: v for k, v in manifest.items() if k != "createdAt"}
    )
    atomic_write_json(staging / "product.json", manifest)
    validate_preview_tiles(staging)
    atomic_write_json(
        staging / "state.json",
        {
            "status": "complete",
            "runKey": run_key,
            "identity": manifest["identity"],
            "tileCount": len(checksums),
        },
    )
    staging.rename(output_root)
    return {
        "identity": manifest["identity"],
        "tileCount": len(checksums),
        "sourceCount": len(sources),
    }
