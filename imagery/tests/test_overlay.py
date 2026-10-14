import json
import shutil
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from foundinspace.textures.grid import TileGrid
from foundinspace.textures.overlay import build_overlay, load_overlay_project
from foundinspace.textures.overlay_sources import ReferenceTiles
from foundinspace.textures.preview_tiles import validate_preview_tiles
from foundinspace.textures.toolchain import run_command
from foundinspace.textures.util import atomic_write_json, identity_sha256, sha256_file


@pytest.fixture
def overlay_case(tmp_path):
    if not shutil.which("gdalwarp"):
        pytest.skip("GDAL required for raster integration")
    grid = TileGrid("web-mercator", 1737400)
    sources, reference, archive = [
        tmp_path / name for name in ("inputs", "reference", "archive")
    ]
    for root in (sources, reference, archive):
        root.mkdir()
    size = 64
    levels = []
    for z in (3, 4):
        lines = []
        for y in range(2**z):
            for x in range(2**z):
                xx, yy = np.meshgrid(
                    np.arange(size) + x * size, np.arange(size) + y * size
                )
                # Smooth, deterministic nonconstant reference across tile edges.
                value = (80 + 15 * np.sin(xx / 2**z) + 12 * np.cos(yy / 2**z)).astype(
                    np.uint8
                )
                path = reference / f"imagery/{z}/{x}/{y}.png"
                path.parent.mkdir(parents=True, exist_ok=True)
                Image.fromarray(value).save(path)
                lines.append(f"{sha256_file(path)}  {path.relative_to(reference)}\n")
        manifest = reference / f"z{z}.sha256"
        manifest.write_text("".join(lines))
        levels.append(
            {
                "zoom": z,
                "manifest": manifest.name,
                "manifest_sha256": sha256_file(manifest),
            }
        )
    atomic_write_json(
        reference / "product.json",
        {
            "format_version": 2,
            "grid": grid.metadata(),
            "levels": levels,
            "tiles": {
                "minimum_zoom": 3,
                "maximum_zoom": 4,
                "tile_size": size,
                "channels": "grayscale",
                "opaque": True,
                "path_template": "imagery/{z}/{x}/{y}.png",
            },
        },
    )
    crs = tmp_path / "target.wkt"
    shutil.copy(
        Path(__file__).parents[1] / "resources/crs/moon-mercator-1737400.wkt", crs
    )
    bounds = [-45, -40.97989806962013, 45, 40.97989806962013]
    raster = sources / "raw.tif"
    x, y = np.meshgrid(np.arange(256) + 384, np.arange(256) + 384)
    # Raw float values deliberately exceed one: clipping them before fitting
    # would destroy the texture that this integration is intended to preserve.
    image = sources / "unreferenced.tif"
    Image.fromarray(
        (1.5 + 0.4 * np.sin(x / 16) + 0.3 * np.cos(y / 16)).astype(np.float32)
    ).save(image)
    west, south, east, north = grid.project_bounds(bounds)
    run_command(
        [
            "gdal_translate",
            "-q",
            "-a_srs",
            str(crs),
            "-a_ullr",
            str(west),
            str(north),
            str(east),
            str(south),
            str(image),
            str(raster),
        ]
    )
    project = tmp_path / "overlay.toml"
    project.write_text(f'''format_version = 1
kind = "matched-overlay"
algorithm = "linear-huber-multiscale-v1"
tile_size = 64
minimum_zoom = 3
target_crs = "target.wkt"
reference_descriptor_sha256 = "{sha256_file(reference / "product.json")}"
[grid]
projection = "web-mercator"
radius_metres = 1737400
[matching]
calibration_zoom = 4
block_pixels = 4
contrast_fraction = 0.75
trim_fraction = 0.02
maximum_canvas_pixels = 1048576
[[sources]]
id = "context"
kind = "raster"
priority = 0
credit = "Synthetic test"
bounds = {bounds}
maximum_zoom = 5
blend_metres = 20000
encoding = "linear"
scale = 1.0
valid_range = [0.0, 3.0]
[[sources.inputs]]
path = "raw.tif"
sha256 = "{sha256_file(raster)}"
[[sources.rasters]]
path = "raw.tif"
size = [256, 256]
data_type = "Float32"
''')
    return project, {
        "source_root": sources,
        "archive_root": archive,
        "reference_root": reference,
        "work_root": tmp_path / "work",
        "output_root": tmp_path / "product",
    }


def test_overlay_end_to_end_is_opaque_reproducible_and_authenticates_reports(
    overlay_case,
):
    project, options = overlay_case
    first = build_overlay(project, **options)
    product = json.loads((options["output_root"] / "product.json").read_text())
    assert first["tileCount"] > 0
    assert product["matching"]["sources"][0]["fit"]["heldoutDisplayMAE"] < 5
    assert validate_preview_tiles(options["output_root"])["status"] == "passed"
    second = build_overlay(
        project,
        **{**options, "output_root": options["output_root"].with_name("second")},
    )
    assert first == second
    with pytest.raises(ValueError, match="already exists"):
        build_overlay(project, **options)
    (options["output_root"] / "matching.json").write_text("{}")
    with pytest.raises(ValueError, match="Matching report changed"):
        validate_preview_tiles(options["output_root"])


