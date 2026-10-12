# Sparse detail preview contract, version 1

The discriminator is `kind = "sparse-detail-preview"` with `formatVersion = 1`.
It is independent of the opaque display-texture contract. This local prototype
is consumed by Pas de Géant's imagery study page, not its 3D terrain renderer.

- The global longitude/latitude XYZ grid, lunar sphere and 512 × 512 tile
  dimensions match the core imagery grid.
- Materialized context PNGs have grayscale and alpha channels. Zero alpha is
  missing coverage; valid black terrain has positive alpha.
- `levels[].tiles` declares available context tiles. An absent tile is never
  discovered through a speculative failed request.
- Each detail references a registered, masked archive pyramid, a geographic
  band, a useful maximum grid zoom and an explicit priority. The consumer sorts
  priorities before compositing. Source-wide tone controls remain optional study
  adjustments; they do not change stored tiles.
- Above a source's maximum zoom, the consumer draws its capped geographic parent.
  It retains coarse context through masked detail pixels. Gaps in all extras
  expose the global core layer. Failed requests are reported separately from
  geometric gaps and retain successfully loaded lower-priority imagery.
- Context levels are averaged directly from the normalized source mosaic.
  Pixel masks clip them to the declared regional extent; empty tiles are omitted.
- Coverage summaries sample source masks, bands and priorities on a 1024 × 1024
  geographic grid. They describe approximate geometric coverage, not image
  quality, shadow compatibility, or seamlessness.

The manifest embeds the authoring recipe, source and metadata hashes, producer
code hashes, commit/dirty state, tool versions and commands. The materialized PNG
payload has generated checksums. Fine archive JPEGs remain remote referenced
inputs; the manifest does not authenticate every retrieved JPEG or claim that
the preview is an immutable, self-contained publication.

## Prepared tiles for the 3D runtime

`prepare-preview-tiles` converts this study product into a local
`kind = "sparse-opaque-xyz"`, `formatVersion = 1` product. It materializes
ordinary opaque grayscale PNGs on the same grid, grouped by context, regional
NAC and landing-site NAC provider. Each source declares `minimumZoom`,
`maximumZoom`, `priority`, `pathTemplate` and `levels[].tiles`.

The producer admits only complete context tiles. Partial boundary tiles are
omitted so the viewer selects its global source. NAC tiles are regridded with
bilinear sampling, clipped to the declared band and footprint, and composited
over the best available complete lower-priority parent. Footprint holes preserve
that parent; valid black pixels replace it. This preserves the existing opaque
runtime contract without an overlay, mask shader or browser compositor.

The viewer selects the finest available source ancestor, breaking resolution
ties by priority, before queueing the ordinary tile acquisition and decode.
Every resolved address has a stable provider for the lifetime of the product.
No request probes for unlisted tiles. Unexpected failures use the existing
failure and retry behavior rather than masquerading as coverage holes.

Acquisition requires explicit `--allow-download`. Archive JPEGs and receipts are
cached locally, verified by hash on reuse, and included in generated provenance.
Output PNGs are atomic; the complete manifest is placed only after the build
finishes. Restarting uses the authenticated archive cache and rebuilds tiles.
The prepared payload remains scratch evidence, with no seam correction or
claim of immutable publication.

## Explicit-grid preview and runtime (format version 2)

Version 2 requires the same `grid` object as the full display product. Context
warps use the declared projected CRS and extent. Archive bilinear regridding
and footprint/band masks use nonlinear target latitude centres for Mercator;
they do not stretch a geographic tile into a different grid. Parent crops
remain exact XYZ subdivisions on that grid. Preparation preserves the grid,
cap and provenance in its opaque runtime manifest; validation authenticates the
whole descriptor identity and payload manifests before decoding tiles.

The new `apollo11-preview-mercator-v2` recipe uses source caps chosen to retain
native sampling in both directions. See its README for sampling and cost
tradeoffs. Global, regional, landing and elevation grids must agree before the
shared runtime admits them. Source selection alone remains Apollo-specific.

The current 2D archive comparison is an explicitly geographic reader. Keep its
format 1 study product separate from the format 2 3D runtime root. The app's
`PAS_DE_GEANT_LUNAR_RUNTIME_DIRECTORY` selects the prepared root independently;
its geographic study base defaults to immutable WAC release `20261011.1` and
can be configured separately. A Mercator study descriptor is rejected rather
than drawn at incorrect latitudes. No old payload is relabelled.
