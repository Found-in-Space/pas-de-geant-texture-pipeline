# Apollo matched overlays

These six opt-in recipes replace the original clipped Kaguya stretch with
source-wide matching to the exact 256-pixel WAC product used in the Apollo 16
experiment. Regional NAC sources match their composited lower-priority imagery;
Apollo 11 additionally includes its landing layer. All layers share the global
Mercator grid and retain their declared native-resolution caps.

Use [`build-overlay`](../../../docs/matched-overlays.md). The source root must
contain each listed `.img`, `.lbl` and registered metadata JSON. Keep the existing
archive JPEG cache and its receipts available separately. No network acquisition
or runtime service switch is performed by this build.

The initial fitting/blending parameters come from the Apollo 16 visual
experiment. The recipes configure all sites; each site's new appearance still
needs review before a full product replaces its serving predecessor. Recipe
admission does not mean that all six full-resolution products have been rebuilt.

`apollo16-quality-mask.json` is a manually authored exclusion of the confirmed
striped plateau in the original Kaguya source. It records the native crop and
outline and is bound to exact source inputs. It falls through to WAC.

The recipes were derived from the existing authenticated Apollo collection's
input descriptors. To regenerate them from those same inputs:

```sh
UV_CACHE_DIR=.cache/uv uv run python projects/moon/create_overlay_projects.py \
  --collection-root "$APOLLO_COLLECTION" --reference-root "$WAC_PRODUCT" \
  --output-root projects/moon/matched-overlays
```

The generator checks descriptor identities, carries raw/metadata hashes and
source bounds forward, and rejects a curated mask whose source binding changes.
It does not invent or update a mask for changed upstream imagery.
