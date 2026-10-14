# Matched display overlays

`build-overlay` fits each source against the base product or the already
composited lower-priority sources. It emits the existing format 2
`sparse-opaque-xyz` product, with opaque grayscale tiles of at most 256 pixels.
The reference descriptor is pinned by SHA-256; its grid/body, per-level manifests,
and every reference tile actually read are checked. No runtime changes are needed.

This is an opt-in appearance build. Existing `build-preview` and
`prepare-preview-tiles` recipes retain their original behavior. Use a new product
directory and collect the results with `collect-preview-tiles` after review.
Do not replace a serving dataset with scratch output.

## Algorithm version 1

The project names `linear-huber-multiscale-v1`. Processing is deterministic for
the recorded input bytes, code, configuration and tool versions:

1. Admit every raster and sidecar by hash. Decode raw values using the declared
   scale, offset and `linear`/`srgb` encoding before GDAL averages them. This avoids
   the irreversible highlight clipping of the original Kaguya display stretch.
   Registered Zoomify browse sources use the existing masked bilinear archive
   regridder, followed by sRGB decoding. Their existing JPEG quantization and
   archive interpolation are part of the admitted display source.
2. Sample each complete regional footprint on one fixed calibration grid,
   including surrounding fallback imagery. Divide it into common-resolution
   mean cells; exclude nodata, quality masks, clipped reference values and the
   configured source tails from fitting. Valid dark pixels remain in rendering.
3. Hold out about one fifth of spatial blocks of 8 × 8 fit cells. Fit positive
   gain and offset using Huber IRLS on the remaining cells. Require at least 30
   training and 10 held-out cells and nondegenerate source contrast.
   `contrast_fraction` sets a gain floor relative to the ratio of reference and
   source interquartile ranges. The Apollo starting value, 0.75, keeps the weakly
   correlated Kaguya imagery from being flattened by a least-squares fit.
4. Extend valid source pixels into missing areas before forming Gaussian and
   Laplacian bands. Blend high-frequency bands over narrow edges and broad
   brightness bands over wider edges. Outside the footprint or inside a quality
   exclusion, retain the lower-priority image exactly at the calibration grid.
5. Store the resulting correction and finest-band weight as one regional field.
   Globally aligned field mipmaps supply every output tile and zoom. Above the
   calibration resolution, add the source's native detail residual using the
   same fitted gain and weight. Thus full-resolution rasters stay on disk and
   fitting or pyramid construction is never repeated independently per tile.
6. Composite over the best available lower-priority parent, preserve mask holes,
   clamp at final display encoding, and write opaque sRGB PNGs. Record output
   clipping separately from the fitted transform's clipping statistics.

The native detail continuation is a bounded production extension of the
overview experiment, not a full-resolution in-memory Laplacian pyramid.
`blend_metres` uses **projected metres**. The broadest band is rounded up to the
next available pyramid scale and its actual width is reported. The finest
transition spans two calibration pixels. To resolve narrower masks or blend
edges, increase the calibration zoom within the canvas budget.

Matching changes display appearance, not geometry, illumination direction, or
physical reflectance. It cannot recover clipped original data or correct a
camera's cast shadows. A low source/reference correlation produces a review
warning, not a claim that the fit is scientifically valid. The contrast floor
and fit errors need inspection for each new source. Viewing gamma, including the
Moon headset exponent, is **not baked into these tiles**.

Apollo 15 uses `contrast_fraction = 0.25`: the initial 0.75 constraint clipped
about 14% of its full-resolution NAC output to black. Comparing the same fixed
calibration grid showed that the lower floor preserves shadow values and
reduces held-out brightness error. This is a recorded project choice, not a
universal default or a correction of illumination direction. Inspect rendered
clipping as well as held-out fit errors before accepting a new source.

## Project and source configuration

See [`projects/moon/matched-overlays`](../projects/moon/matched-overlays) for six
complete, pinned Apollo projects. The project format is independent of Apollo:

- `format_version = 1`, `kind = "matched-overlay"`, and the algorithm identifier.
- `grid`: Mercator projection and the body's spherical radius. `target_crs` is
  project-relative and must describe the same grid. Version 1 supports bounded
  regions wholly inside one Mercator world; polar and antimeridian-spanning
  sources need a separate implementation, not implicit wrapping.
- `tile_size`, `minimum_zoom`, and an optional descriptive `product_id`.
- `reference_descriptor_sha256`: exact hash of the base `product.json`.
- `matching`: fixed `calibration_zoom`, `block_pixels`, `contrast_fraction`,
  `trim_fraction`, and `maximum_canvas_pixels` (at most 16,777,216).
