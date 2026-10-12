"""Explicit planetary XYZ grids; Mercator matches the Earth consumer scheme."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

MERCATOR_MAX_LATITUDE = math.degrees(math.atan(math.sinh(math.pi)))


@dataclass(frozen=True, slots=True)
class TileGrid:
    projection: str
    radius_metres: float

    def __post_init__(self):
        if self.projection not in {"geographic", "web-mercator"}:
            raise ValueError("Unsupported tile-grid projection")
        if not math.isfinite(self.radius_metres) or self.radius_metres <= 0:
            raise ValueError("Tile-grid radius must be positive finite metres")

    @property
    def latitude_limit(self):
        return 90.0 if self.projection == "geographic" else MERCATOR_MAX_LATITUDE

    @property
    def geographic_bounds(self):
        return (-180.0, -self.latitude_limit, 180.0, self.latitude_limit)

    @property
    def projected_bounds(self):
        if self.projection == "geographic":
            return self.geographic_bounds
        half = math.pi * self.radius_metres
        return (-half, -half, half, half)

    def metadata(self):
        return {
            "formatVersion": 1,
            "projection": self.projection,
            "radiusMetres": self.radius_metres,
        }

    @classmethod
    def from_metadata(cls, raw):
        if raw.get("formatVersion") != 1:
            raise ValueError("Unsupported tile-grid metadata version")
        return cls(raw["projection"], raw["radiusMetres"])

    def normalized_y(self, latitude):
        latitude = np.clip(latitude, -self.latitude_limit, self.latitude_limit)
        if self.projection == "geographic":
            return (90 - latitude) / 180
        return (1 - np.arcsinh(np.tan(np.radians(latitude))) / math.pi) / 2

    def latitude_at_y(self, y):
        if self.projection == "geographic":
            return 90 - np.asarray(y) * 180
        return np.degrees(np.arctan(np.sinh(math.pi * (1 - 2 * np.asarray(y)))))

    def tile_bounds(self, z, x, y):
        n = 2**z
        return [
            -180 + x * 360 / n,
            float(self.latitude_at_y((y + 1) / n)),
            -180 + (x + 1) * 360 / n,
            float(self.latitude_at_y(y / n)),
        ]

    def tile_range(self, bounds, zoom):
        west, south, east, north = bounds
        count = 2**zoom

        def edge(value):
            # Inverse Mercator round trips can place an exact edge a few ulps
            # either side of its integer index. Only remove that rounding error.
            nearest = round(value)
            return (
                nearest if abs(value - nearest) <= 8 * math.ulp(float(count)) else value
            )

        # A boundary exactly on a tile edge belongs to the preceding extent.
        return (
            max(0, math.floor(edge((west + 180) / 360 * count))),
            max(0, math.floor(edge(float(self.normalized_y(north)) * count))),
            min(count - 1, math.ceil(edge((east + 180) / 360 * count)) - 1),
            min(
                count - 1, math.ceil(edge(float(self.normalized_y(south)) * count)) - 1
            ),
        )

    def pixel_coordinates(self, bounds, size):
        west, south, east, north = bounds
        centres = (np.arange(size) + 0.5) / size
        longitude = west + centres * (east - west)
        top, bottom = self.normalized_y(north), self.normalized_y(south)
        latitude = self.latitude_at_y(top + centres * (bottom - top))
        return longitude, latitude

    def project_bounds(self, bounds):
        if self.projection == "geographic":
            return bounds
        west, south, east, north = bounds
        scale = math.pi * self.radius_metres
        return [
            west / 180 * scale,
            (1 - 2 * float(self.normalized_y(south))) * scale,
            east / 180 * scale,
            (1 - 2 * float(self.normalized_y(north))) * scale,
        ]


# Format 1 products explicitly used this lunar geographic grid. Never relabel
# their bytes as Mercator; version 2 descriptors always carry a grid.
LEGACY_LUNAR_GRID = TileGrid("geographic", 1_737_400)
