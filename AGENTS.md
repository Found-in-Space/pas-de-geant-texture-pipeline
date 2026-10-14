# Planetary surfaces

This repository owns planetary surface-data production through two independent
Python projects: `imagery/` for display textures and `elevation/` for scientific
heights. Read the selected project's `AGENTS.md`, README and contracts before
editing it. Run its tools from that directory.

- Use Python 3.13+, `UV_CACHE_DIR=.cache/uv uv sync --frozen`, and `uv run` with
  the same cache setting. Each workflow has its own environment and lockfile;
  neither requires installing the other. Do not add a combined dependency set.
- Preserve existing package names, CLI commands, recipes and artifact formats.
  Repository consolidation is not a format or package migration.
- Keep imagery photometry separate from scalar elevation, explicit units,
  datums, masks and numeric validation. Share code only for demonstrated common
  behavior; do not force a universal raster engine.
- Process large rasters in bounded windows. Keep downloads, build outputs,
  local paths, credentials and scratch evidence outside Git. Never hand-edit
  generated evidence. New tiles are square and no larger than 256 pixels.
- Producers own acquisition, transformations, validation and exported artifacts.
  Reusable runtime packages own loading, querying and rendering capabilities;
  applications own interaction and composition. Catalogs owns citable releases.
- Run the changed workflow's Ruff checks, tests and synthetic example. Run both
  workflows when changing repository layout or shared tooling.
- Preserve both original Git histories and `pre-consolidation/*` tags. Read
  `docs/repository-migration.md` before changing migration or compatibility rules.
