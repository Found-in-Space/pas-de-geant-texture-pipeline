# Apollo terrain example

This first recipe covers Apollo 11, 12, 14, 15, 16 and 17. It is an example of
the generic source/area contract, with no Apollo behavior in the production
engine or consumer renderer.

Source hierarchy, from fallback to detail:

1. NASA SVS LOLA, 64 samples/degree, unsigned values representing
   `0.5 × DN − 10000` metres. Attach the documented global pixel-edge
   registration on the 1,737,400 m sphere without changing source values.
2. SLDEM2015, 512 samples/degree, for a native-grid window extending 1.5° each
   way around each site. Its Float32 values are heights in kilometres relative
   to the same sphere: multiply by 1000, without adding the label's radius.
   Acquire full-row byte ranges from the uncompressed archived IMG files,
   retain and hash the exact ranges, and extract the native pixels. Adjacent
   latitude windows around Apollo 11 join without resampling. Western source
   longitudes are re-expressed with an explicit −360° shift.
3. Published Float32 LROC NAC DTMs, with their embedded lunar CRS, actual
   nodata masks and metre heights. Apollo 11/12/14/15/16 use 2 m sample spacing;
   Apollo 17 uses the 5 m valley mosaic. Preserve labels and README evidence.

The global fallback reaches zoom 6. Context reaches zoom 9; 2 m DTM footprints
reach zoom 14, and the 5 m mosaic reaches zoom 12. These caps retain native
sampling in both projected axes. They do not describe independent measurements
at every output pixel. The same scalar layers supply coarse and fine tiles.

All context precedes all local DTMs. Each overlay feathers to the previous
height surface over 128 m inside its actual valid mask. This blend is declared
for display continuity. Source overlap differences remain in per-tile reports;
there is no estimated vertical correction or height exaggeration. Confidence
maps are not used as rejection masks in this initial example. Stereo-derived
heights have documented errors and artifacts; sample spacing is not accuracy.

Review free disk, source metadata and source/output roots before acquisition.
The DTM payload is roughly 1.7 GB. Retained SLDEM row ranges, the global source,
tile payload and working evidence add several GB. Commands run from this repo:

```sh
UV_CACHE_DIR=.cache/uv uv sync --frozen
UV_CACHE_DIR=.cache/uv uv run python projects/moon/acquire_apollo.py --discover-only
UV_CACHE_DIR=.cache/uv uv run python projects/moon/acquire_apollo.py
UV_CACHE_DIR=.cache/uv uv run python projects/moon/prepare_apollo.py \
  --global-source /path/to/admitted/ldem_64_uint.tif
UV_CACHE_DIR=.cache/uv uv run fis-terrain plan .cache/apollo-project/project.toml
UV_CACHE_DIR=.cache/uv uv run fis-terrain build .cache/apollo-project/project.toml \
  --output .cache/products/moon-apollo-v1
UV_CACHE_DIR=.cache/uv uv run fis-terrain validate .cache/products/moon-apollo-v1
UV_CACHE_DIR=.cache/uv uv run python projects/moon/check_apollo.py \
  --product .cache/products/moon-apollo-v1 --output .cache/apollo-site-checks.json
```

The preparation adapter requires the already admitted exact NASA SVS source.
The build defaults to four tile workers with at most eight queued results.
GDAL reader access is serialized per input; numeric processing and lossless
PNG emission can overlap. `--workers 1` provides serial operation. Worker count
is recorded with the recipe, and tests compare serial/parallel tile bytes and
manifest order. The independent site check compares prepared pixel centres
with native Float32 neighbours outside the declared transition.
It generates a project with explicit paths/conversions, source specifications
and retained acquisition evidence. Another area can supply its own project and
specifications directly using `fis-terrain inspect` and `acquire-window`; another
spherical body supplies its own radius/CRS/datum. The engine currently supports
spherical Mercator products within ±85.05112878° and nonwrapping detail bounds.
Polar height products, ellipsoidal/geoid conversions and geographic output
require separate declared implementations.

For local Pas de Géant validation, set
`PAS_DE_GEANT_LUNAR_ELEVATION_DIRECTORY` to the completed product's `elevation`
directory and use matching Mercator imagery. The application loads the
descriptor, selects the finest available ancestor and uses the shared renderer.
Desktop/Quest visual and performance acceptance must be recorded separately.
These initial outputs are scratch, without public hosting or a catalog release.

Primary sources:

- [NASA CGI Moon Kit and LOLA encoding](https://svs.gsfc.nasa.gov/4720/)
- [SLDEM2015 description](https://www.usgs.gov/media/images/lro-lola-and-kaguya-terrain-camera-dem-merge-60n60s-512ppd)
- [Archived SLDEM2015 Float32 labels and IMG files](https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/data/sldem2015/tiles/float_img/)
- [Apollo 11 DTM](https://data.lroc.im-ldi.com/lroc/view_rdr/NAC_DTM_APOLLO11)
- [Apollo 12 DTM](https://data.lroc.im-ldi.com/lroc/view_rdr/NAC_DTM_APOLLO12)
- [Apollo 14 DTM](https://data.lroc.im-ldi.com/lroc/view_rdr/NAC_DTM_APOLLO14)
- [Apollo 15 DTM](https://data.lroc.im-ldi.com/lroc/view_rdr/NAC_DTM_APOLLO15)
- [Apollo 16 DTM](https://data.lroc.im-ldi.com/lroc/view_rdr/NAC_DTM_APOLLO16)
- [Apollo 17 valley mosaic](https://data.lroc.im-ldi.com/lroc/view_rdr/NAC_DTM_APOLLO17)
