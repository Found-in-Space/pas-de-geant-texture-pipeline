"""Source-wide display matching and bounded multiscale boundary correction.

All arithmetic is display-linear. These are appearance transforms, not physical
reflectance estimates. No fitting is performed on individual output tiles.
"""

from __future__ import annotations

import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt, gaussian_filter
from scipy.optimize import lsq_linear

ALGORITHM = "linear-huber-multiscale-v1"


def decode_srgb(value):
    value = np.asarray(value, dtype=np.float32)
    return np.where(
        value <= 0.04045, value / 12.92, ((value + 0.055) / 1.055) ** 2.4
    ).astype(np.float32)


def encode_srgb(value):
    value = np.maximum(value, 0)
    return np.where(
        value <= 0.0031308, 12.92 * value, 1.055 * value ** (1 / 2.4) - 0.055
    )


def display_pixels(value):
    return np.rint(np.clip(encode_srgb(value), 0, 1) * 255).astype(np.uint8)


def block_mean(value, size):
    height, width = value.shape
    height, width = height // size * size, width // size * size
    return (
        value[:height, :width]
        .reshape(height // size, size, width // size, size)
        .mean(axis=(1, 3))
    )


def fit_affine(
    source, reference, valid, *, block_pixels, contrast_fraction, trim_fraction
):
    """Positive-gain Huber IRLS with a spatially disjoint validation subset."""
    valid = valid & np.isfinite(source) & np.isfinite(reference)
    if valid.sum() < 100:
        raise ValueError("Insufficient valid overlap for source matching")
    low, high = np.quantile(source[valid], [trim_fraction, 1 - trim_fraction])
    fit_mask = valid & (source >= low) & (source <= high)
    # Exclude clipped reference samples from fitting, but retain valid black
    # pixels in rendering. Range trimming is not a physical shadow detector.
    fit_mask &= (reference > 0) & (reference < 1)
    mask = block_mean(fit_mask.astype(np.float32), block_pixels) >= 0.995
    x = block_mean(np.where(valid, source, 0), block_pixels)
    y = block_mean(np.where(valid, reference, 0), block_pixels)
    rows, columns = np.indices(x.shape)
    heldout = ((rows // 8) * 73856093 + (columns // 8) * 19349663) % 5 == 0
    train, test = mask & ~heldout, mask & heldout
    if train.sum() < 30 or test.sum() < 10:
        raise ValueError("Matching needs at least 30 training and 10 held-out cells")
    xx, yy = x[train].astype(np.float64), y[train].astype(np.float64)
    source_iqr = float(np.subtract(*np.quantile(xx, [0.75, 0.25])))
    if source_iqr <= 1e-8:
        raise ValueError("Source has insufficient contrast to fit a stable gain")
    iqr_gain = float(np.subtract(*np.quantile(yy, [0.75, 0.25]))) / source_iqr
    minimum_gain = max(1e-8, contrast_fraction * iqr_gain)
    design = np.column_stack([xx, np.ones_like(xx)])
    bounds = ([minimum_gain, -np.inf], [np.inf, np.inf])
    params = lsq_linear(design, yy, bounds=bounds).x
    iterations = 0
    for _ in range(30):
        iterations += 1
        residual = yy - design @ params
        sigma = max(1.4826 * np.median(np.abs(residual - np.median(residual))), 1e-5)
        weight = np.sqrt(
            np.minimum(1, 1.345 * sigma / np.maximum(np.abs(residual), 1e-10))
        )
        updated = lsq_linear(design * weight[:, None], yy * weight, bounds=bounds).x
        change = np.max(np.abs(updated - params))
        params = updated
        if change < 1e-9:
            break
    gain, offset = map(float, params)
    prediction = gain * x[test] + offset
    correlation = (
        float(np.corrcoef(x[test], y[test])[0, 1])
        if np.std(y[test]) > 1e-8 and np.std(x[test]) > 1e-8
        else None
    )
    corrected = gain * source[valid] + offset
    return {
        "gain": gain,
        "offset": offset,
        "referenceIqrGain": iqr_gain,
        "minimumGain": minimum_gain,
        "trainingCells": int(train.sum()),
        "heldoutCells": int(test.sum()),
        "iterations": iterations,
        "heldoutCorrelation": correlation,
        "heldoutLinearMAE": float(np.mean(np.abs(prediction - y[test]))),
        "heldoutDisplayMAE": float(
            np.mean(np.abs(encode_srgb(prediction) - encode_srgb(y[test]))) * 255
        ),
        "belowZeroFraction": float(np.mean(corrected < 0)),
        "aboveOneFraction": float(np.mean(corrected > 1)),
        "warnings": [
            "Low source/reference correlation; inspect lighting and retained contrast"
        ]
        if correlation is None or correlation < 0.5
        else [],
    }


def resize(value, shape):
    return np.asarray(
        Image.fromarray(value).resize((shape[1], shape[0]), Image.Resampling.BILINEAR),
        dtype=np.float32,
    )


def smoothstep(value):
    value = np.clip(value, 0, 1)
    return value * value * (3 - 2 * value)


def blend_field(reference, source, mask, *, levels):
    """Return a shared multiband composite, extended source, and fine weight.

    Invalid source values never enter the pyramid. The finest weight also
    controls the continuation of native detail above the calibration resolution.
    """
    if not mask.any() or mask.all():
        raise ValueError(
            "Blend canvas must contain valid source and surrounding fallback"
        )
    indices = distance_transform_edt(~mask, return_distances=False, return_indices=True)
    extended = source[tuple(indices)].astype(np.float32)
    del indices
    a, b, masks = [reference], [extended], [mask.astype(np.float32)]
    for _ in range(levels):
        for pyramid in (a, b, masks):
            pyramid.append(gaussian_filter(pyramid[-1], 1, mode="reflect")[::2, ::2])
    distance = distance_transform_edt(mask).astype(np.float32)
    output = None
    for level in range(levels, -1, -1):
        weight = resize(
            smoothstep(distance / (2 * 2**level)), a[level].shape
        ) * np.clip(masks[level], 0, 1)
        if level == levels:
            output = a[level] * (1 - weight) + b[level] * weight
        else:
            lap_a = a[level] - resize(a[level + 1], a[level].shape)
            lap_b = b[level] - resize(b[level + 1], b[level].shape)
            output = (
                resize(output, a[level].shape) + lap_a * (1 - weight) + lap_b * weight
            )
    return (
        np.where(mask, output, reference).astype(np.float32),
        extended,
        smoothstep(distance / 2),
    )
