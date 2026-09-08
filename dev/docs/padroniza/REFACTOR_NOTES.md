# Refactor and improvement notes

The project cleanup was performed incrementally so the existing document workflow could remain stable while responsibilities became explicit.

## Structural cleanup

- Generation and output planning moved out of `MainWindow` into services.
- `MainWindow` behavior was split into focused UI mixins.
- A canonical `FieldDefinition` and `FieldType` define the application's field vocabulary.
- Field IDs, metadata helpers, conditions, validation, and formatting were separated into focused domain modules; the old catch-all `field_utils.py` was removed.
- DOCX tag parsing is centralized in `document/docx/tags.py` and shared by scanner/generator.
- `default_or_text` is a supported tag instead of becoming an invalid literal field ID.
- Automatic field detection was split into candidate, checkbox, text, table, identifier, context, record, application, and orchestration modules.
- Document conversion sits behind `DocumentConverter`.
- Backup restore has archive limits, settings validation, staging, rollback, and schema compatibility checks.

## Reliability/product pass

- Added a central `FieldHandler` registry rather than growing field-type branching across the app.
- Added Word/LibreOffice/integrated conversion backend selection and fallback.
- Added staged/atomic generation and staged converter output.
- Added cooperative conversion cancellation.
- Added structured template preflight/diagnostics and editor navigation.
- Added explicit data/template/settings/backup schemas and migrations.
- Added rotating logs, error IDs, and copyable technical diagnostics.
- Added path/mtime/size caches for expensive DOCX scan/diagnostic work.
- Added bundled-template E2E coverage and real GUI startup smoke coverage in Windows CI.

See `ARCHITECTURE.md` for the rules new code should follow and `IMPROVEMENTS_2026-08.md` for the product-facing changes.
