"""Generate the portable producer/consumer sampling fixture (no external data)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from foundinspace.textures.grid import TileGrid


def fixture():
    cases = []
    for projection in ("geographic", "web-mercator"):
        for radius in (1_737_400, 6_378_137):
            grid = TileGrid(projection, radius)
            for z, x, y in (
                (0, 0, 0),
                (2, 3, 1),
                (3, 0, 0),
                (3, 7, 7),
                (14, 9260, 8161),
            ):
                bounds = grid.tile_bounds(z, x, y)
                longitude, latitude = grid.pixel_coordinates(bounds, 8)
                cases.append(
                    {
                        "grid": grid.metadata(),
                        "address": {"z": z, "x": x, "y": y},
                        "bounds": bounds,
                        "pixelSize": 8,
                        "longitudeCentres": longitude.tolist(),
                        "latitudeCentres": latitude.tolist(),
                    }
                )
    return {
        "formatVersion": 1,
        "generator": "scripts/write-grid-contract-fixture.py",
        "cases": cases,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(fixture(), indent=2, sort_keys=True) + "\n")
