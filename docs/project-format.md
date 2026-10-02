# Project format

The first implementation should define and validate `format_version = 1` TOML
project files. A project describes semantic inputs and outputs; it must not
contain credentials or machine-specific run paths.

Relative paths resolve from the project file. Environment-variable expansion
inside TOML path values should be rejected so that the same file means the same
thing on every host. Local source, work, output, and evidence roots are supplied
as explicit CLI arguments or a separate ignored run file.

## Proposed model

The names below are a design contract for implementation, not an already
supported parser.

```toml
format_version = 1
product_id = "moon-lroc-wac-global-morphology-100m-v1"

[target]
id = "moon"
crs = "../../../resources/crs/moon-geographic-1737400.wkt"
longitude_range = [-180.0, 180.0]
latitude_range = [-90.0, 90.0]

[[sources]]
id = "lroc-wac-global-morphology-100m-june-2013"
acquisition = "sources/lroc-wac-global-morphology-100m.toml"
priority = 100

[composite]
policy = "priority"
missing_pixel = 0

[product]
kind = "display-texture"
bounds = [-180.0, -90.0, 180.0, 90.0]
maximum_zoom = 8
tile_size = 512
resampling = "area"
pixel_type = "uint8"
channels = "grayscale"
format = "png"
opaque = true
path_template = "imagery/{z}/{x}/{y}.png"
```

## Source acquisition specifications

Each source specification should declare:

- stable source ID and human-readable title;
- public landing page and exact payload URL or a documented manual retrieval
  method;
- expected filename, byte size, and SHA-256 once known;
- licence/citation and retrieval notes;
- expected raster dimensions, band count, type, CRS, geotransform, mask,
  nodata, scale, offset, and relevant metadata;
- coverage geometry or bounds;
- source-wide preprocessing, if any;
- whether network acquisition is allowed by the command being run.

Unknown values discovered during an explicit source-admission workflow may be
captured in a candidate report, but a production build must not silently bless
them. A human-reviewed update to the source specification comes first.

## Target definitions

Targets are reusable across products, but a product pins the exact checked-in
definition. A target definition must make these choices explicit:

- datum and body-fixed frame;
- sphere radius or ellipsoid axes;
- prime meridian;
- longitude direction and range;
- latitude type;
- target geographic CRS and any projected CRS needed during processing.

Do not infer a lunar or planetary CRS from the source filename or from an EPSG
fallback.

## Product identity

The final report should compute a canonical product identity from at least:

- normalized project configuration;
- all source object checksums;
- checked-in CRS resource checksums;
- producer Git SHA and dirty-state assertion;
- material external tool versions;
- generated payload manifest checksum.

The Found in Space `catalogs` publication can then pin this identity and the
immutable storage prefix without committing the tile tree.
