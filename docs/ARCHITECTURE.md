# Padroniza architecture

## Goal

The codebase is organized so that UI code coordinates user interaction, while document processing and application rules remain independently testable.

## Dependency direction

```text
UI
 ↓
Services
 ↓
Document / Repositories
 ↓
Domain / Core
```

Practical rules:

1. `app/domain` owns the canonical field vocabulary and must not depend on Qt or filesystem workflows.
2. `app/document` owns document parsing, generation, conversion, automatic detection, and document understanding.
3. `app/repositories` owns persistence and compatibility of stored data.
4. `app/services` orchestrates multi-step workflows and is the preferred entry point for UI actions.
5. `app/ui` owns dialogs, widgets, navigation, save/open prompts, notifications, and presentation state.
6. Scanner and generator share `app/document/docx/tags.py`; tag syntax must not be reimplemented independently.

## Canonical field flow

```text
DOCX/PDF/native controls
        ↓
scanner or assisted detector
        ↓
FieldDefinition + canonical FieldType
        ↓
FieldHandler registry
        ↓
template repository
        ↓
form / validation / profiles / drafts
        ↓
GenerationService
        ↓
DOCX generator
        ↓
optional DocumentConverter
```

`FieldDefinition` remains dict-compatible so existing template JSON is preserved while new code gets a normalized model and typed properties.

`app/domain/field_handlers.py` is the central behavior registry for field types. It owns common widget hints, formatting, samples, and type-specific validation for text, date, checkbox, dropdown, Brazilian document numbers, numeric types, e-mail, and repeatable tables. New field types should be registered there rather than adding parallel `if/elif` chains to scanner, form, and validation code.

## Automatic detection

Automatic field detection is split by stage instead of living in one giant module:

```text
detection/
├── candidates.py        candidate discovery
├── checkboxes.py        checkbox-specific detection
├── text_fields.py       text-field detection
├── tables.py            table/repeatable-row detection
├── identifiers.py       field ID construction
├── context_helpers.py   nearby/contextual information
├── records.py           detection records
├── application.py       applying accepted detections
└── detector.py          orchestration/public workflow
```

This makes a detection failure attributable to a specific stage rather than one monolithic function.

## Generation and publication

`app/services/generation.py` owns the generation workflow. The UI chooses paths and asks questions; the service performs template preflight, fills the document, validates the produced package, and only then publishes the output.

Final files are transactional at the filesystem level:

```text
generate in destination-side staging path
        ↓
validate DOCX/PDF
        ↓
atomic os.replace into final destination
        ↓
commit sequence and history
```

A failed generation or conversion therefore does not replace an existing final file or consume a sequence number before a valid artifact exists.

`app/services/output_planner.py` owns filename/folder patterns and sequence planning.

## Conversion

The UI and generation service use `DocumentConverter` rather than calling the integrated PDF converter directly.

DOCX → PDF backends are selected by fidelity priority:

```text
Microsoft Word COM (Windows + Word)
        ↓ fallback
LibreOffice headless
        ↓ fallback
Integrated ReportLab converter
```

The successful backend is reported to the UI. Backend failures fall through to the next available option. The integrated converter remains an offline fallback, but complex Word layout may be simplified.

PDF → DOCX continues to use the integrated PyMuPDF/python-docx pipeline.

The interactive converter runs in a worker thread, publishes through a staging file, and supports cooperative cancellation. LibreOffice subprocess conversion can be terminated while running; the integrated pipeline checks cancellation between document units. Word automation checks cancellation at safe COM boundaries.

## Template diagnostics and preflight

`app/document/diagnostics.py` provides structured diagnostics with severity, stable issue codes, field IDs, source locations, and safe-fix metadata where applicable. It checks markers, IDs, field/config mismatches, conditions/cycles, dropdowns, repeatable tables, and output tokens.

Preflight is enforced when templates are created, updated, imported, and again immediately before generation. Blocking structural errors cannot silently enter the generation pipeline. The template editor displays issues in a structured navigator; double-clicking a field issue returns to that field in the editor.

Document scanning and diagnostic source analysis are cached by resolved path + modification timestamp + size. Returned field objects are copied so callers cannot mutate cached state.

## Persistence and schema versions

Runtime JSON files are stored as explicit envelopes:

```json
{
  "schema_version": 1,
  "kind": "profiles",
  "data": []
}
```

Legacy raw JSON is accepted and migrated on read. Data written by a newer unsupported schema is rejected rather than reset or silently overwritten. Template JSON, QSettings, and backup metadata also carry explicit schema versions. Future migrations should be added as ordered `vN -> vN+1` steps in `app/core/schema.py`.

## Error reporting and logs

`app/core/application_logging.py` writes bounded rotating logs under `data/logs/`. User-facing failure dialogs show a short error ID and expose copyable technical details. Logging context should contain operational metadata only; form values and document contents must not be passed to the logger.

## Backup restore

Backup restore validates archive sizes, member paths, backup schema, and settings before touching live data. Restored folders are staged first and swapped into place with rollback if a filesystem replacement fails.

## CI and integration testing

The Windows GitHub workflow runs the automated test suite before packaging and then starts the real PySide6 window in offscreen `--smoke-test` mode. This validates resource paths, theme loading, storage initialization, and window construction in addition to unit-level behavior.
