"""Prepare the Apollo recipe from authenticated native files and PDS windows.

Run with uv from the repository root. Source rasters and generated project state
are local scratch. This adapter is reusable as an example for another area;
the production CLI has no Apollo-specific behavior.
"""

import argparse
import json
import math
import os
import re
import shutil
from pathlib import Path

import rasterio
from rasterio.merge import merge
from rasterio.warp import transform_bounds

from foundinspace.terrain.acquisition import acquire_grid_window, digest, write_json
from foundinspace.terrain.source import inspect_source

RADIUS = 1737400
SITES = {
    11: (0.67416, 23.47314),
    12: (-3.0128, -23.4219),
    14: (-3.64589, -17.47194),
    15: (26.13239, 3.6333),
    16: (-8.9734, 15.5011),
    17: (20.1911, 30.7723),
}
PDS_BASE = "https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/data/sldem2015/tiles/float_img"
GEOGRAPHIC = f"+proj=longlat +R={RADIUS} +no_defs"


def label_value(text, key):
    match = re.search(rf"^\s*{key}\s*=\s*([-+0-9.eE]+)", text, re.MULTILINE)
    if not match:
        raise ValueError(f"Missing PDS label value: {key}")
    return float(match[1])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path, default=Path(".cache/sources"))
    parser.add_argument(
        "--project", type=Path, default=Path(".cache/apollo-project/project.toml")
    )
    parser.add_argument("--global-source", type=Path, required=True)
    args = parser.parse_args()
    args.sources.mkdir(parents=True, exist_ok=True)
    args.project.parent.mkdir(parents=True, exist_ok=True)
    global_path = args.sources / "lola.tif"
    if (
        digest(args.global_source)
        != "0f40bce8b42864deddb6943a38474879e691d5b20647aa5e54c2612b23106499"
    ):
        raise ValueError("Unexpected admitted NASA SVS 64 ppd source")
    if not global_path.exists():
        shutil.copyfile(args.global_source, global_path)
    spec = inspect_source(global_path)
    if (
        spec["metadata"]["size"] != [23040, 11520]
        or spec["metadata"]["dtype"] != "uint16"
        or spec["metadata"]["crs"] is not None
    ):
        raise ValueError("Unexpected LOLA source registration/type")
    spec["registration"] = {
        "crs": GEOGRAPHIC,
        "transform": [1 / 64, 0, -180, 0, -1 / 64, 90],
        "evidence": "https://svs.gsfc.nasa.gov/4720/",
        "pixelEdges": True,
    }
    spec["sourceUrl"] = (
        "https://svs.gsfc.nasa.gov/vis/a000000/a004700/a004720/ldem_64_uint.tif"
    )
    write_json(args.sources / "lola.json", spec)
    sources = [("lola", 0.5, -10000, 0)]
    details = []
    for mission, (latitude, longitude) in SITES.items():
        context_bounds = [
            longitude - 1.5,
            latitude - 1.5,
            longitude + 1.5,
            latitude + 1.5,
        ]
        west = 315 if longitude < 0 else 0
        hemi_ranges = [(0, 30, "00n_30n"), (-30, 0, "30s_00s")]
        parts = []
        receipts = []
        for south, north, hemi in hemi_ranges:
            lower, upper = max(context_bounds[1], south), min(context_bounds[3], north)
            if lower >= upper:
                continue
            stem = f"sldem2015_512_{hemi}_{west:03}_{west + 45:03}_float"
            label = (args.sources / f"{stem}.lbl").read_text()
            # Require the published native layout and units before network work.
            if (
                label_value(label, "LINE_SAMPLES") != 23040
                or label_value(label, "LINES") != 15360
                or label_value(label, "MAP_RESOLUTION") != 512
                or label_value(label, "A_AXIS_RADIUS") != 1737.4
                or not re.search(r"UNIT\s*=\s*KILOMETER", label)
                or not re.search(r"SAMPLE_TYPE\s*=\s*PC_REAL", label)
            ):
                raise ValueError("Unexpected SLDEM2015 label contract")
            native_longitude = longitude if longitude >= 0 else longitude + 360
            x = math.floor((native_longitude - 1.5 - west) * 512)
            right = math.ceil((native_longitude + 1.5 - west) * 512)
            y = math.floor((north - upper) * 512)
            bottom = math.ceil((north - lower) * 512)
            window = {
                "url": f"{PDS_BASE}/{stem}.img",
                "dtype": "<f4",
                "size": [23040, 15360],
                "window": [x, y, right - x, bottom - y],
                "header_bytes": 0,
                "nodata": None,
                "crs": GEOGRAPHIC,
                "transform": [
                    1 / 512,
                    0,
                    west if longitude >= 0 else west - 360,
                    0,
                    -1 / 512,
                    north,
                ],
                "longitudeShiftDegrees": 0 if longitude >= 0 else -360,
                "label": {
                    "file": f"{stem}.lbl",
                    "sha256": digest(args.sources / f"{stem}.lbl"),
                },
            }
            path = args.sources / f"sldem-apollo{mission}-{hemi}.tif"
            receipt = acquire_grid_window(window, path)
            receipts.append(receipt)
            parts.append(path)
            print(f"Acquired SLDEM native window: Apollo {mission} {hemi}", flush=True)
        context = args.sources / f"sldem-apollo{mission}.tif"
        if not context.exists():
            temporary = context.with_suffix(".part.tif")
            datasets = [rasterio.open(part) for part in parts]
            try:
                merge(
                    datasets,
                    dst_path=temporary,
                    mem_limit=128,
                    dst_kwds={"tiled": True, "compress": "deflate"},
                )
            finally:
                for dataset in datasets:
                    dataset.close()
            temporary.replace(context)
        context_spec = inspect_source(context)
        context_spec["acquisition"] = receipts
        context_spec["evidence"] = [
            part for receipt in receipts for part in receipt["ranges"]
        ]
        context_spec["evidence"].extend(
            receipt["spec"]["label"] for receipt in receipts
        )
        context_spec["conversion"] = (
            "native kilometres above 1737.4 km sphere; multiply by 1000; no radius offset added"
        )
        write_json(context.with_suffix(".json"), context_spec)
        sources.append((context.stem, 1000, 0, 128))
        # Include the whole acquired footprint so outer emitted tiles reach the
        # mask edge's transition to the global fallback.
        with rasterio.open(context) as ds:
            details.append((list(ds.bounds), 9))
        dtm = args.sources / f"apollo{mission}.tif"
        label = (args.sources / f"apollo{mission}.lbl").read_text()
        if label_value(label, "A_AXIS_RADIUS") != 1737.4 or not math.isclose(
            label_value(label, "MAP_SCALE"), 5 if mission == 17 else 2, abs_tol=1e-9
        ):
            raise ValueError("Unexpected LROC DTM body/sample spacing")
        dtm_spec = inspect_source(dtm)
        dtm_spec["acquisition"] = json.loads(
            dtm.with_suffix(".tif.receipt.json").read_text()
        )
        if dtm_spec["sha256"] != dtm_spec["acquisition"]["sha256"]:
            raise ValueError("DTM bytes changed since acquisition")
        dtm_spec["evidence"] = [
            {
                "file": f"apollo{mission}.{ext}",
                "sha256": digest(args.sources / f"apollo{mission}.{ext}"),
            }
            for ext in ("lbl", "html")
        ] + [
            {
                "file": f"apollo{mission}-readme.txt",
                "sha256": digest(args.sources / f"apollo{mission}-readme.txt"),
            }
        ]
        dtm_spec["sourceUrl"] = (
            f"https://data.lroc.im-ldi.com/lroc/view_rdr/NAC_DTM_APOLLO{mission}"
        )
        dtm_spec["conversion"] = (
            "native metres above 1737.4 km sphere; nodata only; confidence map not used to filter heights"
        )
        write_json(dtm.with_suffix(".json"), dtm_spec)
        with rasterio.open(dtm) as ds:
            bounds = transform_bounds(ds.crs, GEOGRAPHIC, *ds.bounds, densify_pts=21)
            details.append((list(bounds), 12 if mission == 17 else 14))
    # All context layers precede every local DTM; list order is priority.
    sources.extend((f"apollo{mission}", 1, 0, 128) for mission in SITES)
    source_prefix = Path(
        os.path.relpath(args.sources.resolve(), args.project.parent.resolve())
    ).as_posix()
    lines = [
        "format_version = 1",
        'product_id = "moon-apollo-terrain-256-v1"',
        'target = "moon"',
        f"radius_metres = {RADIUS}",
        "tile_size = 256",
        "global_maximum_zoom = 7",
        'attribution = "NASA/GSFC/MIT LOLA; JAXA/SELENE; NASA/GSFC/Arizona State University LROC"',
        "[grid]",
        'projection = "web-mercator"',
    ]
    for name, scale, offset, feather in sources:
        lines.extend(
            [
                "[[sources]]",
                f'id = "{name}"',
                f'file = "{source_prefix}/{name}.tif"',
                f'spec = "{source_prefix}/{name}.json"',
                f"datum_radius_metres = {RADIUS}",
                f"scale_metres = {scale}",
                f"offset_metres = {offset}",
                f"feather_metres = {feather}",
            ]
        )
    for bounds, zoom in details:
        lines.extend(["[[details]]", f"bounds = {bounds}", f"maximum_zoom = {zoom + 1}"])
    args.project.write_text("\n".join(lines) + "\n")
    print(f"Prepared controlled scratch project: {args.project}", flush=True)


if __name__ == "__main__":
    main()
