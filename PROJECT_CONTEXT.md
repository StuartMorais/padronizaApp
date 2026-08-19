# Padroniza — Project Context / Chat Handoff

> **Purpose of this file:** this is the persistent technical handoff for Padroniza. When starting a new ChatGPT conversation, attach the latest project ZIP **and this file**, and ask the assistant to read this file before changing the code.
>
> **Maintenance rule:** update this file after every meaningful architecture change, feature addition, bug fix that affects project assumptions, quality-gate change, or known limitation. Do not use it as a line-by-line changelog; keep it focused on the current state and decisions that a new developer/chat needs to continue safely.

**Last updated:** 2026-08-19  
**Current baseline:** User-facing capability full replacement (assisted detection v3 + template-authoring UX)  
**Primary platform:** Windows / PySide6 desktop application  
**Entry point:** `main.py`

---

## 1. What Padroniza does

Padroniza is a desktop application that turns DOCX/PDF documents into reusable templates and user-fillable forms.

Core workflow:

```text
DOCX / PDF
    ↓
scan explicit tags and/or automatically detect fillable fields
    ↓
normalize fields into the application field model
    ↓
review/edit template metadata
    ↓
render a PySide6 form
    ↓
collect/validate user input
    ↓
generate DOCX
    ↓
optionally generate/convert PDF
```

The application supports both documents that already contain Padroniza tags and documents without tags that need assisted field detection.

Important capabilities include:

- Tagged and untagged field scanning.
- DOCX generation with user-provided values.
- DOCX ↔ PDF conversion.
- Native Word/content-control handling where supported.
- Dates, text, checkboxes, dropdowns, single-choice fields, repeatable tables, and `default_or_text` fields.
- Template creation/editing/import/update and diagnostics.
- Profiles, drafts, favorites, recent documents, audit/history, numbering/sequences, backups, and template versions.
- Automatic/assisted field detection and document-understanding heuristics.

---

## 2. Current architecture

The source tree is organized by responsibility:

```text
app/
├── core/            # paths, settings, schema/atomic helpers, logging, constants
├── domain/          # field models/types/handlers, metadata, conditions, validation
├── document/        # DOCX/PDF scanning, generation, conversion, detection, understanding
├── repositories/    # persistence and local/template repositories
├── services/        # application workflows/orchestration
└── ui/              # PySide6 windows, pages, dialogs, widgets, styles, action mixins
```

Supporting folders:

```text
templates/           # bundled templates
assets/              # application icons/images
data/                # local runtime state; starts clean in replacement archives
backups/             # local backups; starts clean in replacement archives
output/              # generated output; starts clean in replacement archives
docs/                # architecture/quality/reference documentation
examples/            # example documents
installer/           # Windows installer files
tests/               # automated regression tests
tools/               # quality/development scripts
```

### Dependency direction

Prefer this direction:

```text
UI
 ↓
Services
 ↓
Document / Repositories
 ↓
Domain / Core
```

Do not move document-processing or persistence business logic back into `MainWindow` merely because it is convenient for a UI action.

---

## 3. Important architectural decisions

### Canonical field model

Fields should be represented through the canonical domain model (`FieldDefinition`, `FieldType`, and the field-handler registry) instead of subsystem-specific dictionaries whenever practical.

Desired flow:

```text
scanner/detector -> canonical field definitions
UI/validator/profile/draft/generator -> consume canonical field definitions
```

Field-specific formatting, validation, hints, samples, and behavior should be centralized through field handlers rather than duplicated `if field.type == ...` chains.

### Tag parsing

DOCX tag interpretation is centralized under the DOCX document layer. Scanner and generator should not independently invent different syntax rules.

Supported concepts include normal text fields and specialized tags such as date, checkbox, dropdown, single-choice, repeatable structures, and `default_or_text`.

### Generation orchestration

Generation is a service responsibility. The UI decides things such as save dialogs, overwrite confirmations, and notifications; services coordinate the actual workflow.

Generation should remain transactional:

```text
plan output / preview sequence
↓
generate to staged temporary output
↓
validate generated output
↓
perform conversion if requested
↓
validate conversion
↓
publish final output atomically
↓
commit numbering/history
```

A failed generation/conversion must not consume a sequence number or leave a partially written final file.

### Conversion backends

