# Display-texture tile contract

This contract is intentionally independent of any particular source or target
body. Individual products may choose different zoom ranges or color encodings,
but deviations must be explicit and supported by the Pas de Géant consumer.

## Baseline contract

- Geographic longitude/latitude target grid covering the declared body extent.
- XYZ addressing: `x` increases eastward and `y` increases southward.
- Square `2^z × 2^z` matrix with one whole-body tile at zoom 0.
- Pixel centers sample a uniform linear-longitude/linear-latitude grid.
- 512 × 512 pixels per tile.
- Opaque PNG for display imagery.
- Path `imagery/{z}/{x}/{y}.png`.
- No independent per-tile stretch, normalization, or color adjustment.
- Missing coverage is represented by the product's declared opaque fallback
  pixel unless a future, separately versioned consumer contract says otherwise.

For bounds `[west, south, east, north]`, a tile at `(z, x, y)` covers:

```text
n = 2^z
tile_west  = west  + (east - west) * x       / n
tile_east  = west  + (east - west) * (x + 1) / n
tile_north = north - (north - south) * y       / n
tile_south = north - (north - south) * (y + 1) / n
```

The antimeridian is a wrap boundary between the western edge of `x = 0` and the
eastern edge of `x = n - 1`; it is not duplicated as an extra column.

## Pyramid construction

The highest product level is built on the declared target grid. Lower levels
are generated using a declared area-averaging rule. The first implementation
should derive every lower level directly from the highest-resolution base so
that repeated byte rounding does not accumulate between levels.

Each level is materialized as a tiled intermediate whose block boundaries align
with output tiles. Emission copies exact 512-pixel windows without another
resampling step.

## Required product metadata

The output root should include generated, machine-readable metadata recording:

- product and target IDs;
- bounds, CRS resource checksum, and axis conventions;
- tile size, addressing, path template, zoom range, pixel type, channels, and
  opacity;
- nodata/missing-coverage rendering;
- resampling and rounding rules;
- source identities and checksums;
- per-level dimensions, tile counts, byte sizes, and manifest checksums;
- producer Git SHA and tool versions.

Metadata filenames and their schema must be fixed during implementation before
the first publication.

## Topography exclusion

This contract is for visual color/intensity samples. It must not be reused for
elevation simply because both products can be tiled. Topography requires a
separate contract for units, vertical datum, numeric precision, nodata,
interpolation, quantization, range, and potentially mesh continuity.

