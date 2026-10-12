# Moon WAC Mercator migration candidate

This format 2 recipe reprojects the same admitted WAC source into the Earth's
XYZ scheme on the lunar sphere (radius 1,737,400 m). It does not replace or
relabel the geographic `lroc-wac-global-100m` recipe or its published payload.

The target is spherical Mercator with unit scale and zero offsets. Projected
extent is ±πR in both axes; latitude coverage is ±85.0511287798066°. Longitude
wraps at ±180°. The reviewed source remains lunar Simple Cylindrical. Each
pixel samples the projected grid, rather than stretching geographic rows.

The 512-pixel zoom 0–8 pyramid contains 87,381 tiles; the maximum raster is
131,072 square (16 GiB of uncompressed grayscale samples). Intermediate levels,
output PNGs and validation working files need additional disk space. The CLI
preflight estimates these separately. The separate 2048 × 1024 equirectangular
`base.png` is generated directly from the admitted source and includes both
poles. The consumer uses it for the base and polar caps, with flat reference
heights beyond Mercator's extent.

Use four distinct run roots outside Git. First inspect the existing source and
run `preflight` with this recipe; review its recorded disk/tool/input checks
before a full build. Run commands in order with the same arguments:

```sh
export GRID_RUN_ROOT=/absolute/external/new-mercator-run
export GRID_SOURCE_ROOT=/absolute/external/admitted-wac-source
UV_CACHE_DIR=.cache/uv uv run pas-de-geant-textures preflight \
  projects/moon/lroc-wac-global-100m-mercator-v2/project.toml \
  --source-root "$GRID_SOURCE_ROOT" --work-root "$GRID_RUN_ROOT/work" \
  --output-root "$GRID_RUN_ROOT/output" --evidence-root "$GRID_RUN_ROOT/evidence"
```

The `build-base`, `build-levels`, `emit-tiles` and `validate-tiles` commands use
this project and the roots accepted by each command; see `--help`. Run state
records source/project/CRS hashes, producer Git SHA and dirty state, tool
versions, commands and stage hashes. The product authenticates `base.png` and
its grid. Publication requires a clean pushed producer commit and a new
immutable storage prefix; scratch runs do not constitute release evidence.

No full source download or payload build accompanies this recipe change.
Scientific elevation must be independently reprojected to the identical grid
under its own value-preserving contract before enabling relief. A geographic
height tree cannot accompany these Mercator imagery tiles.
