# Apollo 11 Mercator preview migration candidate

This format 2 recipe produces the Apollo source selection for the shared 3D
world runtime. It uses the lunar Mercator grid declared in the new global WAC
recipe. The existing geographic recipe remains the 2D archive comparison input.

**Quest imagery warning:** this recipe declares 512 × 512 tiles. Prior physical
Quest testing found performance problems with 512-pixel imagery; normal Quest
sessions use 256 × 256 across bodies and providers. The recipe and its sampling
table describe the existing 512-pixel candidate, not acceptance for normal
headset use. Prepare and validate a genuine 256-pixel runtime derivative with
reviewed source caps and new authenticated identities before promotion. See the
[consumer performance decision](../../../docs/tile-contract.md#quest-consumer-performance-decision).
This note changes no recipe or payload; scientific elevation is separate.

The same admitted Kaguya registration and archive metadata are used. GDAL
reprojects Kaguya into Mercator. NAC regridding samples nonlinear latitude rows
at target pixel centres; footprint holes retain the complete lower-priority
parent, and valid black samples remain data. All final runtime tiles are opaque.
There is no Apollo renderer, planner or special height path.

At Apollo 11 (0.67416°), approximate sampling in both directions is:

| Source | Declared source m/pixel | Cap | Mercator target m/pixel |
| --- | ---: | ---: | ---: |
| Kaguya context, 100 km band | 8.423 | 13 | 5.205 |
| Regional NAC, 25 km band | 1.3 | 16 | 0.651 |
| Landing NAC, 5 km band | 0.52 | 17 | 0.325 |

The output uses square 256 × 256 tiles. These caps retain the declared source sampling in both directions. Oversampling
does not add source detail. They replace the old geographic preview caps only
in this new recipe, with larger target tile counts to review before acquisition.
Coverage masks are from coarser supporting rasters; fine illumination seams and
geometric coverage are not claims of seamlessness or scientific resolution.

Replay using existing authenticated sources and metadata, with new independent
work/output roots on the persistent `/data` volume. `build-preview` runs offline; archive acquisition in
`prepare-preview-tiles` requires explicit `--allow-download`.

```sh
UV_CACHE_DIR=.cache/uv uv run pas-de-geant-textures build-preview \
  projects/moon/apollo11-preview-mercator-v2/preview.toml \
  --source-root "$GRID_KAGUYA_ROOT" --detail-root "$GRID_METADATA_ROOT" \
  --work-root "$GRID_PREVIEW_WORK_ROOT" --output-root "$GRID_PREVIEW_ROOT"
UV_CACHE_DIR=.cache/uv uv run pas-de-geant-textures prepare-preview-tiles \
  "$GRID_PREVIEW_ROOT" --source-root "$GRID_ARCHIVE_CACHE" \
  --output-root "$GRID_RUNTIME_ROOT"
UV_CACHE_DIR=.cache/uv uv run pas-de-geant-textures validate-preview-tiles \
  "$GRID_RUNTIME_ROOT"
```

Use `--allow-download` only after reviewing the cache, disk budget and window
estimates. Preparation embeds the explicit grid, source/metadata/payload
checksums, producer code hashes and exact source caps. The application rejects
an Apollo product whose grid differs from global imagery.

Serve the prepared root with `PAS_DE_GEANT_LUNAR_RUNTIME_DIRECTORY`; keep
`PAS_DE_GEANT_LUNAR_PREVIEW_DIRECTORY` on the geographic study product. The
comparison page explicitly rejects Mercator study input. Point global imagery
at the new Mercator WAC product and independently admit matching elevation.
No existing payload, application server or Quest session is changed by adding
this recipe.
