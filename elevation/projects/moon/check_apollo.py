"""Compare prepared pixel centres independently with native LROC neighbours."""

import argparse
import json
import math
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from rasterio.warp import transform
from rasterio.windows import Window

from foundinspace.terrain.acquisition import digest, write_json
from foundinspace.terrain.encoding import decode_terrarium

SITES = {
    11: (0.67416, 23.47314),
    12: (-3.0128, -23.4219),
    14: (-3.64589, -17.47194),
    15: (26.13239, 3.6333),
    16: (-8.9734, 15.5011),
    17: (20.1911, 30.7723),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--product", type=Path, required=True)
    parser.add_argument("--sources", type=Path, default=Path(".cache/sources"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    descriptor = json.loads((args.product / "elevation/product.json").read_text())
    recipe = json.loads((args.product / "recipe.json").read_text())
    reports = []
    radius, pixels = descriptor["grid"]["radiusMetres"], descriptor["tileSize"]
    geographic = f"+proj=longlat +R={radius} +no_defs"
    for mission, (latitude, longitude) in SITES.items():
        z = 13 if mission == 17 else 15
        n = 2**z
        cx = (longitude + 180) / 360 * n * pixels
        cy = (
            (1 - math.asinh(math.tan(math.radians(latitude))) / math.pi)
            / 2
            * n
            * pixels
        )
        source = args.sources / f"apollo{mission}.tif"
        source_digest = digest(source)
        spec = next(
            spec
            for spec in recipe["sources"]
            if spec.get("sourceUrl", "").endswith(f"NAC_DTM_APOLLO{mission}")
        )
        if spec["sha256"] != source_digest:
            raise ValueError("Reference source changed since production")
        errors = []
        samples = []
        decoded_tiles = {}
        with rasterio.open(source) as native:
            for dx in (-16, -8, 0, 8, 16):
                for dy in (-16, -8, 0, 8, 16):
                    column, row = math.floor(cx) + dx, math.floor(cy) + dy
                    tile_x, px = divmod(column, pixels)
                    tile_y, py = divmod(row, pixels)
                    lon = (column + 0.5) / (pixels * n) * 360 - 180
                    lat = math.degrees(
                        math.atan(
                            math.sinh(math.pi * (1 - 2 * (row + 0.5) / (pixels * n)))
                        )
                    )
                    xs, ys = transform(geographic, native.crs, [lon], [lat])
                    u, v = (~native.transform) @ (xs[0], ys[0])
                    u, v = u - 0.5, v - 0.5
                    left, top = math.floor(u), math.floor(v)
                    neighbours = native.read(
                        1, window=Window(left, top, 2, 2), masked=True
                    )
                    if (
                        neighbours.shape != (2, 2)
                        or np.ma.getmaskarray(neighbours).any()
                    ):
                        raise ValueError(
                            f"Reference point outside native DTM: Apollo {mission}"
                        )
                    # This small window also proves the sample is outside the
                    # declared 128 m transition, so native height is expected.
                    margin = math.ceil(128 / abs(native.transform.a)) + 2
                    mask = native.read_masks(
                        1,
                        window=Window(
                            left - margin, top - margin, 2 * margin + 2, 2 * margin + 2
                        ),
                        boundless=True,
                    )
                    if (mask == 0).any():
                        continue
                    ax, ay = u - left, v - top
                    values = neighbours.astype(np.float64)
                    expected = float(
                        (values[0, 0] * (1 - ax) + values[0, 1] * ax) * (1 - ay)
                        + (values[1, 0] * (1 - ax) + values[1, 1] * ax) * ay
                    )
                    key = z, tile_x, tile_y
                    if key not in decoded_tiles:
                        with Image.open(
                            args.product / f"elevation/{z}/{tile_x}/{tile_y}.png"
                        ) as png:
                            decoded_tiles[key] = decode_terrarium(np.array(png))
                    actual = float(decoded_tiles[key][py, px])
                    error = abs(actual - expected)
                    if error > 1 / 512 + 1e-7:
                        raise ValueError(
                            f"Native height mismatch at Apollo {mission}: {error} m"
                        )
                    errors.append(error)
                    samples.append(
                        {
                            "tile": list(key),
                            "pixel": [px, py],
                            "nativeMetres": expected,
                            "decodedMetres": actual,
                        }
                    )
        if not errors:
            raise ValueError(
                f"No unblended native reference samples at Apollo {mission}"
            )
        reports.append(
            {
                "mission": mission,
                "sourceSha256": source_digest,
                "samples": samples,
                "maximumHeightErrorMetres": max(errors),
            }
        )
    result = {
        "productIdentity": descriptor["identity"],
        "checkerSha256": digest(__file__),
        "method": "Independent inverse-CRS coordinates and bilinear interpolation of four native Float32 neighbours at prepared pixel centres; only unblended interior samples",
        "sites": reports,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.output, result)
    print(
        json.dumps(
            {
                "sites": len(reports),
                "samples": sum(len(site["samples"]) for site in reports),
                "maximumHeightErrorMetres": max(
                    site["maximumHeightErrorMetres"] for site in reports
                ),
            }
        )
    )


if __name__ == "__main__":
    main()
