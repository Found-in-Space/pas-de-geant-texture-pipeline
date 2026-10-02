# Testing and validation

Tests are split between producer correctness and Pas de Géant integration. A
viewer screenshot cannot substitute for pixel-level producer validation, and
producer tests cannot prove that the viewer requests the correct tiles.

## Synthetic fixture

Generate the fixture from code so its expected values and spatial locations are
known. It should include:

- labeled hemispheres and cardinal directions;
- longitude and latitude gradients;
- distinct patterns touching each side of the antimeridian;
- features at both poles;
- constant-value regions crossing tile boundaries;
- exact byte values 0 and 255;
- masked or missing regions;
- a second optional source with partial coverage and overlap.

The fixture must begin in a projected planetary CRS so the test exercises real
reprojection, not just window splitting.

## Producer tests

Project and source contracts:

- reject unsupported format versions and unknown semantic fields;
- resolve relative paths from the project file;
- reject environment interpolation and committed absolute run paths;
- detect changed source bytes and metadata mismatches;
- prove deterministic source ordering and compositing.

Tile structure:

- exactly `4^z` tiles at level `z` and the declared total count;
- every PNG decodes to 512 × 512 with the declared bit depth and channels;
- no alpha channel, palette transparency, or PNG transparency chunk for opaque
  products;
- path coordinates are in range and no expected coordinate is absent;
- tile bytes and manifests are stable across identical clean runs.

Pixel and spatial correctness:

- each decoded tile equals the corresponding level-raster window exactly;
- assembling all tiles reproduces the complete level raster exactly;
- coordinate tests prove eastward `x` and southward `y`;
- known synthetic features land at expected longitudes, latitudes, poles, and
  antimeridian sides;
- missing data becomes the declared opaque value;
- constant regions remain constant across tiles and levels;
- parents match the declared area-average and byte-rounding rule.

Operational behavior:

- interruption never promotes a partial stage;
- valid completed stages resume without rewriting outputs;
- changed configuration or input invalidates the correct downstream stages;
- work is bounded under an instrumented memory limit;
- free-space preflight and overlapping-root checks fail safely;
- reports contain complete tool versions, timings, counts, sizes, and hashes.

## Full-product validation

The WAC build additionally requires:

- source metadata comparison against the reviewed acquisition specification;
- per-level tile count and byte-size reconciliation;
- complete decoding/structure validation for all 87,381 tiles;
- exact pixel-window checks for all tiles, or a documented equivalent streaming
  comparison that covers every pixel;
- selected inverse-coordinate checks against the original source;
- manual review of global brightness consistency and source coverage;
- preservation of all generated logs and reports for the `catalogs` handoff.

## Pas de Géant integration

Tests in the application repository should cover:

- imagery zoom 8 while elevation remains independently limited to zoom 5;
- intended behavior for imagery zoom 9 and elevation zoom 6;
- 512-pixel tile width and one-tile level-zero matrix;
- XYZ orientation and proxy URL construction;
- proxy operation against a local static tile server;
- interactive inspection at poles, antimeridian, boundaries, and zoom changes;
- no unexpected missing-tile requests during ordinary navigation.
