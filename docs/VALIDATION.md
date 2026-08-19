# Validation status — 2026-08-19

The full improved source tree was validated with:

- `python -m compileall -q app tests tools main.py`
- automated regression suite: run with `pytest -q`; the exact count is expected to grow as regression cases are added
- end-to-end DOCX generation against every bundled template
- template diagnostics against every bundled template: no blocking errors or warnings
- real DOCX → PDF conversion using the default backend chain on Linux: **LibreOffice** selected successfully and produced a valid `%PDF-` file
- real PDF → DOCX round-trip smoke conversion: a valid Word ZIP package was produced
- deterministic integrated-converter PDF generation test so CI does not depend on an external office installation
- generation regression tests proving failed DOCX/PDF output does not publish partial final files or consume sequence numbers prematurely
- schema migration tests for legacy local JSON and rejection of newer unsupported schemas
- backup rollback, malformed-settings, archive-safety, and future-schema tests
- scanner-cache mutation isolation and invalidation tests
- conversion backend selection/fallback/cancellation tests
- field-handler registry coverage and formatting/validation tests

GUI-specific smoke tests are skipped automatically when PySide6 is unavailable in the local review environment. `requirements-dev.txt` installs `requirements.txt`, so Windows CI installs PySide6, runs the full offscreen UI smoke matrix, and additionally launches `python main.py --smoke-test` before building.

The Microsoft Word COM backend is implemented and guarded by Windows/Word availability checks. It cannot be executed in this Linux validation environment; the Windows application will prefer it automatically when Word and pywin32 are available.


## Quality gate

See `QUALITY_GATE.md` for Ruff, Pyright, coverage, GUI smoke and Windows CI enforcement.

## Quality/stability pass — 2026-08-19

The replacement produced by the quality pass was revalidated locally with:

- `python -m compileall -q app tests tools main.py`
- `python tools/check_dead_code.py` — all production modules reachable from `main.py`
- `pytest -q` — **167 passed, 3 skipped** in the Linux review environment
- core coverage — **75.89%**, above the enforced 75% floor
- source-level constructor/name-resolution contracts — passed

The skipped modules are GUI-specific and are expected when PySide6 is unavailable. Ruff, Pyright, the complete PySide6 smoke matrix, and the real `main.py --smoke-test` are enforced by the Windows quality workflow, where the development requirements are installed before the gate runs.
