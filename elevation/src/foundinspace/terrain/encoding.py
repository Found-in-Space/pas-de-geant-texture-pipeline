import numpy as np


def encode_terrarium(heights):
    if not np.isfinite(heights).all():
        raise ValueError("Missing or nonfinite heights cannot be encoded")
    codes = np.rint((heights.astype(np.float64) + 32768) * 256)
    if (codes < 0).any() or (codes > 16777215).any():
        raise ValueError("Height outside Terrarium's numeric range")
    codes = codes.astype(np.uint32)
    return np.stack((codes >> 16, (codes >> 8) & 255, codes & 255), axis=-1).astype(
        np.uint8
    )


def decode_terrarium(rgb):
    values = rgb.astype(np.float64)
    return values[..., 0] * 256 + values[..., 1] + values[..., 2] / 256 - 32768
