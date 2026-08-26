# Padroniza

Padroniza is a desktop application for turning DOCX/PDF templates into structured forms, collecting user values, and generating completed documents.

## Project layout

The source tree is organized by responsibility:

- `app/domain/` — field models, field types, handlers, metadata, conditions, formatting, and validation. No UI concerns.
- `app/document/` — DOCX/PDF scanning, generation, conversion, automatic detection, and document understanding.
- `app/repositories/` — persistence and template/data repositories.
- `app/services/` — application workflows such as generation, backups, output planning, and template operations.
- `app/ui/` — PySide6 windows, dialogs, widgets, styles, and UI action mixins.
- `templates/` — bundled document templates.
- `assets/`, `docs/`, `examples/` — runtime resources and examples.
- `tests/` — automated regression tests.

See `docs/ARCHITECTURE.md` for the dependency rules and document pipeline, `docs/IMPROVEMENTS_2026-08.md` for the reliability pass, `docs/USER_FACING_CAPABILITIES_2026-08.md` for the template-authoring/detection UX milestone, `docs/STRUCTURAL_TABLE_INTELLIGENCE_2026-08.md` for Word-table preservation rules, and `docs/SCANNER_V4_2026-08.md` for the current structure-first scanner architecture.

For continuity across development sessions or a new ChatGPT conversation, read **`PROJECT_CONTEXT.md`** first. It records the current architecture, quality baseline, important regressions, known limitations, and handoff instructions.


## Template authoring and assisted detection

- Scanner V4 analyzes document structure and content roles before creating field candidates; accepted automatic tags must pass a strict detect → apply → re-scan round trip before publication.
- Assisted detection exposes multidimensional confidence plus `ready` / `recommended` / `required` review priority and evidence.
- The detection review dialog supports search plus confidence, review-priority, and type filters.
- Template fields receive live `OK` / `Erro` / `Revisar` status with type/status filtering.
- The preview tab can fill deterministic sample values and generate an atomically-published test DOCX after preflight.
- Expensive DOCX assisted detection is cached and runs off the UI thread with cooperative cancellation.
- Word tables are structurally classified before cell-level detection, so repeatable grids remain tables instead of becoming unrelated field cards.
- Merged multi-level headers are expanded into distinct columns, and short legends such as `SIM / NÃO` become dropdown columns.
- Smart Scan repairs structurally unambiguous duplicate/wrong-prefix markers in repeatable-table editor work copies before scanning, so older partial tagging runs do not permanently break the template editor.

## Reliability highlights

- DOCX → PDF automatically prefers Microsoft Word, then LibreOffice, then the integrated fallback.
- Template preflight catches malformed tags/configuration before installation or generation.
- Generated/conversion outputs are staged before final publication so failures do not leave partial final files.
- Runtime JSON/templates/settings/backups use explicit schema versions and reject newer incompatible data safely.
- Rotating logs under `data/logs/` provide short error IDs and copyable technical details.
- DOCX scanning/diagnostics are cached by file identity to keep repeated template analysis responsive.

## Clean development setup (Windows)

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe main.py
```

Build dependencies are separate:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
```

Then use `build_windows.bat` or `build_github.ps1` as appropriate.

## Runtime data

`data/`, `output/`, `backups/`, `.venv/`, caches, and `.storage-v1` are local/runtime state and are intentionally ignored by Git. The application recreates the storage files it needs.

## Quality gate

For development on Windows, install `requirements-dev.txt` and run:

```powershell
./tools/run_quality_gate.ps1
```

This runs compilation, dead-module detection, Ruff, Pyright, pytest with coverage, the PySide6 UI smoke matrix, and a real offscreen `main.py` startup. See `docs/QUALITY_GATE.md` for the policy and CI details.

### Generated form layout

Generated form fields share a reusable visual container. Labels, assisted-detection actions, input controls, hints and validation messages remain attached to the same field, and searchable dropdowns expand with their field column. This prevents correction actions and compact editors from appearing visually detached on wide windows.
