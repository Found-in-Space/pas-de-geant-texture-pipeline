# Moon: LROC WAC global morphology 100 m

## Status

Planned first product. The full source has not been admitted, downloaded, or
tiled by this repository. Do not create `project.toml` with guessed metadata;
inspect the actual object and review its acquisition specification first.

## Source candidate

- Landing page: <https://astrogeology.usgs.gov/search/map/moon_lro_lroc_wac_global_morphology_mosaic_100m>
- Expected filename: `Lunar_LRO_LROC-WAC_Mosaic_global_100m_June2013.tif`
- Reported size: approximately 5.5 GB
- Reported raster: 109,164 × 54,582, one-band 8-bit grayscale
- Intended target body: Moon, reference radius 1,737,400 m

All reported properties are admission expectations, not yet verified facts.
Capture the actual bytes, checksum, HTTP metadata, and complete `gdalinfo -json`
before making the source contract authoritative.

The candidate acquisition specification is
[`sources/lroc-wac-global-morphology-100m.toml`](sources/lroc-wac-global-morphology-100m.toml).
It records the public USGS URL and reported properties without presenting them
as verified expectations. A local admission run is deliberately two-stage:

```console
UV_CACHE_DIR=.cache/uv uv run pas-de-geant-textures download \
  projects/moon/lroc-wac-global-100m/sources/lroc-wac-global-morphology-100m.toml \
  --source-root "$RUN_ROOT/source"

UV_CACHE_DIR=.cache/uv uv run pas-de-geant-textures inspect-source \
  projects/moon/lroc-wac-global-100m/sources/lroc-wac-global-morphology-100m.toml \
  --source-root "$RUN_ROOT/source" \
  --evidence-root "$RUN_ROOT/evidence"
```

`download` resumes through a hidden partial file, verifies any admitted size
and checksum, and promotes the payload atomically. For this candidate it records
the discovered SHA-256 and byte size without claiming that they are reviewed.
`inspect-source` records the full GDAL JSON plus normalized contract fields.
Review both generated records before adding `[expected]`, a reviewed source CRS
resource, and changing the specification status to `admitted`.

## Planned output

| Property | Planned value |
| --- | --- |
| Bounds | longitude −180° to +180°; latitude −90° to +90° |
| Addressing | XYZ; eastward `x`, southward `y` |
| Matrix | `2^z × 2^z`; one whole-Moon tile at zoom 0 |
| Tile size | 512 × 512 pixels |
| Encoding | opaque 8-bit grayscale PNG |
| Path | `imagery/{z}/{x}/{y}.png` |
| Zooms | 0–8, pending source and viewer validation |

Zoom 8 represents a 131,072 × 131,072 geographic grid, approximately 83 m
per horizontal pixel at the lunar equator. Latitude is intentionally sampled
more densely by the square matrix; source detail remains approximately 100 m.
The complete zoom 0–8 pyramid contains 87,381 tiles.

## Admission questions

- What CRS and lunar datum are actually embedded in the GeoTIFF?
- Are dimensions, band count, datatype, mask, nodata, scale, and offset exactly
  as reported?
- Are byte values already display-ready, or is a source-wide documented
  photometric transform required?
- How are genuinely missing pixels represented, and is opaque black the correct
  display fallback?
- What compressed size and temporary space result from a representative region?
- Do the source licence and LROC/USGS citation terms require additional notice?

## Consumer handoff

Pas de Géant will eventually point
`PAS_DE_GEANT_TILE_PROXY_LUNAR_IMAGERY_UPSTREAM_TEMPLATE` at the immutable
hosted prefix. Its imagery maximum zoom must be configured independently from
the existing LOLA elevation maximum zoom.
