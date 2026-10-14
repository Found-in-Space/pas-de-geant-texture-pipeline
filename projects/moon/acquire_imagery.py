"""Acquire the declared Apollo context images and registered NAC evidence.

Use --discover-only first. Large transfers are resumable under incoming/ and
move into raw/ only after size, encoding and registration checks. This adapter
does not create a catalog publication or change any running viewer.
"""

import argparse
import json
import re
import shutil
import subprocess
import tomllib
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from foundinspace.textures.toolchain import gdalinfo
from foundinspace.textures.util import atomic_write_json, sha256_file, utc_now


def transfer(
    url, destination, *, byte_range=None, expected_hash=None, expected_bytes=None
):
    receipt = destination.with_suffix(destination.suffix + ".receipt.json")
    if destination.exists() and receipt.exists():
        record = json.loads(receipt.read_text())
        if record["url"] != url or record["sha256"] != sha256_file(destination):
            raise ValueError(f"Changed acquired source: {destination.name}")
        if expected_hash and record["sha256"] != expected_hash:
            raise ValueError(f"Source differs from registered metadata: {url}")
        return record
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".partial")
    headers = destination.with_suffix(destination.suffix + ".headers")
    command = [
        "curl",
        "-fLsS",
        "--retry",
        "5",
        "--retry-delay",
        "3",
        "--connect-timeout",
        "30",
        "--speed-time",
        "120",
        "--speed-limit",
        "1024",
        "-D",
        str(headers),
        "-o",
        str(partial),
    ]
    if byte_range:
        command += ["--range", byte_range]
    else:
        command += ["--continue-at", "-"]
    subprocess.run([*command, url], check=True)
    if expected_bytes is not None and partial.stat().st_size != expected_bytes:
        raise ValueError(f"Unexpected source size: {destination.name}")
    digest = sha256_file(partial)
    if expected_hash and digest != expected_hash:
        raise ValueError(f"Source differs from registered metadata: {url}")
    partial.replace(destination)
    record = {
        "url": url,
        "sha256": digest,
        "bytes": destination.stat().st_size,
        "byteRange": byte_range,
        "retrievedAt": utc_now(),
    }
    atomic_write_json(receipt, record)
    return record


