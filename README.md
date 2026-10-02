# Pas de Géant texture pipeline

Reproducible production of planetary display textures for Pas de Géant.

Part of [Found in Space](https://foundin.space/), which makes scientific data
and models into materials people can explore, question, and build with.

This repository owns acquisition verification, source inspection, coordinate
conversion, multi-source compositing, pyramid generation, tile emission, and
validation. It is designed for more than one upstream image and more than one
target body. The first planned product is the Moon's LROC WAC global morphology
mosaic, but the architecture must also accommodate later lunar detail layers,
Mars, Venus, and deliberately constructed Earth imagery.

The repository name is intentionally application-specific while the project
model is target-neutral. It does not contain Pas de Géant viewer code and it
does not publish large tile trees to Git. The repository is currently a
planning scaffold; the production CLI and raster pipeline are not implemented
yet.

## Ownership boundary

| Location | Responsibility |
| --- | --- |
| This repository | Deterministic texture production and validation |
| [Pas de Géant](https://github.com/Found-in-Space/pas-de-geant) | Tile consumption, proxy configuration, and viewer integration |
| [Found in Space Catalogs](https://github.com/Found-in-Space/catalogs) | Citable publication metadata, evidence, checksums, and producer SHA |
| Object storage/CDN | Immutable generated tile payloads and optional source archives |

Scientific topography is excluded. Elevation samples must preserve physical
values, datums, units, nodata semantics, and encodings; terrain may also require
mesh or normal-map generation. Those needs justify a separate producer even if
both producers eventually share conventions or a small geospatial library.

## Intended repository layout

```text
docs/                    Architecture, contracts, implementation, and QA plans
projects/                Versioned product definitions and product notes
resources/crs/           Reviewed target-body CRS definitions
src/foundinspace/pas_de_geant/textures/
                         Producer implementation (initially a package shell)
tests/                   Synthetic fixtures and contract tests
```

Raw downloads, working rasters, generated tiles, and run evidence live outside
Git. Their locations will be supplied to the CLI or project-local run config;
they must never be inferred from machine-specific absolute paths committed to a
product definition.

## CLI

The initial implementation exposes a stage-oriented `pas-de-geant-textures`
command. Acquisition and raster construction are intentionally separate so a
downloaded candidate cannot silently become a production input.

```text
download
inspect-source
preflight
build-base
build-levels
validate-project
```

Tile emission, complete product validation, final reporting, and orchestration
remain to be implemented. See
[`docs/implementation-plan.md`](docs/implementation-plan.md) for the phased
handoff.

Run the CLI through the locked environment:

```console
UV_CACHE_DIR=.cache/uv uv run pas-de-geant-textures --help
```

The processor currently delegates raster operations to the system
`gdalinfo`, `gdalwarp`, `gdal_translate`, and `proj` executables. Their exact
versions and commands are recorded in evidence and stage state. A pinned
distribution/container remains required before the first publication build.

## First product

The initial product is documented at
[`projects/moon/lroc-wac-global-100m/README.md`](projects/moon/lroc-wac-global-100m/README.md).
It targets opaque 8-bit grayscale PNG tiles at zoom levels 0–8 using a square
geographic XYZ matrix with 512-pixel tiles.

Its checked-in source specification remains explicitly `candidate`. Running
`download` records the actual object checksum and HTTP receipt, and
`inspect-source` records complete GDAL metadata. Those results must be reviewed
and promoted into an admitted source contract before `build-base` will run.

## Licence

Repository software and Found in Space-authored documentation are available
under the [MIT License](LICENSE). Upstream imagery and generated products retain
their own source terms; each publication must record those terms separately.
