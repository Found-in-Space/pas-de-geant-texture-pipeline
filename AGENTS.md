# Terrain pipeline

This repository produces reusable scientific elevation tiles. It owns source
admission, scalar reprojection/compositing, encoding and numeric validation.
Applications own rendering; catalogs owns citable publications.

- Use Python 3.13+, `uv sync`, `uv run`, and `uv run pytest`.
- Set `UV_CACHE_DIR=.cache/uv` for every uv invocation.
- Keep heights in declared physical units and datums. Never infer elevation
  from display imagery, stretch tile values, or interpolate encoded channels.
- Declare source hashes, metadata, registration, priority, masks and transitions
  in project files. Reject mismatches; keep generated evidence machine-produced.
- Process rasters in bounded windows. Keep raw data, tiles, work state and local
  paths outside Git. Complete builds publish descriptors atomically, last.
- Read README.md and docs/contracts.md before editing production code.
- Do not deploy, upload or create a catalog release from an exploratory dirty
  checkout. Record such products as scratch and preserve that status.
