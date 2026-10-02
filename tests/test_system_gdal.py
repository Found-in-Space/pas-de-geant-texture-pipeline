from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from foundinspace.textures.processing import build_base, build_levels
from foundinspace.textures.project import load_project
from foundinspace.textures.tiles import emit_tiles, validate_tiles
from foundinspace.textures.toolchain import gdalinfo, run_command

pytestmark = pytest.mark.skipif(
    not all(
        shutil.which(name)
        for name in (
            "gdal_create",
            "gdalinfo",
            "gdalwarp",
            "gdal_translate",
            "gdal_retile.py",
        )
    ),
    reason="system GDAL command-line tools are not installed",
)


def test_reviewed_moon_crs_validates_with_system_gdal() -> None:
    root = Path(__file__).resolve().parents[1]
    crs = root / "resources/crs/moon-geographic-1737400.wkt"

    result = run_command(("gdalsrsinfo", "-V", str(crs)))

    assert "Validate Succeeds" in result.stdout


def test_small_real_gdal_base_and_direct_pyramid(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    definition = tmp_path / "definition"
    source_specs = definition / "sources"
    crs_dir = definition / "crs"
    source_root = tmp_path / "source"
    source_specs.mkdir(parents=True)
    crs_dir.mkdir()
    source_root.mkdir()
    target_crs = crs_dir / "moon.wkt"
    target_crs.write_text(
        (repository / "resources/crs/moon-geographic-1737400.wkt").read_text(),
        encoding="utf-8",
    )
    source_crs = source_specs / "source.crs"
    source_crs.write_text(
        "+proj=eqc +lat_ts=0 +lat_0=0 +lon_0=0 +R=1737400 "
        "+units=m +no_defs +type=crs\n",
        encoding="utf-8",
    )
    source = source_root / "source.tif"
    run_command(
        (
            "gdal_create",
            "-of",
            "GTiff",
            "-outsize",
            "32",
            "16",
            "-bands",
            "1",
            "-ot",
            "Byte",
            "-burn",
            "42",
            "-a_srs",
            str(source_crs),
            "-a_ullr",
            "-5458203.076",
            "2729101.538",
            "5458203.076",
            "-2729101.538",
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
    (source_specs / "source.toml").write_text(
        """
format_version = 1
status = "admitted"
source_id = "synthetic"
title = "Synthetic projected Moon"
landing_page = "https://example.test/synthetic"
url = "https://example.test/synthetic.tif"
filename = "source.tif"
citation = "Generated test fixture."
source_crs = "source.crs"

[expected]
""".lstrip()
        + "\n".join(f"{key} = {json.dumps(value)}" for key, value in expected.items())
        + "\n",
        encoding="utf-8",
    )
    project_path = definition / "project.toml"
    project_path.write_text(
        """
format_version = 1
product_id = "synthetic-gdal-v1"

[target]
id = "moon"
crs = "crs/moon.wkt"
longitude_range = [-180.0, 180.0]
latitude_range = [-90.0, 90.0]

[[sources]]
id = "synthetic"
acquisition = "sources/source.toml"
priority = 100

[composite]
policy = "priority"
missing_pixel = 0

[product]
kind = "display-texture"
bounds = [-180.0, -90.0, 180.0, 90.0]
maximum_zoom = 1
tile_size = 16
reprojection_resampling = "bilinear"
pyramid_resampling = "average"
pixel_type = "uint8"
channels = "grayscale"
format = "png"
opaque = true
path_template = "imagery/{z}/{x}/{y}.png"
""".lstrip(),
        encoding="utf-8",
    )
    project = load_project(project_path)
    work_root = tmp_path / "work"
    output_root = tmp_path / "output"
    evidence_root = tmp_path / "evidence"

    build_base(project, source_root=source_root, work_root=work_root)
    build_levels(project, work_root=work_root)
    emitted = emit_tiles(project, work_root=work_root, output_root=output_root)
    validation = validate_tiles(
        project,
        work_root=work_root,
        output_root=output_root,
        evidence_root=evidence_root,
    )

    base_metadata, _ = gdalinfo(work_root / "levels/1.tif")
    lower_metadata, _ = gdalinfo(work_root / "levels/0.tif")
    assert base_metadata["size"] == [32, 32]
    assert lower_metadata["size"] == [16, 16]
    assert base_metadata["bands"][0]["type"] == "Byte"
    assert lower_metadata["bands"][0]["type"] == "Byte"
    assert emitted["output"]["tile_count"] == 5
    assert validation["valid"] is True
    assert validation["tile_count"] == 5
    assert validation["checks"]["every_level_reconstructs_exactly"] is True
    assert len(list((output_root / "imagery").rglob("*.png"))) == 5
