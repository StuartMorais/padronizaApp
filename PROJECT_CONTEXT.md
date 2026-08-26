# Padroniza — Project Context / Chat Handoff

> **Purpose of this file:** this is the persistent technical handoff for Padroniza. When starting a new ChatGPT conversation, attach the latest project ZIP **and this file**, and ask the assistant to read this file before changing the code.
>
> **Maintenance rule:** update this file after every meaningful architecture change, feature addition, bug fix that affects project assumptions, quality-gate change, or known limitation. Do not use it as a line-by-line changelog; keep it focused on the current state and decisions that a new developer/chat needs to continue safely.

**Last updated:** 2026-08-26  
**Current baseline:** Scanner V5.3 review-first detection + unified field localization + safe DOCM ingestion + automatic GitHub Releases  
**Primary platform:** Windows / PySide6 desktop application  
**Entry point:** `main.py`

---

## 1. What Padroniza does

Padroniza is a desktop application that turns DOCX/DOCM/PDF documents into reusable templates and user-fillable forms.

Core workflow:

```text
DOCX / DOCM / PDF
    ↓
safe source preparation (DOCM -> macro-free DOCX working copy; PDF -> reconstructed DOCX)
    ↓
one field-localization workflow: authoritative tags/native controls + review-first untagged candidates
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
- DOCX/DOCM → PDF and PDF → DOCX conversion. DOCM is normalized to a macro-free DOCX working copy before any scanner/converter backend opens it.
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
├── document/        # DOCX/DOCM/PDF ingestion, DOCX scanning/generation, conversion, detection, understanding
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

### Word source preparation and conversion backends

DOCX is the canonical editable/generation format. DOCM is accepted as an input format, but `app/document/word_package.py` creates an inert DOCX working copy by removing VBA project/data/signature parts and changing the macro-enabled main content type. The original DOCM is never modified and Padroniza must not execute macros. PDF input is reconstructed to a DOCX working copy through the existing source-preparation path.

For DOCX/DOCM → PDF, prefer the best available backend after safe DOCM normalization:

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

### Scanner V5 review-first model

The current scanner baseline is **Scanner V5**. It preserves the proven Scanner V4 structure-first heuristics, but changes the contract: detection is allowed to find broadly while only candidates supported by strong structural/evidence rules are preselected for automatic application. Ambiguous candidates remain visible for human review instead of silently modifying the template.

```text
DOCX/DOCM/PDF source
↓
safe source preparation to canonical DOCX where required
↓
normalized structural extraction + document fingerprint
↓
section/table/content ownership
↓
independent detector passes
↓
candidate evidence + semantic/type inference
↓
selection policy (preselected vs review-only)
↓
user review / acceptance
↓
transactional tag application
↓
strict re-scan round-trip validation
```

Key Scanner V5 implementation pieces live under `app/document/detection/`, including `extraction.py`, `passes.py`, and `selection_policy.py`. `app/services/template_scanning.py` is the application-level orchestration boundary for the editor: one call locates authoritative tags/native controls and additional untagged review candidates while the detector layers remain independently testable. Candidate metadata preserves source/location/evidence and document fingerprint information so future per-template learning can be added without letting heuristics directly mutate documents.

Important structure-first rules retained from Scanner V4:

- every candidate retains a meaningful section/structural owner;
- numbered instruction-list items inside notes are not document sections;
- physical Word tables are classified before ordinary cell candidates;
- valid manual tags protect their local structure from reinterpretation;
- formatting is evidence, not an absolute field rule;
- binary long-choice blocks with a single standalone `OU` are valid choices (two alternatives are sufficient);
- mixed-color sentences may expose a narrowly bounded inline choice when one contiguous colored span contains explicit `OU` alternatives; only that colored span is replaced;
- terminal prompts after instructional blocks can become fields when context is strong;
- field type inference combines structure, vocabulary, placeholders, controls, neighbors and section context;
- candidates expose multidimensional confidence (`structure`, `fillable`, `label`, `type`) and evidence;
- automatically written tags are staged and must pass the strict normal DOCX scanner before publication;
- real scanner bugs should become permanent regression fixtures/contracts.

See `docs/SCANNER_V5_2026-08.md` for the current contract and `docs/SCANNER_V4_2026-08.md` for the underlying structure-first rules.

### Assisted-detection review model

Candidates can expose:

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

### Structural Table Intelligence

Word tables are analyzed structurally **before** ordinary cell-level heuristics. `app/document/detection/table_structure.py` classifies physical tables as layout, repeatable, fixed-form, editable-sheet, reference, or unknown. A high-confidence repeatable table owns its title/header/model/continuation rows so lower-level detectors cannot flatten those cells into unrelated top-level fields.

Important current behaviors:

- one numbered model row plus an ellipsis row can establish a repeatable list;
- horizontally merged/multi-level headers are expanded by physical Word-grid position (for example `Quantidade` → `Quantidade — 2023/2024/2025`);
- short header legends such as `SIM / NÃO` become dropdown columns;
- optional wording such as `se for o caso` makes that repeatable column optional;
- editable-sheet detection only considers the primary structural header, so a later row inside a fixed matrix cannot be mistaken for a new spreadsheet merely because a merged note follows it;
- repeatable child dropdowns are materialized as real dropdown tags in the Word model row.

The real regression fixture `tests/fixtures/dfd_licitacao_tradicional_sia13tdr.docx` must remain covered. In that document, section 3 must be one 9-column repeatable table and no standalone `SIM` field may survive. See `docs/STRUCTURAL_TABLE_INTELLIGENCE_2026-08.md`.

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
11. **A real Word data table could be flattened into unrelated filling fields** (for example section 3 of SIA33TDR showed header boxes plus a standalone `SIM` field). Structural table analysis now runs before cell heuristics, recognizes the merged 9-column repeatable grid, owns the region, expands grouped year headers, and converts `SIM / NÃO` into a table dropdown. The same fix prevents a later row in the fiscalização matrix from being misclassified as an editable sheet.
12. **Replacing an existing template source could fail preflight because the staged replacement lost its `.docx` suffix.** Replacement sources now retain a valid DOCX suffix and source/config publication is rollback-capable.
13. **A template update could publish the new DOCX but fail writing `template.json`, leaving mismatched live state.** Template source and configuration updates now roll back together on failure.
14. **Generation could publish a valid output and consume its sequence, then raise because recent/audit persistence failed.** Output publication plus sequence/recent/audit metadata now behave as one logical rollback-capable transaction.
15. **Backup restore could swap restored data successfully and then fail restoring settings.** Data folders and settings now participate in the same rollback operation and QSettings status is checked.
16. **Future-schema/corrupt templates could silently disappear during discovery.** Discovery now preserves/report compatibility failures instead of treating them as absent templates.
17. **Template package imports lacked resource limits.** ZIP imports now enforce path safety, member count, individual-member size, and total uncompressed-size limits.
18. **DOCM was invisible to the application and cannot be passed directly to python-docx safely.** Word input now accepts `.docm`, strips VBA into an inert canonical DOCX working copy, preserves the original macro-enabled file untouched, and uses the normal scanner/converter pipeline. The converter never hands an original DOCM to Word COM/LibreOffice, preventing an `AutoOpen` macro from being executed by Padroniza's conversion path.
19. **The GitHub release workflow repeated dependency installation, the full quality gate, and two PyInstaller builds, then only uploaded Actions artifacts.** Release packaging now installs dependencies once, runs a fast compile/dead-module preflight, runs one PyInstaller `--onefile` build, feeds that exact EXE to Inno Setup, calculates SHA-256 hashes, and publishes the installer/portable EXEs directly to GitHub Releases. Manual releases auto-increment SemVer from existing tags (`patch`/`minor`/`major`), while semantic tag pushes use their explicit version.

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

At the Scanner V5.3/DOCM/release baseline validation in the Linux review environment:

```text
pytest:         224 passed, 3 skipped (single process)
core coverage: 79.42%
dead modules:   none
compileall:     pass
workflow YAML: parsed successfully
```

Ruff, Pyright, PySide6 UI smoke tests, a real Windows executable build, and the real GUI startup remain authoritative Windows CI gates and should be rerun in the normal Windows/GitHub environment.

The skipped tests are PySide6-dependent in the Linux review environment. The Windows quality workflow installs PySide6 and executes the GUI gates.

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

### GitHub release workflow

The normal release path is **Actions → Gerar release do Padroniza para Windows → Run workflow**. Choose `patch`, `minor`, or `major`; do not type a version manually. `tools/resolve_release_version.py` reads existing semantic Git tags and computes the next version (first semantic release defaults to `v1.0.0`). The workflow uses `contents: write` and `gh release` to publish `Padroniza-Setup-vX.Y.Z.exe`, `Padroniza-vX.Y.Z.exe`, and `SHA256SUMS.txt` directly on the GitHub Releases page.

The full quality workflow intentionally ignores semantic release tags so a release does not rerun the expensive quality suite while packaging. Full Windows quality remains the pre-merge acceptance gate; the release workflow performs only fast compile/dead-module checks before building. `build_github.ps1` must not install dependencies or invoke PyInstaller more than once.

Do not carry `.venv/`, `__pycache__/`, `.pytest_cache/`, `build/`, or `dist/` between clean replacements. `.git/` is local Git metadata and should be preserved separately if the working folder must remain attached to the existing checkout.

---

## 12. Known limitations / areas to improve next

These are not necessarily bugs; they are the main future product-development areas:

### Conversion fidelity

The internal DOCX/DOCM → PDF converter cannot perfectly reproduce all Microsoft Word layout features. DOCM macros are intentionally removed before conversion; macro preservation is not a Padroniza feature. Prefer Word COM when available, then LibreOffice. Continue improving backend reporting/fallback behavior rather than attempting to make the UI depend on a specific converter.

### Automatic detection quality

Scanner V5 uses structure-first ownership, section/table analysis, content-role classification, multidimensional confidence, review evidence, caching, cooperative cancellation, invariants, and transactional tag round-trip validation. It is still heuristic: unusual legal/government layouts can produce false positives/negatives or imperfect type/label inference. Future work should improve detection quality using real failure documents and committed structure contracts rather than broad score tuning without fixtures.

### Generated filling-form layout

Generated fields now use a reusable `FieldContainer` shell so labels, help, assisted-detection actions, editors, hints, and validation messages stay structurally attached to the same field. Assisted fields show a subtle `Ajustar campo` action on its own left-aligned row rather than a distant `Corrigir` button at the far edge of a wide grid cell. `SearchableDropdown` explicitly expands to the width offered by the field container. The Windows Qt smoke suite includes geometry checks for this contract.

For genuine Word data tables, do **not** solve layout problems by arranging independent field cards. Preserve table identity through detection → tagged model → canonical repeatable-table field → `RepeatableTableWidget` → DOCX generation. Multi-column forms that are only using a Word table for positioning may still use the normal `layout=table/form_grid` metadata path.

Template-editor work copies also have a conservative repeatable-marker migration in `app/document/docx/repair.py`. Before field localization / Smart Scan, duplicate child IDs inside an existing `{{repeat:...}}` row are disambiguated from the physical Word headers (for example `quantidade_2023`, `quantidade_2024`, `quantidade_2025`), and child markers using the wrong table prefix are repaired. This exists specifically so an older/partial assisted-detection run cannot leave the editor permanently unable to reopen or rescan its own work copy. The original user source is not modified by this migration.

### Template authoring UX

The editor now has live field status, search/type/status filtering, sample preview, test-DOCX generation, diagnostics navigation, and existing undo/redo. The previous `Ferramentas do arquivo` menu with separate `Localizar campos` / `Detectar campos sem tags` commands was intentionally simplified: the normal path is one primary **Localizar campos** button backed by `TemplateScanResult` / `locate_template_fields()`. That operation synchronizes deterministic tags/native controls first, then presents any additional untagged candidates in the review-first dialog. **Diagnóstico** remains a separate secondary button because it answers a different question ("is this model structurally valid?") rather than locating fields. This is a UI simplification only; the scanner remains separated into specialized internal phases.

Useful next improvements include richer document-side visual highlighting of source locations, preview-before-install for PDF as well as DOCX, and more direct editing from diagnostic/review cards.

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
3. any DOCX/DOCM/PDF that reproduces the current problem, when relevant.

Suggested opening message:

> This is my Padroniza project. Read `PROJECT_CONTEXT.md` first and use it as the current architecture/quality baseline. Then inspect the attached project rather than assuming file paths or implementations. Preserve the quality gate and update `PROJECT_CONTEXT.md` when we make meaningful changes. Here is the issue/feature I want to work on: ...

For the assistant/developer continuing the project:

- Treat this document as context, **not as proof that the current code matches it**. Inspect the actual attached source before editing.
- If source and this handoff disagree, source/tests are authoritative; fix this handoff as part of the change.
- Do not claim tests or GUI paths were executed unless they actually were.
- For document-specific failures, reproduce against the user's actual DOCX/DOCM/PDF when possible.
- Preserve the clean replacement workflow and quality gates.

---

## 15. Current handoff summary

Padroniza now uses a **Scanner V5 review-first contract** on top of the proven Scanner V4 structure-first/table intelligence. DOCM is now a supported Word input alongside DOCX: it is converted into a macro-free canonical DOCX working copy before scanning or conversion, and VBA is never executed/preserved by Padroniza. The scanner separates discovery from automatic application: strong, structurally consistent candidates can be preselected, while ambiguous candidates remain review-only with evidence and source metadata. The reliability pass also makes template replacement/config updates, generated-output metadata persistence, and backup data/settings restoration rollback-capable; incompatible template discovery is surfaced; and template-package imports are resource-limited. The obsolete preview/batch modules were removed so the dead-code gate is green.

The normal template-editor scan UX now exposes one **Localizar campos** action even though the backend remains multi-stage. `app/services/template_scanning.py` coordinates authoritative tag/native-control discovery plus untagged candidate discovery and returns a single `TemplateScanResult`; the UI synchronizes deterministic fields immediately and reviews only the heuristic additions. Diagnostics remains separate.


GitHub Windows releases are now versioned and published automatically. Manual workflow runs choose only the SemVer bump (`patch`, `minor`, or `major`); the workflow resolves the next version from Git tags, runs a single PyInstaller build, uses that same EXE for Inno Setup, and uploads the installer, portable EXE, and checksums directly to GitHub Releases. Semantic tag pushes are also supported, and the full quality workflow ignores release tags to avoid duplicate 30+ minute work.

The next phase should focus on **measured detector quality**, not another language rewrite: add troublesome real documents as fixtures, calibrate the selection policy from observed false positives/negatives, add richer source-location highlighting, and then build per-template learned mappings/fingerprints on top of the V5 candidate metadata. Keep deterministic structure/location logic authoritative and use semantic/AI assistance only as evidence, never as a direct OOXML editor.

A real DFD regression on 2026-08-26 added two scanner contracts that were previously missing: (1) a 5.1-style block with exactly two alternatives separated by one `OU` is detected as a single-choice dropdown; and (2) a section-7-style sentence containing one red inline span such as `área técnica competente ou à equipe de planejamento da contratação` is detected as a two-option single choice while preserving the surrounding black sentence.

---

## 16. Explicit repeatable-table section recovery (2026-08-25)

A manually tagged repeatable Word table is authoritative and may bypass the automatic structural detector. The DOCX scanner therefore now recovers the semantic section directly from the nearest numbered full-width Word table row above `{{repeat:...}}`. Example: a tagged `{{repeat:itens}}` row under the merged heading `3. Quantidade a ser contratada:` receives `section = "3. Quantidade a ser contratada"` and `section_source = "word_table_title"` instead of falling back to `Dados do documento`.

Older templates that already persisted the generic fallback `Dados do documento` are automatically migrated to the stronger physical Word section during Smart Scan, unless the section has `section_source = "manual"`. The template editor marks a section as manual when the author explicitly changes its text, so future inference does not overwrite an intentional choice.

Native Word dropdown/date/checkbox controls without Developer-tab Tag/Title metadata must use the same contextual identifier during generation that the scanner used while building the form. `generate_docx()` now builds the Word control-context map before replacement and resolves unnamed native controls with that same mapping. Truly unresolvable recognized controls are left untouched instead of failing on a field that was never exposed to the user.

The government DFD fixture with a header/background drawing was used to validate generation. The generated DOCX retained all three media assets and both drawings in `header1.xml`; visual rendering confirmed that the Paraíba government background/header artwork remained present after field replacement.
