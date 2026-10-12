import hashlib
import json
import math
import platform
import subprocess
import tomllib
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path

import numpy as np
import PIL
import rasterio
import scipy
from PIL import Image
from scipy.ndimage import distance_transform_edt

from .acquisition import digest, write_json
from .encoding import decode_terrarium, encode_terrarium
from .grid import addresses, availability, tile_transform
from .source import Source


def load_project(path):
    project = tomllib.loads(Path(path).read_text())
    if (
        project["format_version"] != 1
        or project["grid"]["projection"] != "web-mercator"
    ):
        raise ValueError("Unsupported terrain project/grid")
    for key in ("tile_size", "radius_metres"):
        if (
            not isinstance(project[key], (int, float))
            or not math.isfinite(project[key])
            or project[key] <= 0
        ):
            raise ValueError(f"Invalid {key}")
    if not isinstance(project["tile_size"], int):
        raise ValueError("Tile size must be an integer")
    if (
        not isinstance(project["global_maximum_zoom"], int)
        or project["global_maximum_zoom"] < 0
    ):
        raise ValueError("Invalid global maximum zoom")
    ids = [source["id"] for source in project["sources"]]
    if len(set(ids)) != len(ids) or not ids:
        raise ValueError("Sources require distinct identifiers")
    for source in project["sources"]:
        for key in ("scale_metres", "offset_metres", "feather_metres"):
            if not math.isfinite(source[key]) or (
                key != "offset_metres" and source[key] < 0
            ):
                raise ValueError(f"Invalid source {key}")
        for key in ("file", "spec"):
            if Path(source[key]).is_absolute() or "$" in source[key]:
                raise ValueError(
                    "Source paths must be project-relative without environment expansion"
                )
    for detail in project.get("details", []):
        if (
            not isinstance(detail["maximum_zoom"], int)
            or detail["maximum_zoom"] <= project["global_maximum_zoom"]
        ):
            raise ValueError("Detail must extend the global pyramid")
    availability(project)
    return project


def producer():
    root = Path(__file__).resolve().parents[3]
    files = sorted(
        [
            *root.glob("src/**/*.py"),
            *root.glob("projects/**/*.py"),
            root / "pyproject.toml",
            root / "uv.lock",
        ]
    )
    hashes = {
        str(path.relative_to(root)): digest(path) for path in files if path.is_file()
    }

    def git(*args):
        result = subprocess.run(
            ["git", "-C", str(root), *args], text=True, capture_output=True, check=False
        )
        return result.stdout.strip() if result.returncode == 0 else None

    return {
        "gitSha": git("rev-parse", "HEAD"),
        "dirty": bool(git("status", "--porcelain")),
        "treeSha256": identity(hashes),
        "files": hashes,
        "versions": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "pillow": PIL.__version__,
            "scipy": scipy.__version__,
            "rasterio": rasterio.__version__,
            "gdal": rasterio.__gdal_version__,
            "proj": rasterio.__proj_version__,
        },
    }


