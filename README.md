# Padroniza

Padroniza is a desktop application for turning DOCX/DOCM/PDF templates into structured forms, collecting user values, and generating completed documents.

## Project layout

The source tree is organized by responsibility:

- `app/domain/` — field models, field types, handlers, metadata, conditions, formatting, and validation. No UI concerns.
- `app/document/` — DOCX/DOCM/PDF ingestion, DOCX scanning, generation, conversion, automatic detection, and document understanding.
- `app/repositories/` — persistence and template/data repositories.
- `app/services/` — application workflows such as generation, backups, output planning, and template operations.
- `app/ui/` — PySide6 windows, dialogs, widgets, styles, and UI action mixins.
- `templates/` — bundled document templates.
- `assets/`, `docs/`, `examples/` — runtime resources and examples.
- `tests/` — automated regression tests.

See `docs/ARCHITECTURE.md` for dependency rules and the document pipeline; `docs/UI_UX_GUIDED_CREATION_2026-08.md` for the guided Novo/Editar authoring and review UX; `docs/SCANNER_V6_SEMANTIC_2026-08.md` for the current local semantic/dynamic-region architecture; `docs/SCANNER_V5_2026-08.md` and `docs/SCANNER_V4_2026-08.md` for the review-first and structure-first foundations; `docs/STRUCTURAL_TABLE_INTELLIGENCE_2026-08.md` for Word-table preservation; and `docs/DOCM_AND_RELEASE_2026-08.md` for macro-safe DOCM ingestion and automatic GitHub Releases.

For continuity across development sessions or a new ChatGPT conversation, read **`PROJECT_CONTEXT.md`** first. It records the current architecture, quality baseline, important regressions, known limitations, and handoff instructions.


## Template authoring and assisted detection

- **Novo Modelo and Editar share one guided authoring flow:** `Documento → Campos → Organizar → Concluir`. New sources are analyzed with one `Analisar documento` action; an existing model opens with its saved field map already loaded and only rescans if the source is replaced or the user requests `Analisar novamente`. Technical IDs, profile/visibility/layout rules, diagnostics, tag tools, output patterns, and numbering stay hidden unless `Opções avançadas` is enabled.
- **Optional official letterhead:** each model can enable the bundled `assets/Timbrado.docx`. DOCX generation applies the repeating official header/footer to every page, and PDF generation uses the same timbrado document. The integrated PDF fallback also renders the floating logo/red artwork and footer decoration. Leave it disabled for documents that already contain their own official stationery.
- **Government-form regressions:** PBDOC process identifiers such as `SDH-PRC-2026/04715` are detected as editable process-number spans, and exclusive checkbox choices split across separate Word table rows remain one mutually exclusive choice that renders the selected mark in generated DOCX/PDF.
- Scanner V6 keeps Scanner V5/V4 structural authority and adds a local semantic layer for inline values, dynamic paragraphs, repeatable lists, and learned template-family mappings. Fresh semantic discoveries are review-only; accepted tags must still pass a strict detect → apply → re-scan round trip before publication.
- The guided authoring flow exposes one analysis action while `app/services/template_scanning.py` orchestrates deterministic tags/native controls plus untagged/semantic candidates; the detector stages remain separate and independently testable.
- Candidate review defaults to `Identificado` / `Confira` / `Possível campo`; source context stays visible while internal origin/IDs/confidence details are opt-in.
- Assisted detection preserves multidimensional confidence plus `ready` / `recommended` / `required` evidence internally, while the normal review UI translates that into `Identificado` / `Confira` / `Possível campo`.
- The detection review dialog defaults to search, review-state, and type filters; technical confidence/origin/IDs are available on demand.
- Template fields receive live `OK` / `Erro` / `Revisar` status with type/status filtering.
- The preview tab can fill deterministic sample values and generate an atomically-published test DOCX after preflight.
- Expensive DOCX assisted detection is cached and runs off the UI thread with cooperative cancellation.
- Word tables are structurally classified before cell-level detection, so repeatable grids remain tables instead of becoming unrelated field cards.
- Merged multi-level headers are expanded into distinct columns, and short legends such as `SIM / NÃO` become dropdown columns.
- Field localization repairs structurally unambiguous duplicate/wrong-prefix markers in repeatable-table editor work copies before scanning, so older partial tagging runs do not permanently break the template editor.

## Reliability highlights

- DOCX/DOCM → PDF automatically prefers Microsoft Word, then LibreOffice, then the integrated fallback. DOCM input is first normalized to a macro-free DOCX working copy, so VBA is never executed by Padroniza.
- Semantic assistance is local-only: no cloud API or document upload is required. It contributes meaning/type/label evidence but never directly edits OOXML/PDF structures.
- `repeatable_list` is a first-class field type for editable bullet/numbered lists and remains separate from repeatable tables.
- Template preflight catches malformed tags/configuration before installation or generation.
- Generated/conversion outputs are staged before final publication so failures do not leave partial final files.
- Runtime JSON/templates/settings/backups use explicit schema versions and reject newer incompatible data safely. Template source/config updates, generation metadata commits, and backup data/settings restoration are rollback-capable.
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

For a local one-file build, use `build_windows.bat`. `build_github.ps1` is the CI packaging script and expects `APP_VERSION` to be supplied by the release workflow.


## GitHub Windows releases

`.github/workflows/build-windows.yml` creates Windows releases without requiring a typed version number. Run **Gerar release do Padroniza para Windows** from the Actions tab and choose `patch`, `minor`, or `major`. The workflow reads the highest existing `vMAJOR.MINOR.PATCH` tag and calculates the next semantic version; if there are no semantic release tags yet, the first release is `v1.0.0`.

The release job installs runtime/build dependencies once, performs a fast compile/dead-module preflight, runs PyInstaller once, uses that same executable for the portable asset and Inno Setup installer, writes SHA-256 checksums, and publishes all assets directly to the repository's **Releases** page. Tag pushes such as `v1.6.0` are also supported. The separate quality workflow ignores release tags so a tag does not duplicate the full quality job while packaging.

Typical release assets are:

```text
Padroniza-Setup-v1.6.0.exe
Padroniza-v1.6.0.exe
SHA256SUMS.txt
```

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


## Interface de modelos

A página **Modelos** é a central única da biblioteca: pesquisa, favoritos, duplicação, importação/exportação, diagnóstico, histórico de versões, arquivamento e exclusão ficam na própria janela principal. **Novo modelo** e **Editar** abrem somente o editor dedicado; **Usar no Gerar** seleciona o modelo e leva ao formulário.
