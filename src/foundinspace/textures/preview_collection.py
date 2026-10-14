"""Collect immutable sparse products without resampling their tile pixels."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .preview_tiles import validate_preview_tiles
from .util import atomic_write_json, identity_sha256, sha256_file, utc_now


def collect_preview_tiles(inputs: list[tuple[str, Path]], output_root: Path):
    """Hardlink same-grid products, then fully validate before atomic promotion.

    Inputs and output must share a filesystem. Both are immutable after success;
    the independent source namespaces preserve priority and prevent collisions.
    """
    output_root = output_root.resolve()
    staging = output_root.with_name(output_root.name + ".partial")
    if output_root.exists() or staging.exists():
        raise ValueError("Collection output or staging already exists")
    if not inputs or len({name for name, _ in inputs}) != len(inputs):
        raise ValueError("Collection requires unique named inputs")
    records, sources, checksum_lines = [], [], []
    grid, size, version = None, None, None
    prepared = []
    for name, root in inputs:
        root = root.resolve()
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
            raise ValueError("Invalid collection namespace")
        if output_root.is_relative_to(root) or root.is_relative_to(output_root):
            raise ValueError("Collection output overlaps an input")
        product_path = root / "product.json"
        product = json.loads(product_path.read_text())
        if product["kind"] != "sparse-opaque-xyz" or product["formatVersion"] != 2:
            raise ValueError("Collection inputs require explicit-grid opaque products")
        if product["identity"] != identity_sha256(
            {k: v for k, v in product.items() if k not in {"createdAt", "identity"}}
        ):
            raise ValueError("Input descriptor identity changed")
        if sha256_file(root / "checksums.sha256") != product["payloadManifestSha256"]:
            raise ValueError("Input payload manifest changed")
        if grid is None:
            grid, size, version = (
                product["grid"],
                product["tileSize"],
                product["formatVersion"],
            )
        if product["grid"] != grid or product["tileSize"] != size:
            raise ValueError("Collection inputs have different grids or tile sizes")
        if not isinstance(size, int) or size <= 0 or size > 256 or size & (size - 1):
            raise ValueError("Collection tile size must be a power of two at most 256")
        prepared.append((name, root, product))
        records.append(
            {
                "namespace": name,
                "identity": product["identity"],
                "descriptorSha256": sha256_file(product_path),
                "payloadManifestSha256": product["payloadManifestSha256"],
            }
        )
    staging.mkdir(parents=True)
    for name, root, product in prepared:
        for source in product["sources"]:
            template = source["pathTemplate"]
            if Path(template).is_absolute() or ".." in Path(template).parts:
                raise ValueError("Unsafe input tile path")
            sources.append(
                {
                    **source,
                    "id": f"{name}-{source['id']}",
                    "pathTemplate": f"{name}/{template}",
                }
            )
        evidence = staging / "inputs" / name
        evidence.mkdir(parents=True)
        for filename in ("product.json", "checksums.sha256"):
            os.link(root / filename, evidence / filename)
        for line in (root / "checksums.sha256").read_text().splitlines():
            digest, relative = line.split("  ", 1)
            if Path(relative).is_absolute() or ".." in Path(relative).parts:
                raise ValueError("Unsafe input payload path")
            destination = staging / name / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.link(root / relative, destination)
            checksum_lines.append(f"{digest}  {name}/{relative}\n")
    checksum_path = staging / "checksums.sha256"
    checksum_path.write_text("".join(sorted(checksum_lines)))
    manifest = {
        "kind": "sparse-opaque-xyz",
        "formatVersion": version,
        "grid": grid,
        "tileSize": size,
        "sources": sources,
        "inputs": records,
        "producerCodeSha256": sha256_file(Path(__file__)),
        "method": "Named collection of unchanged immutable same-grid tile products. "
        "Source priorities, zoom caps and pixels are preserved. Shared payload inodes are immutable.",
        "payloadManifestSha256": sha256_file(checksum_path),
        "createdAt": utc_now(),
    }
    manifest["identity"] = identity_sha256(
        {k: v for k, v in manifest.items() if k != "createdAt"}
    )
    atomic_write_json(staging / "product.json", manifest)
    report = validate_preview_tiles(staging)
    atomic_write_json(
        staging / "state.json",
        {
            "status": "complete",
            "identity": manifest["identity"],
            "tileCount": report["tileCount"],
            "completedAt": utc_now(),
        },
    )
    staging.rename(output_root)
    return report
