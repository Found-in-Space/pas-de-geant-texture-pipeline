# Found in Space Catalogs publication handoff

The producer creates an evidence bundle; the Found in Space `catalogs`
repository turns a reviewed bundle and an immutable payload into a citable
release. Neither repository should reconstruct facts owned by the other. The
publication must be understandable from its own `publications/<release>/`
directory without access to private workspace notes.

Publication release IDs use `YYYYMMDD.N`, starting at `.1` each day. Before
assembly, decide whether the product is a standalone work with a new Zenodo
record or an immutable version of an evolving series. An evolving series keeps
one stable `series_id` and uses Zenodo's **New version** workflow.

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
- licence, notice, references, and source citations.

The resulting publication should include the standard files required by the
`catalogs` conventions: publication-specific `README.md`, `manifest.toml`,
`run_log.md`, generated `checksums.sha256`, `LICENSE.txt`, `NOTICE.md`, and
`REFERENCES.md` where applicable. Generated counts, object metadata, and
checksums must come from the final payload or evidence bundle rather than being
hand-edited.

The publication must pin a public producer commit. Exploratory results from a
dirty checkout, path dependency, editable install, `PYTHONPATH` injection, or
environment override are not release artifacts.

The tile tree remains outside ordinary Git unless a publication explicitly
chooses to include a packaged payload. Ordinarily the publication authenticates
the externally hosted tree with manifests and immutable storage identity. If
the product is rebuilt from changed sources, changed processing, or a changed
producer revision, create a new release and payload identity rather than
replacing the old one.