For DOCX → PDF, prefer the best available backend:

```text
Microsoft Word COM (Windows, highest fidelity when available)
    ↓ fallback
LibreOffice headless
    ↓ fallback
Integrated converter
```

The integrated converter is deliberately a fallback and is not expected to reproduce every Word layout feature perfectly.

### Runtime schemas

Runtime JSON, templates/settings/backups use explicit schema/version handling. Legacy data may be migrated when safe. Data from a newer unsupported schema must be rejected rather than silently reset or rewritten.

### Backups

Restore operations must remain defensive and transactional: validate archive paths/sizes/schema/settings first, stage restored data, replace live data only when ready, and roll back on I/O failure.

---

## 4. UI organization

`MainWindow` was reduced substantially from the original monolithic implementation. UI action areas are split into focused mixins/pages/dialogs.

The UI layer may coordinate user interactions, but should not become the home for:

- sequence mechanics;
- document-generation internals;
- conversion implementation details;
- repository persistence rules;
- schema migration logic;
- document-analysis algorithms.

When extracting methods into mixins, ensure instance methods accept `self`, and helper methods that intentionally do not use instance state are explicitly `@staticmethod` or `@classmethod`.

---

## 5. Automatic field detection

The former very large automatic detector was split into focused modules under `app/document/detection/` and related document-understanding modules.

Keep the detection pipeline conceptually separated into stages such as:

```text
candidate discovery
↓
field/type classification
↓
context/label interpretation
↓
ID construction
↓
confidence/evidence/review priority
↓
application of accepted detections
```

### Detector v3 review model

Assisted detection currently uses detector version 3. Candidates can expose:

- normalized confidence and `high` / `medium` / `low` band;
- review priority `ready`, `recommended`, or `required`;
- review reasons and a short review summary;
- positive/negative evidence supporting the score;
- semantic/context label suggestions;
- physical source/location metadata.

Strong semantic-label disagreement is review evidence rather than permission to silently overwrite a usable detector label. Accepted candidates are marked as user-reviewed and that metadata is preserved through the template editor.

The review dialog supports text search plus confidence, review-priority, and field-type filters, select-visible/select-recommended actions, and a details panel explaining the suggestion.

### Responsiveness

Assisted detection is cached by source signature and semantic context. Cache entries return independent copies and invalidate when the source changes. In the template editor, the expensive detection phase runs on a worker `QThread` and supports cooperative cancellation. Do not remove cancellation checks from detector phases or allow the editor to be destroyed while that worker is still active.

When improving detection, prefer identifying which stage is wrong rather than adding broad special cases to a single catch-all function.

---

## 6. Template diagnostics and preflight

Templates have structured diagnostics and preflight checks. Current checks include, where applicable:

- malformed/unmatched tags;
- duplicate or invalid field IDs;
- configured fields missing from the source and source fields missing from configuration;
- field-type inconsistencies;
- invalid/empty dropdown configuration and duplicate options;
- repeatable-table column problems;
- invalid/circular conditions;
- unknown output filename tokens;
- source locations for issues.

Preflight is intended to run during template creation/update/import/editor save and again before generation.

The template editor also has a fast source-independent live validation layer. Each field row can show `OK`, `Erro`, or `Revisar`, and authors can filter by status/type/search. Live checks include missing/invalid/duplicate IDs, missing labels, dropdown/table configuration, invalid/unknown/circular visibility rules, and unreviewed medium/low-confidence automatic fields. Blank unfinished rows remain visible to this validator so issue row indexes do not shift.

Dropdowns consistently require at least two configured choices. Duplicate dropdown values and duplicate repeatable-table column IDs must be diagnosed from the raw configured values before runtime normalization deduplicates them.

The preview tab can fill deterministic sample values, clear them, and generate a test DOCX. Test generation must run full preflight first and use staged/atomic output; never overwrite the source DOCX.

Do not weaken preflight simply to make an invalid template install; improve the diagnostic or migration path instead.

---

## 7. Reliability and diagnostics

### Logging

Structured rotating logs are stored under:

```text
data/logs/padroniza.log
```

User-visible failures should provide a short error ID and copyable technical details when appropriate. Avoid logging form/document contents or other unnecessary user data in technical context.

### Caching

