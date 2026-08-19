# Full improvement pass — 2026-08

This pass builds on the structural cleanup and focuses on reliability, fidelity, diagnostics, compatibility, and user-facing recovery.

## Implemented

- Fidelity-first DOCX → PDF backend chain: Microsoft Word COM, LibreOffice, integrated ReportLab fallback.
- Backend visibility in settings, generation feedback, live preview, and the file converter.
- Cooperative conversion cancellation and staging/atomic publication in the converter UI.
- Transactional generation with output validation before final publication.
- Central `FieldHandler` registry for formatting, hints, samples, widget behavior, and validation.
- Structured template diagnostics with issue codes, severity, field IDs, locations, condition-cycle checks, dropdown/table checks, malformed tag checks, and output-token checks.
- Template preflight on create/update/import and before every generation.
- Structured diagnostics UI with double-click navigation to affected fields in the template editor.
- Explicit schema versions for local data, templates, QSettings, and backups, with safe legacy migration and future-version rejection.
- Rotating structured application logs with short error IDs and copyable technical details.
- Error-report integration in generation, backup, template editing/management, profile/history actions, and unexpected file-conversion failures.
- Cached DOCX scans and diagnostics, invalidated by file path/mtime/size.
- End-to-end regression tests against all bundled templates.
- Real GUI startup smoke mode and Windows CI smoke launch after tests.
- Backup restore now rejects future backup schemas in addition to path/size/settings validation and transactional rollback.

## Conversion fidelity note

The integrated converter is intentionally a fallback. It cannot perfectly reproduce every Word layout feature. On Windows systems with Microsoft Word installed, Word COM is selected first; LibreOffice is second. This keeps the application functional offline while preferring higher-fidelity rendering when available.

## Compatibility policy

Existing pre-versioned local JSON and templates remain readable. The application migrates legacy local JSON into the new versioned envelope when it can do so safely. Files created by a newer unsupported schema are not rewritten.
