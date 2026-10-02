# Pas de Géant texture pipeline

Reproducible production of planetary display textures for Pas de Géant.

This repository owns acquisition verification, source inspection, coordinate
conversion, multi-source compositing, pyramid generation, tile emission, and
validation. It is designed for more than one upstream image and more than one
target body. The first planned product is the Moon's LROC WAC global morphology
mosaic, but the architecture must also accommodate later lunar detail layers,
Mars, Venus, and deliberately constructed Earth imagery.

The repository name is intentionally application-specific while the project
model is target-neutral. It does not contain Pas de Géant viewer code and it
does not publish large tile trees to Git.

## Ownership boundary

| Location | Responsibility |
| --- | --- |
| This repository | Deterministic texture production and validation |
| `pas-de-geant` | Tile consumption, proxy configuration, and viewer integration |
| `catalogs` | Citable publication metadata, evidence, checksums, and producer SHA |
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
src/foundinspace/        Producer implementation (initially a package shell)
tests/                   Synthetic fixtures and contract tests
```

Raw downloads, working rasters, generated tiles, and run evidence live outside
Git. Their locations will be supplied to the CLI or project-local run config;
they must never be inferred from machine-specific absolute paths committed to a
product definition.

## Planned CLI

The implementation should expose one stage-oriented command, provisionally
`pas-de-geant-textures`, with these operations:

```text
inspect-source
preflight
build-base
build-levels
emit-tiles
validate
report
run
```

The exact command surface is not implemented yet. See
[`docs/implementation-plan.md`](docs/implementation-plan.md) for the handoff.

## First product

The initial product is documented at
[`projects/moon/lroc-wac-global-100m/README.md`](projects/moon/lroc-wac-global-100m/README.md).
It targets opaque 8-bit grayscale PNG tiles at zoom levels 0–8 using a square
geographic XYZ matrix with 512-pixel tiles.

