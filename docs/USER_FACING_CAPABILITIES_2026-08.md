# User-facing capability pass — August 2026

This pass builds on the architecture/reliability baseline and focuses on the parts of Padroniza that template authors interact with directly. It intentionally avoids another broad folder reorganization.

## Assisted field detection v3

Automatic detection now exposes an explicit review model instead of presenting confidence as a number alone.

Each suggestion can carry:

- normalized confidence and `high` / `medium` / `low` band;
- `ready`, `recommended`, or `required` review priority;
- a concise review summary;
- positive/negative evidence explaining the score;
- semantic/context label suggestion when available;
- detector version and source/location metadata.

A strong disagreement between the detector label and strong local semantic context is now represented as negative review evidence rather than silently replacing a usable label.

Accepted suggestions are recorded as reviewed so the template editor does not keep warning about a confidence level the user has already deliberately approved.

### Review dialog

The assisted-detection dialog now supports:

- text search across ID, label, origin, and preview;
- confidence filtering;
- review-priority filtering;
- field-type filtering;
- select-visible and select-recommended actions;
- a detail panel explaining confidence, review reason, origin, semantic suggestion, physical location, and evidence.

## Responsive detection

DOCX assisted detection now has a file/signature cache and returns independent copies of cached results. The cache invalidates when the source changes.

The template editor runs the expensive detection phase in a worker `QThread` with cooperative cancellation. The editor cannot be destroyed while the worker is still running, avoiding the common Qt `QThread destroyed while running` failure mode.

## Live template quality feedback

The field editor has a fast source-independent validation layer that runs while editing. Each field row shows `OK`, `Erro`, or `Revisar`, and fields can be filtered by status and type in addition to text search.

The live checks include:

- missing, invalid, and duplicate field IDs;
- missing labels;
- dropdowns with fewer than two choices;
- duplicate dropdown values;
- repeatable tables without columns;
- duplicate repeatable-column IDs;
- invalid/missing/unknown visibility dependencies;
- circular visibility dependencies;
- unreviewed automatic fields with medium/low confidence.

Completely blank newly-added rows are deliberately kept in the live validation projection so row numbers do not shift and unfinished rows cannot silently appear valid.

Malformed visibility rules are preserved in editor snapshots/undo state and are rejected on validated save rather than being silently discarded.

## Template preview and safe test generation

The preview tab now has actions to:

- fill the form with deterministic sample data;
- clear the preview;
- generate a test DOCX.

Sample generation respects exclusive checkbox groups and supports repeatable tables and common field types.

Before generating a test DOCX, Padroniza runs full template preflight. Test output is generated into staged storage and atomically published only after generation succeeds. The source DOCX cannot be chosen as the test output path.

## Dropdown consistency

A dropdown now consistently requires at least two configured options across:

- the field configuration editor;
- live field validation;
- template readiness;
- full diagnostics/preflight;
- validated template collection.

Diagnostics preserve the raw configured option/column list long enough to report duplicates even though runtime normalization intentionally deduplicates them.

## Regression coverage added

The pass adds tests around:

- live row-specific template-quality issues;
- confidence/review metadata and reviewed-state persistence;
- exclusive-group sample generation;
- detector v3 review priority;
- detection cache isolation/invalidation;
- cooperative detector cancellation;
- one-option dropdown preflight failure;
- duplicate dropdown/table configuration diagnostics;
- visibility cycles;
- strong label disagreement review evidence;
- UI source contracts for the new filters/validation/test-generation actions;
- PySide6 smoke coverage for the new detection filters/details and template-editor status filtering where Qt is available.

At the Linux package validation for this pass:

```text
pytest:         182 passed, 3 skipped
core coverage: 76.41%
dead modules:   none
compileall:     pass
```

The skipped modules are PySide6-dependent in that environment. Ruff/Pyright remain mandatory in the Windows quality gate; they were not available for local execution in the Linux review environment.
