# Texture projects

Each directory describes one independently buildable and publishable texture
product. Product definitions may share target CRS resources and source
specifications, but must pin their semantic inputs explicitly.

Suggested hierarchy:

```text
projects/<target>/<product>/
```

A production product should eventually contain:

- `project.toml` using the current format version;
- one or more acquisition specifications under `sources/`;
- a README explaining purpose, source choice, and unresolved decisions;
- only small reviewed inputs needed to define the build.

Do not put downloads, working rasters, tiles, run logs, or credentials here.
Those belong in external run roots and generated evidence bundles.

