# Agent Instructions

This Found in Space repository produces reproducible display-texture tile sets
for Pas de Géant. It is intentionally independent of the Pas de Géant
application and of the `catalogs` publication repository.

## Scope

- Support multiple planetary targets, including the Moon, Mars, Venus, and
  custom Earth products.
- Support one or more upstream raster sources per product.
- Produce display imagery with an explicit target CRS, tile scheme, blend
  policy, and validation record.
- Keep elevation, terrain, height maps, meshes, and scientific topography out
  of scope. Those products require value-preserving encodings and different
  validation contracts.
- Do not add Pas de Géant runtime or viewer behavior here. The application
  consumes the published tile contract.
- Do not turn `catalogs` into the implementation repository. A catalog
  publication pins this producer by Git SHA and records the immutable payload.

## Controlled-build rules

- Every material input and transformation must be declared in a versioned
  project file and represented in generated provenance.
- Reject unexpected source metadata rather than silently adapting it.
- Never hand-edit generated manifests, checksums, reports, or run state.
- Keep credentials, private URLs, environment files, local absolute paths, raw
  downloads, intermediates, and tile trees out of Git.
- Preserve bounded-memory operation. Full-resolution rasters must be processed
  in blocks or through tools with documented memory and spill limits.
- Use atomic output placement and restartable stages. A failed run must not
  look complete.
- Never stretch or normalise individual tiles independently. Photometric
  transforms and multi-source compositing rules belong to the declared build.
- Display tiles must be opaque unless a future contract explicitly introduces
  another product type.

## Python tooling

- Use Python 3.13 or newer and `uv` for dependency and environment operations.
- Set `UV_CACHE_DIR=.cache/uv` for every `uv` invocation.
- Do not use `pip`, `poetry`, or `conda` directly.
- Run entrypoints with `uv run`, tests with `uv run pytest`, and formatting and
  lint checks with `uv run pre-commit run --all-files` once those are present.

## Before implementing

Read, in order:

1. `README.md`
2. `docs/architecture.md`
3. `docs/project-format.md`
4. `docs/tile-contract.md`
5. `docs/implementation-plan.md`
6. `docs/testing.md`
7. The selected product under `projects/`

Do not download a large source or start a full build until the project file,
storage roots, disk budget, expected source metadata, and evidence capture have
been reviewed.
