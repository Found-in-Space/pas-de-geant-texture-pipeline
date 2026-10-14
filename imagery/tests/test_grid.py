import json
import math
import runpy
from pathlib import Path

import numpy as np
import pytest

from foundinspace.textures.grid import (
    LEGACY_LUNAR_GRID,
    MERCATOR_MAX_LATITUDE,
    TileGrid,
)
from foundinspace.textures.preview import footprint_mask


def test_mercator_reuses_earth_matrix_bounds_and_wrap_boundary():
    grid = TileGrid("web-mercator", 1_737_400)
    assert grid.tile_bounds(0, 0, 0) == [
        -180,
        -MERCATOR_MAX_LATITUDE,
        180,
        MERCATOR_MAX_LATITUDE,
    ]
    assert grid.tile_bounds(1, 0, 0) == [-180, 0, 0, MERCATOR_MAX_LATITUDE]
    assert grid.tile_range(grid.tile_bounds(2, 3, 1), 2) == (3, 1, 3, 1)
    assert grid.projected_bounds == (
        -math.pi * 1_737_400,
        -math.pi * 1_737_400,
        math.pi * 1_737_400,
        math.pi * 1_737_400,
    )
    assert grid.tile_bounds(8, 0, 0)[0] == -180
    assert grid.tile_bounds(8, 255, 255)[2] == 180


def test_pixel_centres_are_projected_not_stretched_geographic_rows():
    grid = TileGrid("web-mercator", 1_737_400)
    longitude, latitude = grid.pixel_coordinates(grid.tile_bounds(1, 1, 0), 8)
    assert np.allclose(grid.normalized_y(latitude), (np.arange(8) + 0.5) / 16)
    assert not np.allclose(
        latitude,
        np.linspace(MERCATOR_MAX_LATITUDE, 0, 8, endpoint=False)
        - MERCATOR_MAX_LATITUDE / 16,
    )
    assert np.allclose(longitude, (np.arange(8) + 0.5) * 180 / 8)
    bounds = grid.tile_bounds(14, 9260, 8161)
    lon, lat = grid.pixel_coordinates(bounds, 512)
    east_west = (
        math.radians(lon[1] - lon[0])
        * grid.radius_metres
        * math.cos(math.radians(float(lat[256])))
    )
    north_south = math.radians(lat[255] - lat[256]) * grid.radius_metres
    assert east_west / north_south == pytest.approx(1, abs=0.001)
    _, old_lat = LEGACY_LUNAR_GRID.pixel_coordinates(
        LEGACY_LUNAR_GRID.tile_bounds(14, 9260, 8130), 512
    )
    assert math.radians(lon[1] - lon[0]) / math.radians(
        old_lat[255] - old_lat[256]
    ) == pytest.approx(2)


def test_mercator_masks_sample_nonlinear_latitudes():
    grid = TileGrid("web-mercator", 1_737_400)
    polygon = [[[[-180, 60], [180, 60], [180, 85], [-180, 85], [-180, 60]]]]
    bounds = grid.tile_bounds(0, 0, 0)
    mask = footprint_mask(polygon, bounds, 16, grid)
    _, latitude = grid.pixel_coordinates(bounds, 16)
    assert np.array_equal(mask[:, 5], (latitude >= 60) & (latitude <= 85))


def test_grid_identity_requires_explicit_projection_radius_and_version():
    grid = TileGrid("web-mercator", 1_737_400)
    assert TileGrid.from_metadata(grid.metadata()) == grid
    with pytest.raises(ValueError):
        TileGrid.from_metadata(
            {
                "formatVersion": 2,
                "projection": "web-mercator",
                "radiusMetres": 1_737_400,
            }
        )


def test_portable_sampling_fixture_is_generated_from_the_producer():
    root = Path(__file__).resolve().parents[1]
    generated = runpy.run_path(str(root / "scripts/write-grid-contract-fixture.py"))[
        "fixture"
    ]()
    expected = json.loads((root / "tests/fixtures/surface-grid.json").read_text())
    generated_cases = generated.pop("cases")
    expected_cases = expected.pop("cases")
    assert generated == expected
    for actual, reference in zip(generated_cases, expected_cases, strict=True):
        assert actual.keys() == reference.keys()
        for key, value in reference.items():
            if key in {"bounds", "longitudeCentres", "latitudeCentres"}:
                # Native transcendental math can differ in its last bits across
                # hosts. 1e-12 degrees is below 0.12 micrometres on Earth.
                assert actual[key] == pytest.approx(value, rel=0, abs=1e-12)
            else:
                assert actual[key] == value


def test_inverse_projection_does_not_add_rows_at_exact_edges():
    grid = TileGrid("web-mercator", 1737400)
    for zoom in (0, 1, 4, 11, 15):
        for x, y in ((0, 0), (2**zoom - 1, 2**zoom - 1), (2**zoom // 2, 2**zoom // 2)):
            assert grid.tile_range(grid.tile_bounds(zoom, x, y), zoom) == (x, y, x, y)
