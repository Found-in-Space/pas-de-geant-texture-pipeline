import numpy as np
import pytest

from foundinspace.textures.grid import TileGrid
from foundinspace.textures.preview import (
    area_bounds,
    build_preview,
    display_pixels,
    footprint_mask,
    tile_range,
)


@pytest.mark.parametrize("projection", ["geographic", "web-mercator"])
def test_footprint_keeps_spanning_edges_and_holes_while_ignoring_remote_rings(
    projection,
):
    grid = TileGrid(projection, 1737400)
    polygons = [
        [
            [[-20, -40], [20, -40], [20, 40], [-20, 40], [-20, -40]],
            [[-2, -2], [2, -2], [2, 2], [-2, 2], [-2, -2]],
        ],
        [[[-20, 60], [20, 60], [20, 70], [-20, 70], [-20, 60]]],
        [[[-20, -70], [20, -70], [20, -60], [-20, -60], [-20, -70]]],
    ]
    bounds = [-5, -5, 5, 5]
    longitude, latitude = grid.pixel_coordinates(bounds, 16)
    # The outer ring encloses the tile, even though none of its vertices lies
    # in this latitude band. Only the central rectangular hole is uncovered.
    expected = ~((np.abs(longitude[None, :]) < 2) & (np.abs(latitude[:, None]) < 2))
    np.testing.assert_array_equal(footprint_mask(polygons, bounds, 16, grid), expected)


def test_build_preview_rejects_512_tiles_before_creating_output(tmp_path):
    project = tmp_path / "preview.toml"
    project.write_text(
        'format_version = 1\nkind = "sparse-detail-preview"\n'
        "tile_size = 512\nradius_metres = 1737400\n"
        "minimum_zoom = 0\ncontext_maximum_zoom = 0\n"
    )
    output = tmp_path / "output"
    with pytest.raises(ValueError, match="no larger than 256"):
        build_preview(
            project, tmp_path / "source", tmp_path / "detail", tmp_path / "work", output
        )
    assert not output.exists()


def test_preserves_dark_terrain_and_saturation_with_separate_coverage():
    gray, alpha = display_pixels(
        np.array([[0, 1, 250, 550, 850, 32767, 65535]], dtype=np.uint16), 250, 850
    )
    assert gray.tolist() == [[0, 0, 0, 128, 255, 255, 255]]
    assert alpha.tolist() == [[0, 255, 255, 255, 255, 255, 0]]


def test_sparse_range_covers_bounds_without_an_extra_eastern_or_southern_tile():
    assert tile_range([-180, 0, 0, 90], 1) == (0, 0, 0, 0)
    assert tile_range([-180, -90, 180, 90], 0) == (0, 0, 0, 0)
    bounds = area_bounds(0.67416, 23.47314, 100, 1737400)
    x0, y0, x1, y1 = tile_range(bounds, 11)
    assert -180 + x0 * 360 / 2048 <= bounds[0]
    assert -180 + (x1 + 1) * 360 / 2048 >= bounds[2]
    assert 90 - (y1 + 1) * 180 / 2048 <= bounds[1]
    assert 90 - y0 * 180 / 2048 >= bounds[3]


def test_footprint_sampling_preserves_holes_and_disconnected_islands():
    outer = [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]
    hole = [[0.5, 0.5], [1.5, 0.5], [1.5, 1.5], [0.5, 1.5], [0.5, 0.5]]
    island = [[3, 0], [4, 0], [4, 1], [3, 1], [3, 0]]
    mask = footprint_mask([[outer, hole], [island]], [0, 0, 4, 2], 8)
    assert not mask[4, 2]
    assert mask[7, 0]
    assert mask[7, 7]
    assert not mask[0, 7]
