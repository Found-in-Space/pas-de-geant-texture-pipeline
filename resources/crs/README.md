# Target CRS resources

`moon-geographic-1737400.wkt` is the reviewed target grid CRS for spherical
lunar display textures. It fixes the radius at 1,737,400 metres, uses an
east-positive longitude axis and a north-positive planetocentric latitude axis,
and deliberately contains no authority-code dependency.

Validate it with the same GDAL/PROJ installation used for a build:

```console
gdalsrsinfo -V resources/crs/moon-geographic-1737400.wkt
```

Store reviewed WKT or PROJJSON definitions for target bodies here. Each resource
must document its authority or derivation, reference radius or ellipsoid, datum,
prime meridian, axis directions, longitude range, latitude type, and validation
tool versions.

Do not copy an unreviewed `gdalinfo` fragment into this directory. The first
implementation task is to add and test the Moon geographic CRS with radius
exactly 1,737,400 m. Later Mars, Venus, or Earth products add separate explicit
resources rather than changing an existing published definition.
