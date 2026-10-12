import json

import numpy as np
import pytest
from PIL import Image

from foundinspace.textures.grid import TileGrid
from foundinspace.textures.preview_tiles import (
    archive_tiers,
    archive_url,
    prepare_preview_tiles,
    regrid_detail,
    sample_parent,
    validate_preview_tiles,
)
from foundinspace.textures.util import atomic_write_json, identity_sha256, sha256_file


def test_mercator_archive_rows_sample_latitude_without_stretching(tmp_path):
    grid = TileGrid("web-mercator", 1737400)
    path = tmp_path / "gradient.jpg"
    data = np.repeat(np.arange(128, dtype=np.uint8)[:, None] * 2, 128, axis=1)
    Image.fromarray(data).save(path, quality=100)
    bounds = [-180, -90, 180, 90]
    detail = {
        "bounds": bounds,
        "region": {
            "bounds": bounds,
            "width": 128,
            "height": 128,
            "tileSize": 128,
            "zoomifyUrl": "https://example.org/pyramid",
            "coverage": [
                [[[-180, -90], [180, -90], [180, 90], [-180, 90], [-180, -90]]]
            ],
        },
    }
    pixels, mask = regrid_detail(
        detail, grid.tile_bounds(0, 0, 0), 16, lambda _: path, grid=grid
    )
    _, latitude = grid.pixel_coordinates(grid.tile_bounds(0, 0, 0), 16)
    expected = (90 - latitude) / 180 * 128 * 2 - 1
    assert np.asarray(pixels)[:, 8] == pytest.approx(expected, abs=1)
    assert np.asarray(mask).min() == 255
    assert pixels.getpixel((8, 3)) < 40  # A geographic stretch would give about 56.


def region():
    return {
        "bounds": [0, 0, 90, 45],
        "width": 8,
        "height": 8,
        "tileSize": 4,
        "zoomifyUrl": "https://example.org/pyramid",
        "coverage": [
            [
                [[0, 0], [90, 0], [90, 45], [0, 45], [0, 0]],
                [[22.5, 11.25], [45, 11.25], [45, 33.75], [22.5, 33.75], [22.5, 11.25]],
            ]
        ],
    }


def test_regrid_keeps_valid_black_and_masked_holes(tmp_path):
    image = tmp_path / "black.jpg"
    Image.new("L", (4, 4), 0).save(image)
    detail = {"region": region(), "bounds": [0, 0, 90, 45]}
    pixels, mask = regrid_detail(detail, [0, 0, 90, 45], 8, lambda _: image)
    assert np.asarray(pixels).max() == 0
    assert np.asarray(mask)[0, 0] == 255
    assert np.asarray(mask)[3, 3] == 0
    detail["bounds"] = [200, 0, 210, 45]
    assert (
        regrid_detail(
            detail,
            [0, 0, 90, 45],
            8,
            lambda _: pytest.fail("Fetching disconnected detail"),
        )
        is None
    )


def test_parent_crop_preserves_xyz_orientation(tmp_path):
    pixels = np.zeros((8, 8), dtype=np.uint8)
    pixels[:4, :4], pixels[:4, 4:] = 10, 20
    pixels[4:, :4], pixels[4:, 4:] = 30, 40
    path = tmp_path / "parent.png"
    Image.fromarray(pixels).save(path)
    assert sample_parent(path, (3, 5, 2), (2, 2, 1), 8).getpixel((4, 4)) == 20
    assert sample_parent(path, (3, 4, 3), (2, 2, 1), 8).getpixel((4, 4)) == 30


def test_prepare_opaque_tiles_omits_boundaries_and_preserves_holes(tmp_path):
    preview = tmp_path / "preview"
    output = tmp_path / "output"
    cache = tmp_path / "archive"
    preview.mkdir()
    cache.mkdir()
    for x, alpha in [(2, 255), (3, 0)]:
        path = preview / f"imagery/2/{x}/1.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("LA", (8, 8), (77, alpha)).save(path)
    detail = {
        "id": "detail",
        "priority": 100,
        "maximumZoom": 2,
        "bounds": [0, 0, 90, 45],
        "region": region(),
    }
    product = {
        "kind": "sparse-detail-preview",
        "formatVersion": 1,
        "tileSize": 8,
        "pathTemplate": "imagery/{z}/{x}/{y}.png",
        "levels": [{"zoom": 2, "tiles": [[2, 1], [3, 1]]}],
        "details": [detail],
    }
    atomic_write_json(preview / "product.json", product)
    tiers = archive_tiers(detail["region"])
    for y in range(2):
        for x in range(2):
            url = archive_url(detail["region"], tiers, 1, x, y)
            key = identity_sha256(url)
            path = cache / f"{key}.jpg"
            Image.new("L", (4, 4), 0).save(path)
            atomic_write_json(
                cache / f"{key}.json", {"url": url, "sha256": sha256_file(path)}
            )
    result = prepare_preview_tiles(preview, cache, output)
    assert result["tileCount"] == 2
    manifest = json.loads((output / "product.json").read_text())
    assert manifest["sources"][0]["levels"][0]["tiles"] == [[2, 1]]
    with Image.open(output / "detail/2/2/1.png") as image:
        assert image.mode == "L"
        assert image.getpixel((0, 0)) == 0  # Valid black replaces context.
        assert image.getpixel((3, 3)) == 77  # A footprint hole retains context.
    assert json.loads((output / "state.json").read_text())["status"] == "complete"
    assert len(manifest["inputs"]["archiveTiles"]) == 4
    assert validate_preview_tiles(output)["tileCount"] == 2
    prepared = output / "detail/2/2/1.png"
    original = prepared.read_bytes()
    prepared.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="checksum changed"):
        validate_preview_tiles(output)
    prepared.write_bytes(original)
    # An offline repeat uses authenticated cached inputs.
    assert (
        prepare_preview_tiles(preview, cache, output)["identity"] == result["identity"]
    )
    assert (
        prepare_preview_tiles(preview, cache, output, allow_download=True)["identity"]
        == result["identity"]
    )
    (cache / f"{key}.jpg").write_bytes(b"changed")
    with pytest.raises(ValueError, match="identity changed"):
        prepare_preview_tiles(preview, cache, output)
    assert not (output / "product.json").exists()
    assert json.loads((output / "state.json").read_text())["status"] == "building"
