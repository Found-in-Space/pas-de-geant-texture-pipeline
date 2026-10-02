# Catalog publication handoff

The producer creates an evidence bundle; `catalogs` turns a reviewed bundle and
an immutable payload into a citable release. Neither repository should
reconstruct facts owned by the other.

The generated handoff must include:

- normalized project configuration and its checksum;
- target CRS resource and checksum;
- source landing pages, exact retrieval URLs or methods, retrieval timestamps,
  response metadata, byte sizes, and SHA-256 checksums;
- complete pre-conversion source metadata reports;
- producer Git SHA, clean-state assertion, Python version, and external tool
  versions;
- exact stage commands/configuration, state records, timings, and logs;
- product metadata and tile contract;
- per-level dimensions, counts, and measured disk usage;
- validation report;
- payload manifest and checksum(s);
- immutable object-storage dataset ID or prefix;
- license, notice, references, and source citations.

The publication must pin a public producer commit. Exploratory results from a
dirty checkout, path dependency, editable install, `PYTHONPATH` injection, or
environment override are not release artifacts.

The tile tree remains outside ordinary Git. The publication authenticates it
with manifests and immutable storage identity. If the product is rebuilt from
changed sources, changed processing, or a changed producer revision, publish a
new payload identity rather than replacing the old one.