- `sources`: unique safe IDs and priorities, geographic bounds, attribution in
  `credit`, maximum zoom, blend width and an authenticated `inputs` list.
- Optional per-source `fit_block_pixels` overrides the common fitting-cell
  spacing for small footprints while keeping calibration and blend resolution
  fixed. Choose cells coarser than the reference's useful resolution. Apollo
  11's landing layer uses four calibration pixels (about 167 projected metres)
  so its narrow footprint retains enough spatially held-out samples.
- Raster sources declare `kind = "raster"`, one or more `rasters` (relative path,
  expected dimensions and datatype), `encoding`, `scale`, optional `offset`,
  inclusive `valid_range`, and optional `nodata` values. All GDAL-reported file
  dependencies must appear in `inputs`; detached labels alone are insufficient.
- Archive sources declare `kind = "zoomify"` and an authenticated `metadata`
  file using the existing registered region/coverage schema. Cached JPEGs must
  have their matching URL/hash receipts. This command performs no downloads.

Unknown semantic fields are rejected. Input paths are relative to `--source-root`;
CRS and quality-mask paths are relative to the project. Absolute paths and
environment substitutions do not belong in versioned projects.

## Quality masks

A source may supply `quality_mask = { path = "mask.json", sha256 = "…" }`.
The mask document contains `format_version = 1`, `source_inputs_sha256` (canonical
identity hash of that source's `inputs` array), and `exclude_multipolygon` using
closed longitude/latitude rings, with optional review/evidence text. Polygon
coordinates refer to the declared target body, not implicitly to Earth.

Exclusions apply to fitting, blend construction, and output coverage. The mask
must conservatively cover the defect plus any resampling contamination: masking
is applied on the target grid, after the source has been sampled. A later,
valid higher-priority source may cover a lower source's exclusion.

Apollo 16 includes a manually traced exclusion around the bright striped patch
confirmed in the original Kaguya raster. Its file records native crop coordinates,
the outline, source binding and rationale. The underlying WAC appears there.
Bright craters elsewhere are not automatically classified as defects.

## Build, review and collect

Supply separately located inputs, archive cache, reference product, working data
and a new output directory. Keep durable production inputs and final products
under the site's `/data` layout. A source root may contain read-only symlinks to
the admitted raster and metadata files in their existing stores.

```sh
UV_CACHE_DIR=.cache/uv uv run pas-de-geant-textures build-overlay \
  projects/moon/matched-overlays/apollo16.toml \
  --source-root "$OVERLAY_INPUTS" --archive-root "$ARCHIVE_CACHE" \
  --reference-root "$WAC_PRODUCT" --work-root "$OVERLAY_WORK" \
  --output-root "$NEW_OVERLAY_PRODUCT"

UV_CACHE_DIR=.cache/uv uv run pas-de-geant-textures validate-preview-tiles \
  "$NEW_OVERLAY_PRODUCT"
```

For an economical visual review, add `--maximum-zoom 11`. This override is
recorded in the descriptor and identity; it cannot be below the calibration zoom.
It produces a distinct review product, not a relabelled full-resolution build.
Repeat with the six recipes, then use the existing `collect-preview-tiles
--input apollo11 … --input apollo12 …` command to produce the aggregate overlay
product. The base remains the separate pinned global product.

The final product contains `matching.json`, embedded matching evidence in
`product.json`, source and tool provenance, authenticated tile checksums, and
full PNG/opacity validation. Matching evidence reports coefficients, held-out
errors/correlation, clipping, actual blend scales and quality masks. Validation
authenticates the external matching report as well as its embedded copy.
Collection retains the embedded reports in the copied input descriptors.

The build preflights source hashes, grid compatibility, canvas size, root
separation and a conservative disk estimate. Raw raster linearization processes
128 rows at a time. Each raster level is warped once to disk and read by tile;
GDAL warp and cache budgets are each 128 MiB. A single raw level is limited to
one billion float pixels (4 GB). The bounded regional calibration canvas is the
main RAM cost; the largest allowed canvas can require roughly 1–2 GB while
constructing the blend. Reduce the calibration zoom or split a larger region.

Outputs are built under a sibling `.building` directory, validated, then renamed
atomically. An existing final product is never overwritten. Rerunning an
interrupted identical build reuses authenticated linearized raster stages and
rebuilds downstream fields/tiles; changed code, tools or settings require a new
output name. Full-resolution live builds and headset acceptance remain separate
from a successful reduced-zoom producer review.
