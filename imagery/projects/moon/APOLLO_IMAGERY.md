# Six-site Apollo display imagery

These recipes extend the existing Apollo 11 product to Apollo 12, 14, 15, 16
and 17. Each uses 100 km square Kaguya TC ortho context and registered LROC
NAC imagery inside a 25 km square, clipped to the actual source footprint.
The shared grid is lunar spherical Web Mercator XYZ, radius 1,737,400 m, with
square 256 × 256 tiles. These are local development products, not catalog
publications or measurements of terrain height.

| Site | NAC mosaic | Archive display sampling | Maximum detail zoom |
| --- | --- | ---: | ---: |
| Apollo 11 (existing) | HIA regional / LOA landing | 1.3 / 0.52 m | 16 / 17 |
| Apollo 12 | LOA | 1.1 m | 16 |
| Apollo 14 | LOB | 1.5 m | 15 |
| Apollo 15 | LOD | 1.4 m | 15 |
| Apollo 16 | HIA | about 0.635 m | 17 |
| Apollo 17 | LOC | 1.3 m | 15 |

The new caps are the first integer zoom retaining each archive pyramid's
sampling at the landing latitude in both grid directions. Apollo 16's browse
pyramid was resampled from its 0.5 m native mosaic; use its registered browse
sampling. Oversampling adds no source detail. Kaguya context uses zoom 13 and
the same source-wide DN display range as Apollo 11. No individual tile has an
independent stretch. Illumination and source seams remain visible.

NAC acquisition uses the official registered Zoomify JPEG pyramids, with
checksummed download receipts. It does not download the large native IMG
mosaics. PDS label ranges, browse masks, registration header ranges and
ImageProperties XML are checked against the existing generated metadata from
Pas de Géant's `build-apollo-regional-preview-metadata.py`.

## Acquisition and production

Set an explicit durable data root, immutable run ID, metadata root and
validated existing Apollo 11 product root. Run from the `imagery/` directory:

```sh
UV_CACHE_DIR=.cache/uv uv run python projects/moon/acquire_imagery.py \
  --data-root "$FIS_DATA_ROOT" --run-id "$APOLLO_IMAGERY_RUN" \
  --metadata-root "$APOLLO_METADATA_ROOT" --discover-only
UV_CACHE_DIR=.cache/uv uv run python projects/moon/acquire_imagery.py \
  --data-root "$FIS_DATA_ROOT" --run-id "$APOLLO_IMAGERY_RUN" \
  --metadata-root "$APOLLO_METADATA_ROOT"
UV_CACHE_DIR=.cache/uv uv run python projects/moon/build_imagery.py \
  --data-root "$FIS_DATA_ROOT" --run-id "$APOLLO_IMAGERY_RUN" \
  --apollo11-root "$APOLLO11_RUNTIME_ROOT" --allow-download
```

Review `acquisition/plan.json` before the second command. The five new sites
declare twenty 10800 × 10800 UInt16 context images: 4,665,600,000 raw bytes.
The free-space gate is 35 GB for inputs, working rasters, authoring tiles,
archive JPEGs and prepared PNGs. Two context downloads and two site builds can
run concurrently; each site allows eight archive requests. Omit
`--allow-download` for replay from a complete archive cache.
With acquisition already running, `build_imagery.py --wait-for-sources` can
start each site after all of its raw inputs have passed admission; it waits
at most six hours for missing inputs and rechecks every source receipt.

Transfers stage under `incoming/surfaces/moon/<run-id>`; verified context
sources move into `raw/surfaces/moon/<run-id>`. Evidence lives under
`runs/surfaces/<run-id>`, including exact recipes, registered metadata, source
receipts, GDAL inspection, stage commands, logs and validation reports.
Preserve the producer revision, code snapshot and lockfile alongside this
evidence when working from a dirty development checkout.

Each site is fully decoded and checksum validated before atomic promotion to
`derived/surfaces/moon/<run-id>/apollo<mission>`. Successful sites survive a
later site's failure. Restart authenticates completed products and reuses
source receipts; unfinished preparation regenerates output PNGs. Recipes and
source evidence for a run must remain immutable.

The final `all-sites` collection has one descriptor and prefixes each site's
providers and paths. `collect-preview-tiles` preserves pixels, grids,
priorities and zoom caps, then validates the entire collection before
promotion. Payloads are hardlinked on the same filesystem, avoiding duplicate
storage. Treat every linked path as immutable. Input descriptors and manifests
remain embedded under `inputs/`.

These commands do not change viewer configuration or public hosting.
Consumer and physical headset acceptance are separate checks.

Sources: [JAXA Kaguya TC seamless ortho v2](https://darts.isas.jaxa.jp/en/datasets/sln-l-tc-5-ortho-map-seamless-v2.0),
[LROC Apollo 12](https://data.lroc.im-ldi.com/lroc/view_rdr/NAC_ROI_APOLLO12LOA),
[Apollo 14](https://data.lroc.im-ldi.com/lroc/view_rdr/NAC_ROI_APOLLO14LOB),
[Apollo 15](https://data.lroc.im-ldi.com/lroc/view_rdr/NAC_ROI_APOLLO15LOD),
[Apollo 16](https://data.lroc.im-ldi.com/lroc/view_rdr/NAC_ROI_APOLLO16HIA),
[Apollo 17](https://data.lroc.im-ldi.com/lroc/view_rdr/NAC_ROI_APOLLO17LOC).