def test_reference_grid_and_payload_must_match(overlay_case):
    project, options = overlay_case
    p, grid = load_overlay_project(project)
    with pytest.raises(ValueError, match="grid differs"):
        ReferenceTiles(
            options["reference_root"],
            p["reference_descriptor_sha256"],
            TileGrid("web-mercator", 3390000),
            64,
        )
    reference = ReferenceTiles(
        options["reference_root"], p["reference_descriptor_sha256"], grid, 64
    )
    path = options["reference_root"] / "imagery/4/8/8.png"
    path.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="checksum changed"):
        reference.sample(grid.tile_bounds(4, 8, 8), 64, 4)


def test_rejects_source_changes_before_creating_output(overlay_case):
    project, options = overlay_case
    (options["source_root"] / "raw.tif").write_bytes(b"changed")
    with pytest.raises(ValueError, match="checksum changed"):
        build_overlay(project, **options)
    assert not options["output_root"].exists()


def test_quality_mask_is_bound_to_exact_sources(overlay_case):
    project, options = overlay_case
    source_inputs = load_overlay_project(project)[0]["sources"][0]["inputs"]
    mask = project.parent / "mask.json"
    atomic_write_json(
        mask,
        {
            "format_version": 1,
            "source_inputs_sha256": identity_sha256(source_inputs),
            "exclude_multipolygon": [[[[-8, -8], [8, -8], [8, 8], [-8, 8], [-8, -8]]]],
        },
    )
    project.write_text(
        project.read_text().replace(
            "blend_metres = 20000",
            f'quality_mask = {{path = "mask.json", sha256 = "{sha256_file(mask)}"}}\nblend_metres = 20000',
        )
    )
    build_overlay(project, **options)
    output = options["output_root"] / "context/4/8/8.png"
    with (
        Image.open(output) as image,
        Image.open(options["reference_root"] / "imagery/4/8/8.png") as reference,
    ):
        np.testing.assert_array_equal(
            np.asarray(image)[:8, :8], np.asarray(reference)[:8, :8]
        )


def test_all_apollo_recipes_are_admitted_and_fit_canvas_budget():
    from foundinspace.textures.overlay import calibration_canvas

    paths = list(
        (Path(__file__).parents[1] / "projects/moon/matched-overlays").glob("*.toml")
    )
    assert len(paths) == 6
    for path in paths:
        project, grid = load_overlay_project(path)
        for source in project["sources"]:
            calibration_canvas(source, grid, project["tile_size"], project["matching"])


def test_source_fit_spacing_allows_small_footprints(overlay_case):
    project, options = overlay_case
    project.write_text(
        project.read_text().replace("block_pixels = 4", "block_pixels = 64")
    )
    with pytest.raises(ValueError, match="training"):
        build_overlay(project, **options)
    project.write_text(
        project.read_text().replace(
            'kind = "raster"', 'kind = "raster"\nfit_block_pixels = 4'
        )
    )
    options["output_root"] = options["output_root"].with_name("small-footprint")
    build_overlay(project, **options)
    report = json.loads((options["output_root"] / "matching.json").read_text())[
        "sources"
    ][0]
    assert (
        report["fitCellProjectedMetres"] == 4 * report["calibrationStepProjectedMetres"]
    )
    assert report["fit"]["trainingCells"] >= 30


def test_underlay_uses_resolution_before_priority():
    from foundinspace.textures.overlay import best_parent

    low = {(4, 8, 8): Path("fine-context")}
    high = {(3, 4, 4): Path("coarse-detail")}
    assert best_parent([low, high], (5, 16, 16), 3) == (Path("fine-context"), (4, 8, 8))
    high[(4, 8, 8)] = Path("fine-detail")
    assert best_parent([low, high], (5, 16, 16), 3) == (Path("fine-detail"), (4, 8, 8))


@pytest.mark.parametrize(
    "old,new,message",
    [
        ("tile_size = 64", "tile_size = 512", "256"),
        ("block_pixels = 4", "block_pixels = 4.5", "integers"),
        (
            "trim_fraction = 0.02",
            "trim_fraction = 0.02\nper_tile_gamma = 1.2",
            "unknown",
        ),
    ],
)
def test_invalid_configuration_fails_before_build(overlay_case, old, new, message):
    project, options = overlay_case
    project.write_text(project.read_text().replace(old, new))
    with pytest.raises(ValueError, match=message):
        build_overlay(project, **options)
    assert not options["output_root"].exists()


def test_failed_build_is_not_promoted_and_can_resume(overlay_case, monkeypatch):
    import foundinspace.textures.overlay as overlay

    project, options = overlay_case
    original = overlay.fit_affine

    def interrupted(*args, **kwargs):
        raise RuntimeError("simulated interruption")

    monkeypatch.setattr(overlay, "fit_affine", interrupted)
    with pytest.raises(RuntimeError, match="interruption"):
        build_overlay(project, **options)
    assert not options["output_root"].exists()
    staging = options["output_root"].with_name("product.building")
    assert json.loads((staging / "state.json").read_text())["status"] == "building"
    monkeypatch.setattr(overlay, "fit_affine", original)
    build_overlay(project, **options)
    assert not staging.exists()
    assert validate_preview_tiles(options["output_root"])["status"] == "passed"
