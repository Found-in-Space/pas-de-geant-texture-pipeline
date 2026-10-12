import math

from rasterio.transform import Affine


def tile_transform(radius, tile_size, z, x, y, halo=0):
    half = math.pi * radius
    step = 2 * half / (tile_size * 2**z)
    return Affine(
        step,
        0,
        -half + x * tile_size * step - halo * step,
        0,
        -step,
        half - y * tile_size * step + halo * step,
    )


def bounds_range(bounds, z):
    west, south, east, north = bounds
    limit = math.degrees(math.atan(math.sinh(math.pi)))
    if not (-180 <= west < east <= 180 and -limit <= south < north <= limit):
        raise ValueError(
            "Detail bounds must be nonwrapping Mercator longitude/latitude bounds"
        )
    count = 2**z

    def row(latitude):
        return (1 - math.asinh(math.tan(math.radians(latitude))) / math.pi) / 2 * count

    return [
        z,
        max(0, math.floor((west + 180) / 360 * count)),
        max(0, math.floor(row(north))),
        min(count - 1, math.ceil((east + 180) / 360 * count) - 1),
        min(count - 1, math.ceil(row(south)) - 1),
    ]


def availability(project):
    ranges = []
    for detail in project.get("details", []):
        for z in range(project["global_maximum_zoom"] + 1, detail["maximum_zoom"] + 1):
            entry = bounds_range(detail["bounds"], z)
            if entry not in ranges:
                ranges.append(entry)
    return {
        "globalMaximumZoom": project["global_maximum_zoom"],
        "ranges": sorted(ranges),
    }


def addresses(coverage):
    # Keep only one zoom's sparse address set in memory. Global levels stream.
    for z in range(coverage["globalMaximumZoom"] + 1):
        for x in range(2**z):
            for y in range(2**z):
                yield z, x, y
    zooms = sorted({entry[0] for entry in coverage["ranges"]})
    for z in zooms:
        visited = set()
        for level, x0, y0, x1, y1 in coverage["ranges"]:
            if level != z:
                continue
            for x in range(x0, x1 + 1):
                for y in range(y0, y1 + 1):
                    if (x, y) not in visited:
                        visited.add((x, y))
                        yield z, x, y