DOCX scanning, diagnostics, and assisted detection can be cached by file identity/context. Cached results must invalidate when the source changes, and callers should not be able to mutate shared cached state accidentally.

### Paths/resources

The project root calculation is sensitive because `paths.py` was moved deeper during the architecture refactor. The correct source root is based on the actual repository root, not `app/`.

A previous regression made the app search paths such as `app/app/ui/styles/` and `app/templates/`, causing the UI theme to disappear and templates to show as zero. Keep the path regression tests.

---

## 8. Historical regressions that must stay covered

These bugs were found during the refactor and are important regression cases:

1. **Sequence consumed on failed generation** — fixed by preview/commit semantics and transactional generation.
2. **Backup restore could leave live data partially replaced** — fixed through staging and rollback.
3. **Malformed backup settings could clear current settings** — restore now validates safely.
4. **`default_or_text:` existed in a bundled template but was not actually supported** — tag support was added and template metadata corrected.
5. **Mixin helper missing `@staticmethod`** caused `_repolish_widget()` to receive `self` unexpectedly. Similar latent methods were fixed and signature tests added.
6. **Project root moved one directory deeper** and resource/template paths broke, making the styled UI disappear and template count become zero. Path tests were added.
7. **`JsonFileStore` gained required `kind=` but `FieldLibraryStore` still called the old constructor**, crashing `Novo Modelo`. The field library now passes a kind and `JsonFileStore` can safely infer one when appropriate. Regression tests were added.
8. **Two form-layout paths referenced an undefined `field_type` variable** after cleanup. This was fixed and static/undefined-name checks were strengthened.
9. **Diagnostics normalized dropdown/table configuration before checking duplicates**, which made duplicate-option/column warnings impossible to trigger. Diagnostics now inspect normalized raw values first, while runtime normalization still deduplicates safely.
10. **Malformed visibility rules could be dropped from editor snapshots**, hiding what the author typed. Invalid non-empty rules are now preserved for live validation/undo and rejected on validated save.

Any future cleanup should keep tests around these scenarios rather than assuming the problem cannot return.

---

## 9. Quality gate

The Windows quality gate is the acceptance criterion for future code changes.

After installing `requirements-dev.txt`, run:

```powershell
./tools/run_quality_gate.ps1
```

It currently performs:

1. Python bytecode compilation for `app`, `tests`, and `tools`.
2. Production-module reachability/dead-module check.
3. Ruff correctness checks.
4. Pyright checks over the typed/stable application boundaries.
5. Complete pytest suite with coverage.
6. Offscreen PySide6 UI smoke matrix.
7. Real isolated `main.py --smoke-test` startup.

Current coverage policy enforces a **75% minimum** over the non-UI core (`core`, `domain`, `document`, `repositories`, `services`). UI correctness relies more heavily on constructor/navigation/startup smoke coverage than line coverage.

At the current user-facing capability baseline validation:

```text
pytest:         182 passed, 3 skipped
core coverage: 76.41%
dead modules:   none
compileall:     pass
```

The skipped tests were PySide6-dependent in the Linux review environment. The Windows quality workflow is expected to install PySide6 and execute the GUI gates.

See `docs/QUALITY_GATE.md` for the exact policy.

---

## 10. Dead-code policy

`tools/check_dead_code.py` checks production-module reachability starting from `main.py`.

The previous quality pass removed obsolete/unreachable modules including:

- `batch_generation_dialog.py`
- `preview_dialog.py`
- `live_document_preview.py`

Do not keep dead modules “just in case” when functionality is truly obsolete. However, remember that Qt signals/callbacks can make method-level dead-code detection unreliable; the project currently focuses on whole-module reachability.

---

## 11. Development setup (Windows)

Recommended clean environment:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

Run the complete quality gate:

```powershell
.\tools\run_quality_gate.ps1
```

Run the application:

```powershell
.\.venv\Scripts\python.exe main.py
```

Build dependencies are separate in `requirements-build.txt`.

Do not carry `.venv/`, `__pycache__/`, `.pytest_cache/`, `build/`, or `dist/` between clean replacements. `.git/` is local Git metadata and should be preserved separately if the working folder must remain attached to the existing checkout.

---

## 12. Known limitations / areas to improve next

These are not necessarily bugs; they are the main future product-development areas:

### Conversion fidelity

