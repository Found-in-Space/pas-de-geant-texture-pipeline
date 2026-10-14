# Found in Space terrain pipeline

Reusable planetary elevation production, starting with the Apollo landing sites.
Sources, horizontal registration, vertical units/datum, masks, priority and
transitions are explicit. Heights are resampled and composed as scalar metres
before lossless PNG encoding. This is independent of display-texture production
and Pas de Géant's renderer.

Read [contracts](docs/contracts.md) for the production and consumer interfaces.
Use Python 3.13+ and `UV_CACHE_DIR=.cache/uv uv sync`.

The [Apollo example](projects/moon/README.md) records acquisition, source
conversion, masks, blend choices, sampling caps and local consumer setup.
`fis-terrain` provides `inspect`, `plan`, `acquire`, `acquire-window`, `build`
and `validate`. A build retains `<output>.work` for resume and exposes its
descriptor only after numeric validation succeeds. All initial outputs are
marked scratch; publication is a separate catalogs handoff.
