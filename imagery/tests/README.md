# Tests

Implementation begins with generated synthetic raster fixtures, not the full
WAC download. Follow `docs/testing.md`; keep fixtures small, deterministic, and
code-generated where practical.

Do not commit large binary fixtures or tests that merely lock down incidental
strings and constants. Prefer behavioral tests for coordinate transforms,
compositing, pyramid math, exact tile windows, restartability, and reports.

