"""Generate scalar lunar heights and exercise the installed elevation CLI."""

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_bounds


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="New scratch directory outside Git")
    args = parser.parse_args()
    root = args.output.resolve()
    repository = Path(__file__).resolve().parents[2]
    if root == repository or repository in root.parents:
        parser.error("keep generated rasters and evidence outside the repository")
    root.mkdir(parents=True, exist_ok=False)
    radius = 1737400
    half = math.pi * radius
    rows, columns = np.indices((64, 64))
    # Change this formula; values are metres relative to the declared sphere.
    heights = (columns * 4.17 - rows * 3.81).astype("float32")
    source = root / "global.tif"
    with rasterio.open(
        source,
        "w",
        driver="GTiff",
        width=64,
        height=64,
        count=1,
        dtype="float32",
        crs=f"+proj=merc +R={radius} +units=m +no_defs",
        transform=from_bounds(-half, -half, half, half, 64, 64),
    ) as target:
        target.write(heights, 1)

    executable = str(Path(sys.executable).with_name("fis-terrain"))

    def run(*arguments, parse_json=True):
        result = subprocess.run(
            [executable, *map(str, arguments)],
            check=True,
            text=True,
            capture_output=True,
        )
        return json.loads(result.stdout) if parse_json else result.stdout

    # Exact admission for our generated fixture, not for an external dataset.
    run("inspect", source, "--output", root / "global.json")
    project = root / "project.toml"
    project.write_text(
        f"""format_version = 1
product_id = "synthetic-elevation-example"
target = "moon"
radius_metres = {radius}
tile_size = 16
global_maximum_zoom = 1
attribution = "Generated synthetic heights; not measured lunar terrain."
[grid]
projection = "web-mercator"
[[sources]]
id = "global"
file = "global.tif"
spec = "global.json"
datum_radius_metres = {radius}
scale_metres = 1
offset_metres = 0
feather_metres = 0
[[details]]
bounds = [-10, -10, 10, 10]
maximum_zoom = 2
"""
    )
    plan = run("plan", project)
    assert plan["tileCount"] == 9
    output = root / "output"
    run("build", project, "--output", output, parse_json=False)
    descriptor = json.loads((output / "elevation/product.json").read_text())
    assert descriptor["encoding"] == {"kind": "terrarium"}
    assert descriptor["elevationBoundsMetres"]["minimum"] < 0
    assert descriptor["elevationBoundsMetres"]["maximum"] > 0
    report = run("validate", output)
    assert report["tileCount"] == 9
    assert report["completeCoverage"]
    assert report["maximumEncodingErrorMetres"] <= 1 / 512
    print(
        json.dumps(
            {"syntheticScratch": True, "output": str(output), "validation": report},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
