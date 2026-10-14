"""Derive opt-in matched recipes from authenticated Apollo preview descriptors.

This records already-admitted inputs; it does not download or change products.
The curated Apollo 16 exclusion is authored separately and bound to source hashes.
"""

import argparse
import json
from pathlib import Path

from foundinspace.textures.util import identity_sha256, sha256_file


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection-root", type=Path, required=True)
    parser.add_argument("--reference-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    args.output_root.mkdir(parents=True, exist_ok=True)
    for mission in (11, 12, 14, 15, 16, 17):
        path = args.collection_root / f"inputs/apollo{mission}/product.json"
        product = json.loads(path.read_text())
        if product["identity"] != identity_sha256(
            {k: v for k, v in product.items() if k not in {"createdAt", "identity"}}
        ):
            raise ValueError("Input descriptor identity changed")
        preview = product["preview"]
        recipe = preview["recipe"]
        inputs = [
            {
                "path": entry["url"].rsplit("/", 1)[-1],
                "sha256": entry["sha256"],
                "url": entry["url"],
            }
            for entry in preview["inputs"]
            if "url" in entry
        ]
        lines = [
            "format_version = 1",
            'kind = "matched-overlay"',
            'algorithm = "linear-huber-multiscale-v1"',
            f'product_id = "apollo{mission}-matched-overlay-v1"',
            "tile_size = 256",
            "minimum_zoom = 8",
            'target_crs = "../../../resources/crs/moon-mercator-1737400.wkt"',
            f'reference_descriptor_sha256 = "{sha256_file(args.reference_root / "product.json")}"',
            f'admission_descriptor_sha256 = "{sha256_file(path)}"',
            "",
            "[grid]",
            'projection = "web-mercator"',
            "radius_metres = 1737400",
            "",
            "[matching]",
            "calibration_zoom = 10",
            "block_pixels = 12",
            *(
                [
                    "# Full-resolution review: the default floor crushed NAC shadow detail.",
                    "contrast_fraction = 0.25",
                ]
                if mission == 15
                else ["contrast_fraction = 0.75"]
            ),
            "trim_fraction = 0.02",
            "maximum_canvas_pixels = 16777216",
            "",
            "[[sources]]",
            'id = "context"',
            'kind = "raster"',
            "priority = 0",
            'credit = "JAXA/SELENE · Kaguya"',
            f"bounds = {json.dumps(preview['bounds'])}",
            f"maximum_zoom = {recipe['context_maximum_zoom']}",
            "blend_metres = 8192",
            'encoding = "linear"',
            "scale = 0.001",
            "offset = 0",
            "valid_range = [1, 32767]",
            "nodata = [0]",
        ]
        mask = args.output_root / "apollo16-quality-mask.json"
        if mission == 16 and mask.exists():
            data = json.loads(mask.read_text())
            if data["source_inputs_sha256"] != identity_sha256(inputs):
                raise ValueError(
                    "Curated mask no longer matches the admitted Apollo 16 sources"
                )
            lines.append(
                f'quality_mask = {{ path = "{mask.name}", sha256 = "{sha256_file(mask)}" }}'
            )
        for entry in inputs:
            lines += [
                "",
                "[[sources.inputs]]",
                *[f"{key} = {json.dumps(value)}" for key, value in entry.items()],
            ]
        for source in recipe["context_sources"]:
            lines += [
                "",
                "[[sources.rasters]]",
                f'path = "{source["stem"]}.lbl"',
                "size = [10800, 10800]",
                'data_type = "UInt16"',
            ]
        for detail in preview["details"]:
            entry = next(
                i
                for i in preview["inputs"]
                if i.get("metadata")
                == next(
                    d["metadata"]
                    for d in recipe["detail_sources"]
                    if d["id"] == detail["id"]
                )
            )
            lines += [
                "",
                "[[sources]]",
                f'id = "{detail["id"]}"',
                'kind = "zoomify"',
                *(["fit_block_pixels = 4"] if detail["id"] == "landing" else []),
                f"priority = {detail['priority']}",
                'credit = "NASA/GSFC/ASU · LROC"',
                f"bounds = {json.dumps(detail['bounds'])}",
                f"maximum_zoom = {detail['maximumZoom']}",
                "blend_metres = 2048",
                f'metadata = "{entry["metadata"]}"',
                "",
                "[[sources.inputs]]",
                f'path = "{entry["metadata"]}"',
                f'sha256 = "{entry["sha256"]}"',
            ]
        (args.output_root / f"apollo{mission}.toml").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
