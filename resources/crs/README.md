# Target CRS resources

Store reviewed WKT or PROJJSON definitions for target bodies here. Each resource
must document its authority or derivation, reference radius or ellipsoid, datum,
prime meridian, axis directions, longitude range, latitude type, and validation
tool versions.

Do not copy an unreviewed `gdalinfo` fragment into this directory. The first
implementation task is to add and test the Moon geographic CRS with radius
exactly 1,737,400 m. Later Mars, Venus, or Earth products add separate explicit
resources rather than changing an existing published definition.

