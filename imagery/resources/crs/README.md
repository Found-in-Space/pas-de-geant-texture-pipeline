# Target CRS resources

`moon-geographic-1737400.wkt` is the reviewed target grid CRS for spherical
lunar display textures. It fixes the radius at 1,737,400 metres, uses an
east-positive longitude axis and a north-positive planetocentric latitude axis,
and deliberately contains no authority-code dependency.

`moon-simple-cylindrical-1737400.wkt` is the reviewed source CRS for the
admitted LROC WAC global morphology mosaic. It uses the same spherical lunar
datum, Equidistant Cylindrical (Simple Cylindrical) with standard parallel and
natural origin at 0 degrees, zero false offsets, and metre coordinates. Its
projection parameters are equivalent to the CRS embedded in the admitted
GeoTIFF; the source inspection report records both normalized definitions.

Validate it with the same GDAL/PROJ installation used for a build:

```console
gdalsrsinfo -V resources/crs/moon-geographic-1737400.wkt
gdalsrsinfo -V resources/crs/moon-simple-cylindrical-1737400.wkt
```

Store reviewed WKT or PROJJSON definitions for target bodies here. Each resource
must document its authority or derivation, reference radius or ellipsoid, datum,
prime meridian, axis directions, longitude range, latitude type, and validation
tool versions.

Do not copy an unreviewed `gdalinfo` fragment into this directory. The first
implementation task is to add and test the Moon geographic CRS with radius
exactly 1,737,400 m. Later Mars, Venus, or Earth products add separate explicit
resources rather than changing an existing published definition.

`moon-mercator-1737400.wkt` defines the new format 2 XYZ target, derived from
spherical Mercator on the same lunar datum: radius 1,737,400 m, Greenwich prime
meridian, east/north axes in metres, natural origin 0°, scale 1 and zero false
offsets. The longitude/latitude convention and physical sphere are unchanged.
The finite XYZ extent is ±πR, cutting latitude at ±85.0511287798066°. It changes
the raster sampling scheme, without claiming an EPSG Earth datum. Validate with:

```sh
gdalsrsinfo -V resources/crs/moon-mercator-1737400.wkt
```

The separate base uses the existing reviewed geographic CRS. The source CRS
remains the admitted Simple Cylindrical resource; assigning Mercator to source
bytes without reprojection is invalid.
