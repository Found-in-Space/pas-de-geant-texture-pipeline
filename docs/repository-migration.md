# Repository consolidation — 14 October 2026

Planetary imagery and scientific elevation now share repository ownership while
remaining independently installable and runnable. The existing GitHub imagery
repository is renamed to `Found-in-Space/planetary-surfaces`; the local-only
terrain repository is merged into it. The GitHub repository retains its identity.

| Previous repository | New directory | Package name (unchanged) | Command (unchanged) |
| --- | --- | --- | --- |
| `pas-de-geant-texture-pipeline` | `imagery/` | `found-in-space-pas-de-geant-texture-pipeline` | `pas-de-geant-textures` |
| `terrain-pipeline` | `elevation/` | `found-in-space-terrain-pipeline` | `fis-terrain` |

## History preservation

No original commits were rewritten or squashed. File moves are ordinary commits;
a merge joins the two formerly unrelated histories. All 11 imagery commits and
all 4 elevation commits present at migration are ancestors of `main`.

Original branch tips are retained as lightweight tags:

| Tag | Original commit |
| --- | --- |
| `pre-consolidation/imagery/main` | `7a8b02c3f65f9690e257deccce1c14b99755ba8d` |
| `pre-consolidation/imagery/codex/shared-grid-migration` | `492ea4b81656c20154d50f26fd9afe489e403587` |
| `pre-consolidation/elevation/main` | `c5c1ec6290c14e855c8901550de0ebf2e1c0167c` |

The imagery development branch is included, including its previously local
256-pixel Apollo and matched-overlay work. There were no source release tags,
open pull requests or GitHub Pages site at migration. Verified Git bundles of
both source repositories and a machine-generated ref/commit inventory are kept
in the maintainer's durable workspace archive.

Trace a moved file with `git log --follow -- imagery/path/to/file` or
`git log --follow -- elevation/path/to/file`. Original commit URLs remain useful
because those exact objects are retained. Historical publications, checksums,
dataset identifiers and provenance are not rewritten.

## Existing clones and commands

In an existing imagery clone, first preserve any local work, then:

```sh
git remote set-url origin git@github.com:Found-in-Space/planetary-surfaces.git
git fetch origin --tags
git switch main
git merge --ff-only origin/main
cd imagery
UV_CACHE_DIR=.cache/uv uv sync --frozen
```

For a new checkout:

```sh
git clone git@github.com:Found-in-Space/planetary-surfaces.git
cd planetary-surfaces/elevation
UV_CACHE_DIR=.cache/uv uv sync --frozen
```

Run old recipe commands from `imagery/` or `elevation/` respectively. Their
internal relative paths remain intact. Recreate virtual environments at the new
locations; do not move an existing environment. External scripts that address
checkout files need the appropriate new directory prefix. Generated datasets
and live service paths do not move as part of this migration.

New Git dependency pins use the exact consolidated SHA and a subdirectory, for
example in `tool.uv.sources`:

```toml
found-in-space-pas-de-geant-texture-pipeline = { git = "https://github.com/Found-in-Space/planetary-surfaces.git", rev = "<exact-commit-sha>", subdirectory = "imagery" }
found-in-space-terrain-pipeline = { git = "https://github.com/Found-in-Space/planetary-surfaces.git", rev = "<exact-commit-sha>", subdirectory = "elevation" }
```

Old pins remain at their original SHA and original root layout. Do not add a
subdirectory to a historical pin or regenerate its publication evidence merely
to reflect the repository rename. Do not recreate a repository at the old
GitHub name, which would displace its redirect.

## Acceptance checks

Verified locally with Python 3.13.12: 69 imagery tests and 14 elevation tests
passed, including native GDAL tests. Both frozen installs, Ruff checks and
standalone CLI examples passed. The imagery example reconstructs all five
tiles and its polar base; elevation validates nine tiles with maximum encoding
error at or below 1/512 metre.

- Independent frozen installs, CLI help and complete test suites for both
  workflows, with native GDAL checks enabled.
- Small generated examples using each installed CLI, with imagery pixel
  reconstruction and elevation numerical validation.
- Original source, recipe, resource and lockfile blobs preserved at their new
  paths; unchanged processing contracts and artifact formats.
- All original commits reachable from `main`, original tips retained by tags,
  and Git object integrity checked before publication.

The shared repository does not imply shared photometry, scalar resampling or
validation semantics. Rendering capabilities belong in reusable runtimes;
applications compose them. Future shared utilities require demonstrated common
behavior and their own compatibility checks.
