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

## Scanner V5.3 / DOCM / release validation — 2026-08-26

The current clean source tree was revalidated with:

- `pytest -q` — **224 passed, 3 skipped** in one Linux process
- core coverage — **79.42%**, above the 75% floor
- `python -m compileall -q app tests tools main.py` — pass
- `python tools/check_dead_code.py` — all production modules reachable
- release/quality workflow YAML — parsed successfully
- synthetic macro-enabled DOCM package regression — VBA parts/relationships are removed, the resulting DOCX opens with `python-docx`, template scanning finds its field, and DOCM → PDF hands only the macro-free DOCX copy to the selected conversion backend
- semantic release version tests — numeric latest-tag selection and patch/minor/major increments pass

A real Windows PyInstaller/Inno Setup/GitHub Release run was not executable in this Linux environment; `.github/workflows/build-windows.yml` is the authoritative Windows packaging path.

## Scanner V6 semantic validation — 2026-08-27

After the semantic/dynamic-region integration and hardening pass:

- `pytest -q` — **234 passed, 3 skipped** in one Linux process;
- core coverage — **79.99%**, above the enforced 75% floor;
- `python tools/check_semantic_benchmark.py` — **13/13 required**, **0 unexpected**, **0 fresh semantic candidates preselected**;
- `python tools/check_dead_code.py` — all production modules reachable;
- `python -m compileall -q app tests tools` — pass;
- semantic apply → normal DOCX re-scan contract — pass, including repeatable-list type/style/punctuation preservation;
- accepted learned mappings relocate changed inline, paragraph, list and signature values in the same template family;
- rejected semantic regions are not suggested again at the same learned location;
- schema-1 template configuration normalizes to schema 2 and V6 semantic/source-anchor metadata survives strict repository normalization;
- invalid repeatable-list metadata and invalid/stale semantic anchor metadata are blocking diagnostics/preflight errors;
- repeatable-list generation produces the expected bullet/punctuation output.

Ruff, Pyright and the real PySide6/Windows startup/build gates were not available in this Linux environment and remain authoritative in the Windows quality workflow.
