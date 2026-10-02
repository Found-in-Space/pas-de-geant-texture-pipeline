# Implementation plan

This is the implementation handoff. Complete the work in small, reviewable
phases; do not begin with the full 5.5 GB lunar source.

## Phase 1: contracts and toolchain spike

1. Choose the implementation boundary between Python and GDAL command-line
   tools. Prefer explicit subprocess commands when they make tool versions and
   exact operations easier to record; do not hide critical defaults.
2. Confirm Python 3.13 compatibility for the selected raster metadata and PNG
   libraries.
3. Define JSON schemas (or equivalently strict typed models) for project files,
   stage state, product metadata, validation reports, and manifests.
4. Add the versioned Moon target CRS with radius exactly `1,737,400 m`, then
   validate it with the chosen GDAL/PROJ versions.
5. Implement strict project parsing, canonical serialization, relative-path
   rules, and rejection of environment expansion.
6. Add CI, Ruff, pre-commit, and tests only after the dependency choices are
   proven locally.

Decision gate: record the chosen GDAL installation strategy. Python wheels that
quietly bundle a different GDAL/PROJ stack from the system tools can undermine
reproducibility.

## Phase 2: synthetic end-to-end product

Build a small projected lunar source and a zoom 0–2 product exercising the real
pipeline. The fixture must contain unmistakable north/south/east/west markers,
longitude and latitude gradients, antimeridian features, polar features,
constant regions, black and white samples, and masked holes.

Implement restartable stages:

1. `inspect-source`: capture complete source metadata and enforce expectations.
2. `preflight`: resolve identities, estimate disk, verify tools and free space,
   and refuse unsafe overlap between source/work/output roots.
3. `build-base`: normalize sources and create the highest target-grid level.
4. `build-levels`: create lower levels with the declared area rule.
5. `emit-tiles`: copy aligned windows into opaque PNGs using atomic writes.
6. `validate`: run structural, pixel, spatial, and pyramid checks.
7. `report`: generate manifests, checksums, timings, versions, and publication
   evidence.
8. `run`: orchestrate the same stages without bypassing their contracts.

Every stage needs a durable state record containing configuration identity,
input checksums, output checksums, start/end times, status, and diagnostic
paths. State must become complete only after atomic output promotion.

## Phase 3: multiple-source proof

Add a second synthetic source with partial coverage and deliberate overlap.
Prove at least `priority` compositing and one explicit regional/cutline case.
Tests must demonstrate stable results regardless of filesystem enumeration
order and must catch undeclared overlap behavior.

Do not implement sophisticated blending until a real product requires it. The
format should reserve the concept without guessing a scientifically acceptable
algorithm.

## Phase 4: admit the LROC WAC source

1. Recheck available space on `/data` and define separate source, work, output,
   and evidence directories.
2. Download through an explicit acquisition command or document the exact
   external retrieval. Record URL, time, response metadata, byte size, and
   SHA-256. Never package credentials.
3. Save complete `gdalinfo -json` output before conversion.
4. Compare actual dimensions, CRS, band, datatype, mask, nodata, scale, and
   offset with the current assumptions. Update the source specification only
   after review.
5. Confirm whether byte values are already display-ready. Do not add `-scale`
   or histogram normalization by default.
6. Run a representative regional build and measure compression, speed, memory,
   and temporary-space behavior.
7. Recalculate the full-run disk budget with safety margin.
8. Build the complete product only after the source contract and budget are
   accepted.

The intended maximum base is 131,072 × 131,072 pixels (zoom 8 with 512-pixel
tiles) over `[-180, -90, 180, 90]`. The complete zoom 0–8 pyramid contains
87,381 tiles. These are planned choices until the source inspection and Pas de
Géant integration confirm them.

## Phase 5: consumer integration and publication

In `pas-de-geant`, separate imagery maximum zoom from elevation maximum zoom
through configuration, proxy validation, viewer/provider construction, cache
keys, and fallbacks. Explicitly configure 512-pixel tiles and the one-tile
level-zero geographic matrix. Keep its local tile builder only for fixtures.

Validate the actual WAC product in the viewer at both poles, the antimeridian,
tile boundaries, and zoom transitions. Once accepted, create a `catalogs`
publication that pins this repository by exact public Git SHA and authenticates
the externally hosted payload.

## Open decisions

- GDAL/PROJ distribution and version pinning strategy.
- Raster I/O library used for exact-window validation and PNG emission.
- Manifest granularity for tens of thousands of objects.
- Canonical JSON and configuration identity rules.
- Published object-store prefix and immutability controls.
- Whether later color products use RGB PNG, another lossless format, or a new
  version of the consumer contract.

