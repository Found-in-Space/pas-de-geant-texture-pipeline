import json
import math

import numpy as np
import pytest
import rasterio
from PIL import Image
from rasterio.transform import from_bounds

from foundinspace.terrain.acquisition import write_json
from foundinspace.terrain.build import build, composite, load_project, validate
from foundinspace.terrain.encoding import decode_terrarium, encode_terrarium
from foundinspace.terrain.grid import addresses, availability, tile_transform
from foundinspace.terrain.source import Source, inspect_source

RADIUS = 1737400
CRS = f"+proj=merc +R={RADIUS} +units=m +no_defs"


def raster(tmp_path, name, values, bounds=None, nodata=None):
    half = math.pi * RADIUS
    bounds = bounds or [-half, -half, half, half]
    path = tmp_path / name
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=values.shape[1],
        height=values.shape[0],
        count=1,
        dtype=values.dtype,
        crs=CRS,
        nodata=nodata,
        transform=from_bounds(*bounds, values.shape[1], values.shape[0]),
    ) as output:
        output.write(values, 1)
    write_json(path.with_suffix(".json"), inspect_source(path))
    return path


def source_config(name, feather=0, **extra):
    return {
        "id": name,
        "file": f"{name}.tif",
        "spec": f"{name}.json",
        "datum_radius_metres": RADIUS,
        "scale_metres": 1,
        "offset_metres": 0,
        "feather_metres": feather,
        **extra,
    }


def project(tmp_path, details=True):
    (tmp_path / "project.toml").write_text(
        f"""format_version = 1
product_id = "numeric-fixture"
target = "moon"
radius_metres = {RADIUS}
tile_size = 16
global_maximum_zoom = 1
attribution = "Synthetic scalar test"
[grid]
projection = "web-mercator"
[[sources]]
id = "global"
file = "global.tif"
spec = "global.json"
datum_radius_metres = {RADIUS}
scale_metres = 1
offset_metres = 0
feather_metres = 0
"""
        + (
            """[[details]]
bounds = [-10, -10, 10, 10]
maximum_zoom = 2
"""
            if details
            else ""
        )
    )
    return tmp_path / "project.toml"


def test_quantization_preserves_negative_zero_extreme_and_byte_carries():
    heights = np.array(
        [[-32768, -256.001, -1 / 256, 0, 1 / 256, 255.999, 32767 + 255 / 256]]
    )
    decoded = decode_terrarium(encode_terrarium(heights))
    assert np.max(np.abs(heights - decoded)) <= 1 / 512
    for invalid in (np.nan, np.inf, -32769, 32768):
        with pytest.raises(ValueError):
            encode_terrarium(np.array([[invalid]]))


def test_real_build_roundtrip_and_tamper_detection(tmp_path):
    # Nonconstant heights straddle encoded byte boundaries, including zero.
    rows, columns = np.indices((64, 64))
    raster(tmp_path, "global.tif", (columns * 4.17 - rows * 3.81).astype("float32"))
    output = tmp_path / "tiles"
    descriptor = build(project(tmp_path), output)
    assert descriptor["encoding"] == {"kind": "terrarium"}
    assert validate(output)["tileCount"] == 9
    assert descriptor["elevationBoundsMetres"]["minimum"] < 0
    assert descriptor["elevationBoundsMetres"]["maximum"] > 0
    png = output / "elevation/2/2/2.png"
    with Image.open(png) as image:
        assert image.mode == "RGB"
        assert np.ptp(decode_terrarium(np.array(image))) > 20
    png.write_bytes(b"damaged")
    with pytest.raises(ValueError, match="hash"):
        validate(output)


def test_masks_feather_heights_and_do_not_invent_zero(tmp_path):
    raster(tmp_path, "global.tif", np.full((32, 32), -250.0, dtype="float32"))
    overlay = np.full((32, 32), -100.0, dtype="float32")
    overlay[:, :12] = -9999
    raster(tmp_path, "detail.tif", overlay, nodata=-9999)
    feather = math.pi * RADIUS / 32 * 8
    sources = [
        Source(source_config("global"), tmp_path, RADIUS),
        Source(source_config("detail", feather), tmp_path, RADIUS),
    ]
    try:
        transform = tile_transform(RADIUS, 32, 0, 0, 0)
        heights, overlap = composite(sources, transform, 32, CRS, RADIUS)
        assert heights[16, 4] == -250
        assert -250 < heights[16, 12] < -100
        assert heights[16, 25] == -100
        assert overlap["detail"]["maximumDifferenceMetres"] == 150
        assert np.isfinite(heights).all()
    finally:
        for source in sources:
            source.close()


