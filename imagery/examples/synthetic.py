"""Generate a tiny projected gradient and exercise the installed imagery CLI."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from foundinspace.textures.toolchain import gdalinfo, run_command


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="New scratch directory outside Git")
    args = parser.parse_args()
    root = args.output.resolve()
    repository = Path(__file__).resolve().parents[2]
    if root == repository or repository in root.parents:
        parser.error("keep generated rasters and evidence outside the repository")
    root.mkdir(parents=True, exist_ok=False)
    definition = root / "definition"
    definition.mkdir()
    sources = root / "sources"
    sources.mkdir()
    workflow = Path(__file__).resolve().parents[1]
    for name in ("geographic", "mercator"):
        shutil.copyfile(
            workflow / f"resources/crs/moon-{name}-1737400.wkt",
            definition / f"{name}.wkt",
        )
    source_crs = definition / "source.crs"
    source_crs.write_text(
        "+proj=eqc +lat_ts=0 +lat_0=0 +lon_0=0 +R=1737400 +units=m +no_defs +type=crs\n"
    )
    # Change this formula to explore how projected source values become tiles.
    pixels = 20 + np.arange(16)[:, None] * 8 + np.arange(32)[None, :] * 2
    png = sources / "gradient.png"
    Image.fromarray(pixels.astype(np.uint8)).save(png)
    source = sources / "source.tif"
    half = math.pi * 1737400
    run_command(
        (
            "gdal_translate",
            "-of",
            "GTiff",
            "-a_srs",
            str(source_crs),
            "-a_ullr",
            str(-half),
            str(half / 2),
            str(half),
            str(-half / 2),
            str(png),
            str(source),
        )
    )
    metadata, _ = gdalinfo(source)
    expected = {
        "size_bytes": source.stat().st_size,
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "width": 32,
        "height": 16,
        "band_count": 1,
        "data_type": "Byte",
        "geo_transform": metadata["geoTransform"],
        "nodata": "absent",
        "mask_flags": ["ALL_VALID"],
        "scale": "absent",
        "offset": "absent",
    }
    # Admission here is only for the synthetic file just generated, not a
    # shortcut around reviewing the identity and metadata of real sources.
    (definition / "source.toml").write_text(
        """format_version = 1
status = "admitted"
source_id = "synthetic"
title = "Synthetic projected lunar gradient"
landing_page = "https://example.test/synthetic"
url = "https://example.test/source.tif"
filename = "source.tif"
citation = "Generated synthetic example; not observed lunar imagery."
source_crs = "source.crs"
[expected]
"""
        + "\n".join(f"{key} = {json.dumps(value)}" for key, value in expected.items())
        + "\n"
    )
    project = definition / "project.toml"
    project.write_text(
        """format_version = 2
product_id = "synthetic-imagery-example"
[target]
id = "moon"
crs = "mercator.wkt"
geographic_crs = "geographic.wkt"
longitude_range = [-180.0, 180.0]
latitude_range = [-85.0511287798066, 85.0511287798066]
[[sources]]
id = "synthetic"
acquisition = "source.toml"
priority = 100
[composite]
policy = "priority"
missing_pixel = 0
[product]
kind = "display-texture"
bounds = [-180.0, -85.0511287798066, 180.0, 85.0511287798066]
maximum_zoom = 1
tile_size = 16
reprojection_resampling = "bilinear"
pyramid_resampling = "average"
pixel_type = "uint8"
channels = "grayscale"
format = "png"
opaque = true
path_template = "imagery/{z}/{x}/{y}.png"
[grid]
projection = "web-mercator"
radius_metres = 1737400
[base_texture]
width = 32
height = 16
path = "base.png"
resampling = "average"
"""
    )
    executable = str(Path(sys.executable).with_name("pas-de-geant-textures"))

    def run(*arguments: str | Path) -> dict:
        result = subprocess.run(
            [executable, *map(str, arguments)],
            check=True,
            text=True,
            capture_output=True,
        )
        return json.loads(result.stdout)

    work, output, evidence = root / "work", root / "output", root / "evidence"
    run("build-base", project, "--source-root", sources, "--work-root", work)
    run("build-levels", project, "--work-root", work)
    run("emit-tiles", project, "--work-root", work, "--output-root", output)
    report = run(
        "validate-tiles",
        project,
        "--work-root",
        work,
        "--output-root",
        output,
        "--evidence-root",
        evidence,
    )
    assert report["valid"] and report["tile_count"] == 5
    assert report["checks"]["every_level_reconstructs_exactly"]
    assert report["checks"]["base_texture_covers_poles"]
    with Image.open(output / "base.png") as image:
        np.testing.assert_array_equal(np.asarray(image), pixels.astype(np.uint8))
    print(
        json.dumps(
            {"syntheticScratch": True, "output": str(output), "validation": report},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
