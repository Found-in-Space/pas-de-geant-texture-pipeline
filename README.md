# Planetary surfaces

Prepare planetary imagery and elevation through independently usable workflows.
Part of [Found in Space](https://foundin.space/): explore, question and build with
scientific data and models.

| Workflow | Start here | Existing command | Output |
| --- | --- | --- | --- |
| Display imagery | [Imagery guide](imagery/README.md) | `pas-de-geant-textures` | Reprojected and composited display textures, opaque tiles and sparse overlays |
| Scientific elevation | [Elevation guide](elevation/README.md) | `fis-terrain` | Scalar heights with explicit units/datums, lossless Terrarium tiles and numeric validation |

Each directory is a complete Python project with its own dependencies, lockfile,
recipes, examples and tests. Install only the workflow you need. Python 3.13+
and [uv](https://docs.astral.sh/uv/) are required. Imagery also uses the system
GDAL/PROJ command-line tools (`gdal-bin` and `proj-bin` on Ubuntu).

## Run a small example

Choose one route from the repository root:

```sh
cd imagery
UV_CACHE_DIR=.cache/uv uv sync --frozen
UV_CACHE_DIR=.cache/uv uv run python examples/synthetic.py /tmp/surface-imagery-example
```

```sh
cd elevation
UV_CACHE_DIR=.cache/uv uv sync --frozen
UV_CACHE_DIR=.cache/uv uv run python examples/synthetic.py /tmp/surface-elevation-example
```

Both examples generate tiny local rasters, run the real producer commands and
validate the output without downloading source data. Use a new output directory
for each run. These disposable examples are synthetic scratch, never live
service datasets or publication evidence. Real sources, completed products and
evidence belong on persistent storage outside the checkout.

To contribute, run an example, change its source values or a transformation,
then run the relevant checks and open a pull request here. See
[CONTRIBUTING.md](CONTRIBUTING.md) for focused checks and review boundaries.

## Responsibilities and compatibility

This repository owns source acquisition, transformations, validation and exported
artifacts. Reusable runtime packages own loading, querying, analysis and rendering
capabilities. Applications such as [Pas de Géant](https://github.com/Found-in-Space/pas-de-geant)
compose those capabilities into experiences. [Catalogs](https://github.com/Found-in-Space/catalogs)
owns citable releases, evidence and references to immutable payloads.

Imagery retains its photometric and visual contract; elevation retains physical
units, vertical datums, masks and numerical validation. There is no combined
processing engine. Shared utilities can follow when common behavior is proven.

`pas-de-geant-texture-pipeline` and the local `terrain-pipeline` were consolidated
here on 14 October 2026. All original commits are ancestors of `main`, with
original tips tagged. Package names, commands and artifact formats are unchanged.
See the [migration and old-name map](docs/repository-migration.md), including
instructions for pinned dependencies and existing clones.

## Licence

Software and Found in Space-authored documentation use the [MIT License](LICENSE).
Upstream data and generated products retain their source terms; publications
must record those separately.
