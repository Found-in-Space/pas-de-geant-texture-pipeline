import io
import json
import urllib.error
from email.message import Message

import numpy as np
import pytest
from PIL import Image

from foundinspace.textures.grid import TileGrid
from foundinspace.textures.preview_tiles import (
    archive_tiers,
    archive_url,
    detail_archive_urls,
    download_archive_tile,
    prepare_preview_tiles,
    regrid_detail,
    sample_parent,
    validate_preview_tiles,
)
from foundinspace.textures.util import atomic_write_json, identity_sha256, sha256_file


def test_archive_download_retries_timeout_before_writing(tmp_path, monkeypatch):
    calls = []

    class Response(io.BytesIO):
        headers = Message()
        headers["Content-Type"] = "image/jpeg"

    def fetch(url, timeout):
        calls.append(url)
        if len(calls) == 1:
            raise urllib.error.URLError(TimeoutError())
        return Response(b"complete image response")

    monkeypatch.setattr("urllib.request.urlopen", fetch)
    monkeypatch.setattr(
        "foundinspace.textures.preview_tiles.time.sleep", lambda _: None
    )
    path = tmp_path / "tile.partial"
    download_archive_tile("https://example.org/tile.jpg", path)
    assert len(calls) == 2
    assert path.read_bytes() == b"complete image response"


@pytest.mark.parametrize("code,attempts", [(404, 1), (503, 4)])
def test_archive_http_retries_are_bounded(tmp_path, monkeypatch, code, attempts):
    calls = []

    def fetch(url, timeout):
        calls.append(url)
        raise urllib.error.HTTPError(url, code, "fixture", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", fetch)
    monkeypatch.setattr(
        "foundinspace.textures.preview_tiles.time.sleep", lambda _: None
    )
    path = tmp_path / "tile.partial"
    with pytest.raises(urllib.error.HTTPError):
        download_archive_tile("https://example.org/tile.jpg", path)
    assert len(calls) == attempts
    assert not path.exists()


def test_preparation_rejects_512_tiles_before_creating_output(tmp_path):
    preview = tmp_path / "preview"
    preview.mkdir()
    (preview / "product.json").write_text(
        json.dumps(
            {"kind": "sparse-detail-preview", "formatVersion": 1, "tileSize": 512}
        )
    )
    output = tmp_path / "output"
    with pytest.raises(ValueError, match="no larger than 256"):
        prepare_preview_tiles(preview, tmp_path / "archive", output)
    assert not output.exists()


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


def test_mercator_batch_contains_every_regridding_request(tmp_path):
    grid = TileGrid("web-mercator", 1737400)
    detail = {"bounds": [0, 0, 90, 45], "region": region()}
    urls = set(detail_archive_urls(detail, 3, 16, grid))
    assert urls
    requested = set()

    def acquire(url):
        requested.add(url)
        assert url in urls
        path = tmp_path / url.rsplit("/", 1)[-1]
        Image.new("L", (4, 4), 123).save(path)
        return path

    for x in (4, 5):
        for y in (2, 3):
            regrid_detail(detail, grid.tile_bounds(3, x, y), 16, acquire, grid=grid)
    assert requested
    # Acquisition contains each archive URL only once, despite overlapping
    # target windows and the interpolation halo.
    assert len(urls) == len(detail_archive_urls(detail, 3, 16, grid))


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