def identity(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def composite(sources, transform, size, crs, radius):
    result = np.full((size, size), np.nan, dtype=np.float64)
    overlap = {}
    for source in sources:
        if not source.intersects(transform, size):
            continue
        values = source.sample(transform, size, crs)
        valid = np.isfinite(values)
        shared = valid & np.isfinite(result)
        delta = values[shared] - result[shared]
        overlap[source.config["id"]] = {
            "samples": int(shared.sum()),
            "rmsDifferenceMetres": float(np.sqrt(np.mean(delta**2)))
            if delta.size
            else 0,
            "maximumDifferenceMetres": float(np.max(np.abs(delta)))
            if delta.size
            else 0,
        }
        feather = source.config["feather_metres"]
        if feather and shared.any():
            # A halo at least as wide as the blend means tile boundaries cannot
            # introduce synthetic mask edges into retained output samples.
            # Mercator pixel ground length is projected length*cos(latitude).
            rows = transform.f + (np.arange(size) + 0.5) * transform.e
            latitude = np.arctan(np.sinh(rows / radius))
            distance = (
                distance_transform_edt(np.pad(valid, 1))[1:-1, 1:-1]
                * transform.a
                * np.cos(latitude)[:, None]
            )
            weight = np.clip(distance / feather, 0, 1)
            result[shared] += (values[shared] - result[shared]) * weight[shared]
            result[valid & ~shared] = values[valid & ~shared]
        else:
            result[valid] = values[valid]
    return result, overlap


def sample_tile(project, sources, address):
    radius, pixels = project["radius_metres"], project["tile_size"]
    transform = tile_transform(radius, pixels, *address)
    maximum_feather = max(source.config["feather_metres"] for source in sources)
    north_y, south_y = transform.f, transform.f + pixels * transform.e
    smallest_cosine = 1 / math.cosh(max(abs(north_y), abs(south_y)) / radius)
    halo = math.ceil(maximum_feather / (transform.a * smallest_cosine)) + 2
    transform = tile_transform(radius, pixels, *address, halo=halo)
    crs = f"+proj=merc +R={radius} +units=m +no_defs"
    heights, overlap = composite(sources, transform, pixels + 2 * halo, crs, radius)
    return heights[halo:-halo, halo:-halo], overlap


def tile_record(project, sources, work, address):
    z, x, y = address
    tile = work / "elevation" / str(z) / str(x) / f"{y}.png"
    report = tile.with_suffix(".json")
    previous = json.loads(report.read_text()) if report.exists() else None
    if previous and tile.exists() and digest(tile) == previous["sha256"]:
        return previous
    heights, overlap = sample_tile(project, sources, address)
    rgb = encode_terrarium(heights)
    tile.parent.mkdir(parents=True, exist_ok=True)
    temporary = tile.with_suffix(".part")
    Image.fromarray(rgb).save(temporary, format="PNG")
    with Image.open(temporary) as emitted:
        decoded = decode_terrarium(np.array(emitted))
    error = float(np.max(np.abs(heights - decoded)))
    if error > 1 / 512 + 1e-8:
        raise ValueError("Elevation round-trip exceeds quantization error")
    record = {
        "address": list(address),
        "sha256": digest(temporary),
        "minimumMetres": float(decoded.min()),
        "maximumMetres": float(decoded.max()),
        "maximumEncodingErrorMetres": error,
        "overlap": overlap,
    }
    temporary.replace(tile)
    write_json(report, record)
    return record


def tile_records(project, sources, work, coverage, workers):
    # Retain at most twice the worker count in futures/results. The manifest
    # consumes them in deterministic address order, independent of completion.
    with ThreadPoolExecutor(max_workers=workers) as executor:
        pending = deque()
        for address in addresses(coverage):
            pending.append(
                (address, executor.submit(tile_record, project, sources, work, address))
            )
            if len(pending) >= 2 * workers:
                address, future = pending.popleft()
                yield address, future.result()
        for address, future in pending:
            yield address, future.result()


def build(project_path, output, workers=4):
    if not isinstance(workers, int) or workers <= 0:
        raise ValueError("Worker count must be a positive integer")
    project_path = Path(project_path).resolve()
    output = Path(output).resolve()
    project = load_project(project_path)
    coverage = availability(project)
    source_code = producer()
    with ExitStack() as stack, rasterio.Env(GDAL_CACHEMAX=128 * 1024 * 1024):
        sources = []
        for config in project["sources"]:
            source = Source(config, project_path.parent, project["radius_metres"])
            stack.callback(source.close)
            sources.append(source)
        recipe = {
            "project": project,
            "projectFileSha256": digest(project_path),
            "sources": [source.spec for source in sources],
            "producer": source_code,
            "workers": workers,
        }
        recipe_identity = identity(recipe)
        work = output.with_name(output.name + ".work")
        if output.exists():
            raise ValueError(
                "Completed output already exists; select a new immutable directory"
            )
        work.mkdir(parents=True, exist_ok=True)
        state = work / "recipe.json"
        if state.exists() and json.loads(state.read_text()) != recipe:
            raise ValueError(
                "Resume requires identical project, source bytes and producer tree"
            )
        write_json(state, recipe)
        (work / "project.toml").write_bytes(project_path.read_bytes())
        count, maximum_error, minimum, maximum = 0, 0.0, math.inf, -math.inf
        manifest_path = work / "checksums.sha256"
        with manifest_path.open("w") as manifest:
            for address, record in tile_records(
                project, sources, work, coverage, workers
            ):
                z, x, y = address
                tile = work / "elevation" / str(z) / str(x) / f"{y}.png"
                manifest.write(
                    f"{record['sha256']}  {tile.relative_to(work).as_posix()}\n"
                )
                count += 1
                maximum_error = max(maximum_error, record["maximumEncodingErrorMetres"])
                minimum, maximum = (
                    min(minimum, record["minimumMetres"]),
                    max(maximum, record["maximumMetres"]),
                )
                if count % 100 == 0:
                    print(
                        f"Validated {count} height tiles; latest {z}/{x}/{y}",
                        flush=True,
                    )
        validation = {
            "tileCount": count,
            "maximumEncodingErrorMetres": maximum_error,
            "maximumAllowedEncodingErrorMetres": 1 / 512,
            "completeCoverage": True,
        }
        write_json(work / "validation.json", validation)
        descriptor = {
            "kind": "elevation-xyz",
            "formatVersion": 2,
            "productId": project["product_id"],
            "target": project["target"],
            "grid": {
                "formatVersion": 1,
                "projection": "web-mercator",
                "radiusMetres": project["radius_metres"],
            },
            "units": "metres",
            "verticalDatum": {
                "kind": "reference-surface",
                "radiusMetres": project["radius_metres"],
            },
            "encoding": {"kind": "terrarium"},
            "tileSize": project["tile_size"],
            "maximumZoom": max(
                [
                    coverage["globalMaximumZoom"],
                    *[entry[0] for entry in coverage["ranges"]],
                ]
            ),
            "availability": coverage,
            "elevationBoundsMetres": {"minimum": minimum, "maximum": maximum},
            "attribution": project["attribution"],
            "recipeSha256": recipe_identity,
            "payload": {"sha256": digest(manifest_path), "tileCount": count},
            "resampling": "scalar bilinear, exact transform, unit kernel scale; nearest 1/256 metre encoding",
            "scratch": True,
        }
        descriptor["identity"] = identity(
            {"descriptor": descriptor, "validation": validation}
        )
        write_json(work / "elevation" / "product.json", descriptor)
        work.rename(output)
        print(f"Complete: {count} tiles, identity {descriptor['identity']}", flush=True)
        return descriptor


def validate(output):
    output = Path(output)
    descriptor = json.loads((output / "elevation/product.json").read_text())
    recipe = json.loads((output / "recipe.json").read_text())
    project = recipe["project"]
    expected = iter(addresses(descriptor["availability"]))
    count = 0
    minimum, maximum = math.inf, -math.inf
    for line in (output / "checksums.sha256").open():
        line = line.rstrip("\n")
        checksum, name = line.split("  ", 1)
        parts = Path(name).parts
        if len(parts) != 4 or parts[0] != "elevation" or not parts[-1].endswith(".png"):
            raise ValueError("Invalid manifest address")
        address = int(parts[1]), int(parts[2]), int(Path(parts[3]).stem)
        if address != next(expected, None) or digest(output / name) != checksum:
            raise ValueError("Payload inventory/hash mismatch")
        count += 1
        with Image.open(output / name) as tile:
            if tile.mode != "RGB" or tile.size != (
                project["tile_size"],
                project["tile_size"],
            ):
                raise ValueError("Invalid encoded elevation tile")
            heights = decode_terrarium(np.array(tile))
            minimum, maximum = (
                min(minimum, float(heights.min())),
                max(maximum, float(heights.max())),
            )
    validation = json.loads((output / "validation.json").read_text())
    if (
        next(expected, None) is not None
        or count != validation["tileCount"]
        or count != descriptor["payload"]["tileCount"]
        or descriptor["elevationBoundsMetres"]
        != {"minimum": minimum, "maximum": maximum}
        or count != sum(1 for _ in (output / "elevation").rglob("*.png"))
        or descriptor["payload"]["sha256"] != digest(output / "checksums.sha256")
        or descriptor["recipeSha256"] != identity(recipe)
        or digest(output / "project.toml") != recipe["projectFileSha256"]
    ):
        raise ValueError("Incomplete or unauthenticated product")
    claimed = descriptor.pop("identity")
    wanted = identity({"descriptor": descriptor, "validation": validation})
    if claimed != wanted or descriptor["availability"] != availability(project):
        raise ValueError("Product identity/availability mismatch")
    return validation
