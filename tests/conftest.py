from __future__ import annotations

import hashlib
from pathlib import Path

import pytest


@pytest.fixture
def project_factory(tmp_path: Path):
    def make(*, admitted: bool = False, maximum_zoom: int = 2) -> tuple[Path, Path]:
        project_dir = tmp_path / "definition"
        sources_dir = project_dir / "sources"
        crs_dir = project_dir / "crs"
        sources_dir.mkdir(parents=True, exist_ok=True)
        crs_dir.mkdir(parents=True, exist_ok=True)
        target_crs = crs_dir / "moon.wkt"
        source_crs = sources_dir / "source.wkt"
        target_crs.write_text("target crs", encoding="utf-8")
        source_crs.write_text("source crs", encoding="utf-8")
        payload = b"source-pixels"
        expected = ""
        source_crs_field = ""
        if admitted:
            expected = f"""
[expected]
size_bytes = {len(payload)}
sha256 = "{hashlib.sha256(payload).hexdigest()}"
width = 8
height = 4
band_count = 1
data_type = "Byte"
geo_transform = [-4.0, 1.0, 0.0, 2.0, 0.0, -1.0]
nodata = "absent"
mask_flags = ["ALL_VALID"]
scale = "absent"
offset = "absent"
"""
            source_crs_field = 'source_crs = "source.wkt"\n'
        acquisition = sources_dir / "source.toml"
        acquisition.write_text(
            f"""
format_version = 1
status = "{"admitted" if admitted else "candidate"}"
source_id = "source-a"
title = "Synthetic source"
landing_page = "https://example.test/source"
url = "https://example.test/source.tif"
filename = "source.tif"
citation = "Synthetic test fixture."
{source_crs_field}{expected}
""".lstrip(),
            encoding="utf-8",
        )
        project_path = project_dir / "project.toml"
        project_path.write_text(
            f"""
format_version = 1
product_id = "synthetic-v1"

[target]
id = "moon"
crs = "crs/moon.wkt"
longitude_range = [-180.0, 180.0]
latitude_range = [-90.0, 90.0]

[[sources]]
id = "source-a"
acquisition = "sources/source.toml"
priority = 100

[composite]
policy = "priority"
missing_pixel = 0

[product]
kind = "display-texture"
bounds = [-180.0, -90.0, 180.0, 90.0]
maximum_zoom = {maximum_zoom}
tile_size = 512
reprojection_resampling = "bilinear"
pyramid_resampling = "average"
pixel_type = "uint8"
channels = "grayscale"
format = "png"
opaque = true
path_template = "imagery/{{z}}/{{x}}/{{y}}.png"
""".lstrip(),
            encoding="utf-8",
        )
        return project_path, acquisition

    return make
