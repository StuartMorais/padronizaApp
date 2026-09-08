# ChecklistPython — Project Context

## Current baseline

ChecklistPython is a Windows/PySide6 desktop application for importing, reviewing, editing and exporting administrative verification checklists.

The scanner was upgraded on 2026-08-28 to use the same core safety philosophy as Padroniza Scanner V6, adapted to checklist documents rather than reusable Word-template fields.

## Scanner contract

The normal workflow is one action in the UI, but internally the scanner stays layered:

```text
source PDF/DOCX/DOCM
    ↓
source verification
    ↓
structural extraction
    ↓
checklist row/section detection
    ↓
needed-column ownership / metadata extraction
    ↓
evidence + confidence
    ↓
structural invariants / diagnostics
    ↓
review-first selection policy
    ↓
human review
    ↓
checklist persistence
```

### Important rules

- Physical document structure is authoritative when available.
- The official SINGRA PDF family is scanned from its table geometry, not from raw text order.
- Text-only parsing is a fallback and is deliberately lower-confidence.
- Scan results are reviewed before a new checklist is saved.
- Scanner diagnostics and the technical report remain available after import.
- Every imported item stores source page, source rectangle, confidence, evidence and detector origin.
- User checklist data remains local JSON under `%APPDATA%\checklist-app\data`.

## Official checklist PDF detector

The current benchmark is `tests/fixtures/checklist_administrativo_lei_14133.pdf`.

Expected result:

- 8 pages
- 5 sections
- 40 verification rows
- 8/8 repeated table headers recognized
- no duplicate item numbers
- nested `2.2.1` remains content of row `2.2` rather than becoming a false extra row
- item `4.9` is recovered despite a leading flattened blank marker
- process metadata `SDH-PRC-2026/01518`

The scanner maps the repeated physical columns:

```text
Documento / Informações
Normativos
S / N / NA
Folha
Observação
```

## Scanner UI

The Scanner page exposes one primary `Analisar documento` action and a secondary `Ferramentas do scanner` menu:

- Revisar itens encontrados
- Executar diagnóstico
- Relatório técnico

The main checklist sheet also exposes the scanner tools for imported scanner-backed checklists.

The review dialog follows Padroniza terminology:

- `Identificado`
- `Confira`
- `Possível item`

It shows source context and evidence, while technical origin/confidence details remain optional.

## Quality gate

Run:

```powershell
python -m compileall -q app main.py tools
python tools/scanner_benchmark.py
python -m pytest -q tests/test_scanner_v6.py tests/test_storage_scan_metadata.py tests/test_ui_regressions.py
```

The Windows release workflow executes these scanner checks before PyInstaller.

## 2026-08-28 UI/runtime correction

- `Código Plataforma` is no longer part of the application data model or UI. The official source PDF column remains only as a structural boundary for geometry.
- Scanner entry points are unified: top navigation and library entry both open `SCANNER_PAGE`; `Analisar documento` is the sole file-selection action.
- `QComboBox` is imported explicitly in `main_window.py`. The missing import previously caused `refresh_checklist_sheet()` to fail on the first expanded item, leaving sections half-rendered and apparently impossible to collapse.
- The six-column checklist sheet uses consistent header indexes: Item, Documento, Normativo, S/N/NA, Folha, Observação.

## 2026-08-28 V6.2 scroll + portable JSON correction

- Checklist-table rebuilds preserve the vertical and horizontal viewport. Expanding/collapsing a section or changing an S/N/NA value no longer sends the user back to the top of the sheet.
- Scroll restoration happens both immediately and on the next Qt event-loop turn because `QTableWidget` can change its viewport again during the pending layout pass.
- Portable JSON import/export is available from the top workspace bar and the checklist library.
- `Exportar checklist ativo` writes a versioned `checklist-app.checklist` envelope containing one normalized checklist.
- `Importar checklist JSON` accepts that portable envelope, a legacy raw checklist object, or a list of raw checklist objects.
- Imported checklist IDs that collide with local data are converted to copies rather than overwriting an existing checklist.
- The application's internal `%APPDATA%` library file remains private implementation storage; users do not need to replace it manually to share checklists.

## 2026-09-01 editable section names

- Checklist section names are user-editable after creation/import.
- Select a section and use `Renomear seção` to replace names such as `NOVA SEÇÃO` with any non-empty text.
- The section number remains unchanged; only the user-facing section name is edited.
- Custom capitalization is preserved in the model, sheet, portable JSON and PDF export.
- Section bars themselves are read-only because a single click is reserved for expand/recolher; this avoids the previous conflict between expand/collapse and inline double-click editing.