def test_admission_rejects_changed_bytes_and_vertical_datum(tmp_path):
    path = raster(tmp_path, "global.tif", np.ones((32, 32), dtype="float32"))
    with pytest.raises(ValueError, match="datum"):
        Source(source_config("global", datum_radius_metres=1), tmp_path, RADIUS)
    with path.open("ab") as output:
        output.write(b"changed")
    with pytest.raises(ValueError, match="mismatch"):
        Source(source_config("global"), tmp_path, RADIUS)


def test_adjacent_tile_windows_match_a_single_numeric_warp(tmp_path):
    rows, columns = np.indices((128, 128))
    raster(
        tmp_path, "global.tif", (np.sin(columns / 9) * 12 + rows / 7).astype("float32")
    )
    source = Source(source_config("global"), tmp_path, RADIUS)
    try:
        transform = tile_transform(RADIUS, 32, 2, 1, 1)
        together = source.sample(transform, 64, CRS)
        first = source.sample(transform, 32, CRS)
        second = source.sample(tile_transform(RADIUS, 32, 2, 2, 1), 32, CRS)
        np.testing.assert_allclose(first, together[:32, :32], atol=1e-8)
        np.testing.assert_allclose(second, together[:32, 32:], atol=1e-8)
    finally:
        source.close()


def test_sparse_ranges_are_complete_deduplicated_and_xyz_oriented(tmp_path):
    p = load_project(project(tmp_path))
    coverage = availability(p)
    assert coverage["ranges"] == [[2, 1, 1, 2, 2]]
    p["details"].append(p["details"][0])
    tiles = list(addresses(availability(p)))
    assert len(tiles) == len(set(tiles)) == 9


def test_descriptor_semantics_are_authenticated(tmp_path):
    raster(tmp_path, "global.tif", np.ones((32, 32), dtype="float32"))
    output = tmp_path / "tiles"
    build(project(tmp_path, details=False), output)
    path = output / "elevation/product.json"
    descriptor = json.loads(path.read_text())
    descriptor["verticalDatum"]["radiusMetres"] = 6378137
    write_json(path, descriptor)
    with pytest.raises(ValueError, match="identity"):
        validate(output)


def test_registered_raw_samples_match_independent_bilinear_heights_at_wrap_and_latitudes(
    tmp_path,
):
    width, height = 512, 256
    rows, columns = np.indices((height, width))
    values = np.rint(20000 + 8000 * np.sin(columns / 7) * np.cos(rows / 9)).astype(
        "uint16"
    )
    path = tmp_path / "global.tif"
    with rasterio.open(
        path, "w", driver="GTiff", width=width, height=height, count=1, dtype="uint16"
    ) as ds:
        ds.write(values, 1)
    spec = inspect_source(path)
    spec["registration"] = {
        "crs": f"+proj=longlat +R={RADIUS} +no_defs",
        "transform": [360 / width, 0, -180, 0, -180 / height, 90],
    }
    write_json(path.with_suffix(".json"), spec)
    source = Source(
        source_config("global", scale_metres=0.5, offset_metres=-10000),
        tmp_path,
        RADIUS,
    )
    try:
        actual = source.sample(tile_transform(RADIUS, 512, 1, 0, 0), 512, CRS)
        for row in (3, 100, 256, 400, 511):
            for column in (0, 1, 100, 256, 510):
                longitude = -180 + (column + 0.5) / 1024 * 360
                latitude = math.degrees(
                    math.atan(math.sinh(math.pi * (1 - 2 * (row + 0.5) / 1024)))
                )
                sx = np.clip((longitude + 180) / 360 * width - 0.5, 0, width - 1)
                sy = np.clip((90 - latitude) / 180 * height - 0.5, 0, height - 1)
                x, y = math.floor(sx), math.floor(sy)
                ax, ay = sx - x, sy - y
                expected = (
                    (values[y, x] * (1 - ax) + values[y, x + 1] * ax) * (1 - ay)
                    + (values[y + 1, x] * (1 - ax) + values[y + 1, x + 1] * ax) * ay
                ) * 0.5 - 10000
                assert actual[row, column] == pytest.approx(expected, abs=1e-7)
    finally:
        source.close()