The internal DOCX → PDF converter cannot perfectly reproduce all Microsoft Word layout features. Prefer Word COM when available, then LibreOffice. Continue improving backend reporting/fallback behavior rather than attempting to make the UI depend on a specific converter.

### Automatic detection quality

Detector v3 now has confidence bands, review priority/evidence, filtering/details UX, caching, and cooperative cancellation. It is still heuristic: unusual legal/government layouts can produce false positives/negatives or imperfect type/label inference. Future work should improve detection quality using real failure documents rather than broad score tuning without fixtures.

### Generated filling-form layout

Generated fields now use a reusable `FieldContainer` shell so labels, help, assisted-detection actions, editors, hints, and validation messages stay structurally attached to the same field. Assisted fields show a subtle `Ajustar campo` action on its own left-aligned row rather than a distant `Corrigir` button at the far edge of a wide grid cell. `SearchableDropdown` explicitly expands to the width offered by the field container. The Windows Qt smoke suite includes geometry checks for this contract.

### Template authoring UX

The editor now has live field status, search/type/status filtering, sample preview, test-DOCX generation, diagnostics navigation, and existing undo/redo. Useful next improvements include richer document-side visual highlighting of source locations, preview-before-install for PDF as well as DOCX, and more direct editing from diagnostic/review cards.

### Type coverage

Pyright currently focuses on stable typed layers. Its scope can be expanded gradually as dynamic Qt and inference-heavy code receives useful annotations. Avoid adding annotations solely to silence the checker if they reduce clarity.

### Coverage floor

75% is a floor, not a target. Increase it only through meaningful regression tests, especially around real document workflows and error paths.

---

## 13. Rules for future changes

When modifying Padroniza:

1. Preserve existing user-facing behavior unless the change is intentional and documented.
2. Prefer incremental changes over broad rewrites.
3. Keep domain/document/persistence logic out of UI classes.
4. Reuse the canonical field model and handler registry.
5. Keep generation/conversion transactional.
6. Do not silently reset incompatible runtime data.
7. Add a regression test for every concrete bug fixed.
8. Exercise the actual UI path when a bug is triggered only by opening/clicking a feature.
9. Run the quality gate before considering a change complete.
10. Update **this `PROJECT_CONTEXT.md` file** when the current project assumptions materially change.
11. When giving the user a replacement archive, provide the **entire clean project**, not just individual modified files, unless the user explicitly asks for a patch.
12. Replacement archives should not contain local environment/cache/build/runtime junk such as `.venv`, `.idea`, `__pycache__`, `.pytest_cache`, `build`, `dist`, or personal runtime data.

---

## 14. Instructions for a new ChatGPT chat

When starting a new conversation, the user can attach:

1. the latest full project ZIP;
2. `PROJECT_CONTEXT.md` from that same ZIP;
3. any DOCX/PDF that reproduces the current problem, when relevant.

Suggested opening message:

> This is my Padroniza project. Read `PROJECT_CONTEXT.md` first and use it as the current architecture/quality baseline. Then inspect the attached project rather than assuming file paths or implementations. Preserve the quality gate and update `PROJECT_CONTEXT.md` when we make meaningful changes. Here is the issue/feature I want to work on: ...

For the assistant/developer continuing the project:

- Treat this document as context, **not as proof that the current code matches it**. Inspect the actual attached source before editing.
- If source and this handoff disagree, source/tests are authoritative; fix this handoff as part of the change.
- Do not claim tests or GUI paths were executed unless they actually were.
- For document-specific failures, reproduce against the user's actual DOCX/PDF when possible.
- Preserve the clean replacement workflow and quality gates.

---

## 15. Current handoff summary

Padroniza has completed the major architecture cleanup, stability/quality gate, and the first user-facing capability milestone. The project is organized by responsibility; generation/conversion/backups/schema handling are hardened; assisted detection v3 exposes confidence evidence/review priority and runs responsively; and the template editor provides live validation/filtering plus safe sample/test generation. Future changes are expected to pass the Windows-oriented quality gate with static analysis, tests, coverage, UI smoke testing, and startup validation.

The next phase should continue to favor **measurable product quality**: improve detector accuracy using real troublesome documents, add richer source-location/document preview interactions, and improve PDF→DOCX fidelity/performance where practical. Avoid another broad architecture rewrite unless a concrete problem justifies it.
