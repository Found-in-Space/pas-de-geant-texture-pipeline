import numpy as np
import pytest

from foundinspace.textures.overlay import BlendField
from foundinspace.textures.photometry import (
    blend_field,
    decode_srgb,
    display_pixels,
    fit_affine,
)


def test_srgb_round_trip_including_valid_black():
    pixels = np.arange(256, dtype=np.uint8)
    np.testing.assert_array_equal(display_pixels(decode_srgb(pixels / 255)), pixels)


def test_robust_fit_recovers_gain_and_offset_with_outliers():
    rng = np.random.default_rng(24)
    source = np.repeat(
        np.repeat(rng.uniform(0.1, 0.9, (64, 64)), 4, axis=0), 4, axis=1
    ).astype(np.float32)
    reference = 0.3 * source + 0.04
    reference[40:56, 80:96] = 0.9
    report = fit_affine(
        source,
        reference,
        np.ones_like(source, bool),
        block_pixels=4,
        contrast_fraction=0.75,
        trim_fraction=0.02,
    )
    assert report["gain"] == pytest.approx(0.3, abs=0.001)
    assert report["offset"] == pytest.approx(0.04, abs=0.001)
    assert report["trainingCells"] > 30 and report["heldoutCells"] > 10


def test_degenerate_or_tiny_overlap_fails_instead_of_silent_flattening():
    source = np.full((256, 256), 0.3, np.float32)
    for mask, message in [
        (np.ones_like(source, bool), "contrast"),
        (np.zeros_like(source, bool), "overlap"),
    ]:
        with pytest.raises(ValueError, match=message):
            fit_affine(
                source,
                source,
                mask,
                block_pixels=4,
                contrast_fraction=0.75,
                trim_fraction=0.02,
            )


def test_multiband_preserves_fallback_holes_and_ignores_invalid_source_values():
    y, x = np.indices((256, 256))
    base = (0.2 + 0.01 * np.sin(x / 9)).astype(np.float32)
    source = (0.35 + 0.02 * np.sin(y / 3)).astype(np.float32)
    mask = (x > 30) & (x < 230) & (y > 30) & (y < 230)
    mask[100:140, 100:140] = False
    first, _, weight = blend_field(base, source, mask, levels=4)
    source[~mask] = 10000
    second, _, _ = blend_field(base, source, mask, levels=4)
    np.testing.assert_array_equal(first, second)
    np.testing.assert_array_equal(first[~mask], base[~mask])
    assert (weight[~mask] == 0).all()
    assert np.mean(np.abs(first[31:34, 50:90] - base[31:34, 50:90])) < 0.08


def test_shared_field_has_identical_sampling_across_tile_boundaries_and_zooms():
    y, x = np.indices((128, 128))
    correction = (np.sin(x / 17) * np.cos(y / 13)).astype(np.float32)
    field = BlendField(correction, np.ones_like(correction), 4, (0, 0))
    # Four child tiles must sample exactly the same global field as one window
    # spanning their common edges (size doubles while the physical extent holds).
    children = np.block(
        [[field.sample((5, col, row), 32)[0] for col in (2, 3)] for row in (2, 3)]
    )
    whole = field.sample((5, 1, 1), 64)[0]
    np.testing.assert_array_equal(children, whole)
    # Lower zooms use one global area reduction, never per-tile normalisation.
    reduced = field.sample((3, 0, 0), 64)[0]
    expected = correction.reshape(64, 2, 64, 2).mean(axis=(1, 3))
    np.testing.assert_allclose(reduced, expected, atol=1e-7)
