# Planetary surfaces: elevation

Reusable planetary elevation production, starting with the Apollo landing sites.
This is the independent elevation project in [Planetary surfaces](../README.md).
Run all commands below from `elevation/`.
Sources, horizontal registration, vertical units/datum, masks, priority and
transitions are explicit. Heights are resampled and composed as scalar metres
before lossless PNG encoding. This workflow is independent of [display imagery](../imagery/README.md)
and reusable runtime rendering packages.

Read [contracts](docs/contracts.md) for the production and consumer interfaces.
Use Python 3.13+ and `UV_CACHE_DIR=.cache/uv uv sync`.

The [Apollo example](projects/moon/README.md) records acquisition, source
conversion, masks, blend choices, sampling caps and local consumer setup.
`fis-terrain` provides `inspect`, `plan`, `acquire`, `acquire-window`, `build`
and `validate`. A build retains `<output>.work` for resume and exposes its
descriptor only after numeric validation succeeds. All initial outputs are
marked scratch; publication is a separate catalogs handoff.

## Small example and checks

```sh
UV_CACHE_DIR=.cache/uv uv sync --frozen
UV_CACHE_DIR=.cache/uv uv run python examples/synthetic.py /tmp/surface-elevation-example
UV_CACHE_DIR=.cache/uv uv run pytest tests/test_terrain.py
```

The example generates a tiny lunar height raster with positive and negative
metre values, declares its sphere and source identity, builds nine Terrarium
tiles, and validates their numerical reconstruction. It downloads no source
data. Change the height formula in `examples/synthetic.py`, use a fresh output
directory, and inspect the resulting bounds and validation report. These are
synthetic scratch outputs. See [contribution checks](../CONTRIBUTING.md).