def validate_label(path, stem):
    label = path.read_text()
    expected = {
        "PRODUCT_ID": f'"{stem}"',
        "DATA_SET_ID": '"SLN-L-TC-5-ORTHO-MAP-SEAMLESS-V2.0"',
        "TARGET_NAME": '"MOON"',
        "LINES": "10800",
        "LINE_SAMPLES": "10800",
        "SAMPLE_TYPE": "MSB_UNSIGNED_INTEGER",
        "SAMPLE_BITS": "16",
        "MAP_PROJECTION_TYPE": '"SIMPLE CYLINDRICAL"',
        "A_AXIS_RADIUS": "1737.400 <km>",
    }
    for key, value in expected.items():
        match = re.search(rf"^\s*{key}\s*=\s*(.*?)\s*$", label, re.M)
        if match is None or match[1] != value:
            raise ValueError(f"Unexpected {key} in {stem}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--metadata-root", type=Path, required=True)
    parser.add_argument("--missions", type=int, nargs="+", default=[12, 14, 15, 16, 17])
    parser.add_argument("--discover-only", action="store_true")
    args = parser.parse_args()
    root = args.data_root.resolve()
    if not root.is_relative_to("/data"):
        raise ValueError("This local acquisition must use the persistent /data volume")
    run = root / "runs/surfaces" / args.run_id
    incoming = root / "incoming/surfaces/moon" / args.run_id
    raw = root / "raw/surfaces/moon" / args.run_id
    evidence = run / "acquisition"
    for directory in (incoming, raw, evidence, run / "metadata"):
        directory.mkdir(parents=True, exist_ok=True)
    sources = {}
    recipes = []
    for mission in args.missions:
        project = (
            Path(__file__).parent / f"apollo{mission}-preview-mercator-v2/preview.toml"
        )
        recipe = tomllib.loads(project.read_text())
        recipes.append(
            {"mission": mission, "sha256": sha256_file(project), "recipe": recipe}
        )
        for source in recipe["context_sources"]:
            sources[source["stem"]] = source
        destination = run / "recipes" / f"apollo{mission}" / "preview.toml"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(project, destination)
        for detail in recipe["detail_sources"]:
            filename = detail["metadata"]
            metadata = args.metadata_root / filename
            region = json.loads(metadata.read_text())
            shutil.copyfile(metadata, run / "metadata" / filename)
            for index, item in enumerate(region["inputs"]):
                if "sha256" not in item:
                    continue  # Canonical GDAL metadata is already pinned in the descriptor.
                byte_range = item.get("byteRange")
                expected_bytes = None
                if byte_range:
                    start, end = map(int, byte_range.split("-"))
                    expected_bytes = end - start + 1
                name = item["url"].rsplit("/", 1)[-1]
                target = evidence / f"apollo{mission}" / f"{index}-{name}"
                transfer(
                    item["url"],
                    target,
                    byte_range=byte_range,
                    expected_hash=item["sha256"],
                    expected_bytes=expected_bytes,
                )
                if name == "ImageProperties.xml":
                    properties = ET.parse(target).getroot().attrib
                    if (
                        int(properties["WIDTH"]),
                        int(properties["HEIGHT"]),
                        int(properties["TILESIZE"]),
                    ) != (region["width"], region["height"], region["tileSize"]):
                        raise ValueError("Archive pyramid dimensions changed")
            print(f"Verified Apollo {mission} NAC registration evidence", flush=True)
    for stem, source in sources.items():
        label = raw / f"{stem}.lbl"
        candidate = incoming / label.name
        if not label.exists():
            transfer(source["url"].removesuffix(".img") + ".lbl", candidate)
            validate_label(candidate, stem)
            candidate.replace(label)
            for suffix in (".receipt.json", ".headers"):
                candidate.with_suffix(candidate.suffix + suffix).replace(
                    label.with_suffix(label.suffix + suffix)
                )
        validate_label(label, stem)
    free = shutil.disk_usage(root).free
    plan = {
        "createdAt": utc_now(),
        "recipes": recipes,
        "contextSources": list(sources.values()),
        "rawImageBytes": len(sources) * 10800 * 10800 * 2,
        "minimumFreeBytes": 35_000_000_000,
        "freeBytes": free,
        "tileSize": 256,
        "projection": "web-mercator",
    }
    atomic_write_json(evidence / "plan.json", plan)
    print(
        json.dumps(
            {
                key: value
                for key, value in plan.items()
                if key not in {"recipes", "contextSources"}
            }
        ),
        flush=True,
    )
    if free < plan["minimumFreeBytes"]:
        raise ValueError(
            "Insufficient free space for acquisition, working rasters and prepared tiles"
        )
    if args.discover_only:
        return

    def acquire(source):
        stem = source["stem"]
        target = raw / f"{stem}.img"
        candidate = incoming / target.name
        if not target.exists():
            record = transfer(
                source["url"], candidate, expected_bytes=10800 * 10800 * 2
            )
            # GDAL must see the matching detached label before source admission.
            shutil.copyfile(raw / f"{stem}.lbl", incoming / f"{stem}.lbl")
            info, _ = gdalinfo(incoming / f"{stem}.lbl")
            if (
                info["size"] != [10800, 10800]
                or len(info["bands"]) != 1
                or info["bands"][0]["type"] != "UInt16"
            ):
                raise ValueError(f"Unexpected raster metadata: {stem}")
            atomic_write_json(evidence / f"{stem}.gdalinfo.json", info)
            candidate.replace(target)
            for suffix in (".receipt.json", ".headers"):
                candidate.with_suffix(candidate.suffix + suffix).replace(
                    target.with_suffix(target.suffix + suffix)
                )
        else:
            record = transfer(source["url"], target, expected_bytes=10800 * 10800 * 2)
        print(
            f"Acquired {stem}: {record['bytes']} bytes; sha256 {record['sha256']}",
            flush=True,
        )
        return record

    with ThreadPoolExecutor(max_workers=2) as executor:
        records = list(executor.map(acquire, sources.values()))
    atomic_write_json(
        evidence / "sources.json",
        {"status": "complete", "sources": records, "completedAt": utc_now()},
    )


if __name__ == "__main__":
    main()
