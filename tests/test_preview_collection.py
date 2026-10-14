import json

import pytest
from PIL import Image

from foundinspace.textures.grid import TileGrid
from foundinspace.textures.preview_collection import collect_preview_tiles
from foundinspace.textures.util import atomic_write_json, identity_sha256, sha256_file


def product(root, value, *, radius=1737400):
    path = root / "context/1/0/0.png"
    path.parent.mkdir(parents=True)
    Image.new("L", (16, 16), value).save(path)
    checksums = root / "checksums.sha256"
    checksums.write_text(f"{sha256_file(path)}  context/1/0/0.png\n")
    descriptor = {
        "kind": "sparse-opaque-xyz",
        "formatVersion": 2,
        "tileSize": 16,
        "grid": TileGrid("web-mercator", radius).metadata(),
        "sources": [
            {
                "id": "context",
                "priority": 0,
                "attribution": "fixture",
                "minimumZoom": 1,
                "maximumZoom": 1,
                "pathTemplate": "context/{z}/{x}/{y}.png",
                "levels": [{"zoom": 1, "tiles": [[0, 0]]}],
            }
        ],
        "payloadManifestSha256": sha256_file(checksums),
    }
    descriptor["identity"] = identity_sha256(descriptor)
    atomic_write_json(root / "product.json", descriptor)
    return path


def test_collection_preserves_pixels_priorities_and_distinct_namespaces(tmp_path):
    first, second, output = (tmp_path / name for name in ("first", "second", "output"))
    original = product(first, 0)
    product(second, 231)
    report = collect_preview_tiles([("one", first), ("two", second)], output)
    assert report["tileCount"] == 2
    assert report["sourceTileCounts"] == {"one-context": 1, "two-context": 1}
    assert (output / "one/context/1/0/0.png").stat().st_ino == original.stat().st_ino
    assert Image.open(output / "two/context/1/0/0.png").getpixel((0, 0)) == 231
    descriptor = json.loads((output / "product.json").read_text())
    assert [s["priority"] for s in descriptor["sources"]] == [0, 0]
    assert (
        sha256_file(output / "inputs/one/product.json")
        == descriptor["inputs"][0]["descriptorSha256"]
    )


def test_collection_rejects_grid_mismatch_and_duplicate_names(tmp_path):
    first, second, output = (tmp_path / name for name in ("first", "second", "output"))
    product(first, 0)
    product(second, 1, radius=6371000)
    with pytest.raises(ValueError, match="unique"):
        collect_preview_tiles([("one", first), ("one", second)], output)
    with pytest.raises(ValueError, match="different grids"):
        collect_preview_tiles([("one", first), ("two", second)], output)
    assert not output.exists()


def test_corrupt_payload_never_promotes_collection(tmp_path):
    source, output = tmp_path / "source", tmp_path / "output"
    path = product(source, 12)
    Image.new("L", (16, 16), 100).save(path)
    with pytest.raises(ValueError, match="checksum changed"):
        collect_preview_tiles([("one", source)], output)
    assert not output.exists()
