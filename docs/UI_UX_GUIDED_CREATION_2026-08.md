# Padroniza — Guided Template Creation UX (2026-08)

## Goal

The normal template-authoring path should assume that the user understands the document they want to automate, but does **not** understand DOCX runs, OOXML, scanner stages, field IDs, profile keys, visibility expressions, or confidence internals.

The product rule is:

> Simple outside, specialized inside.

Scanner V6 and the deterministic document engine remain unchanged in authority. The UX only decides how much of that machinery a normal template author has to see.

## New-template workflow

`TemplateEditorDialog` uses a guided mode when `template_id is None`:

```text
Documento → Campos → Organizar → Concluir
```

### 1. Documento

The user selects or drops a DOCX, DOCM, or PDF and provides a friendly model name/category/description.

Selecting the file performs only safe source preparation. It does **not** implicitly start the full scanner. The single primary action is **Analisar documento**.

This avoids the previous behavior where file selection could trigger hidden analysis and then unexpectedly open review UI.

### 2. Campos

After the scanner finishes and the review-first candidate dialog is completed, the normal field table exposes only what most users need:

- field label;
- field type;
- required state;
- options/field configuration;
- validation status.

Hidden by default:

- technical field ID;
- section/profile key/group metadata;
- exclusive-choice implementation flags;
- `visible_when` expressions;
- layout internals;
- tag guide;
- direct row add/remove/reorder/group tools;
- undo/history controls.

Those remain available under **Opções avançadas**.

Direct row mutation is intentionally not presented as a friendly normal-user operation. A configured field that is not anchored/tagged in the source document is not useful. A future manual-authoring UX should select/highlight a real source location and create the field + source anchor together.

### 3. Organizar

The section-card view becomes the whole step instead of another technical tab. The user can rename/reorder sections and inspect field organization without deciding which editor tab to use.

### 4. Concluir

The user sees the generated-form preview plus final model metadata/readiness.

Output filename patterns, folder patterns, sequential numbering, diagnostics, and other technical options remain hidden unless **Opções avançadas** is enabled.

## Candidate review language

`AutomaticDetectionDialog` continues to preserve all Scanner V6 evidence, but defaults to human-facing states:

```text
✓ Identificado
⚠ Confira
? Possível campo
```

The exact source context remains visible because that is the most important review information.

Technical origin, internal field ID, structural report, and technical-confidence filter are hidden behind **Detalhes técnicos**.

The user-facing decision is intentionally narrow:

```text
Does this source region change?
Is the proposed label/type correct?
```

The user does not need to understand why a Word paragraph is split into runs or which detector generated the candidate.

## Architecture boundaries

- `app/ui/widgets/creation_stepper.py` owns only presentation of workflow progress.
- `TemplateEditorDialog` coordinates step visibility and user actions.
- `app/services/template_scanning.py` remains the field-localization orchestration boundary.
- Scanner structure/semantic logic stays under `app/document/`.
- Document modifications remain deterministic and transactional.

The guided flow must never become a reason to move scanner/document logic into Qt classes.

## Next UX milestone

The next high-value authoring capability is **document-side visual selection/highlighting** for manual correction:

```text
scanner misses a span
        ↓
author selects exact source text
        ↓
Make dynamic
        ↓
Padroniza creates field + robust source anchor together
```

Do not implement a simple “add field” button in the normal workflow until the source placement/anchoring part is solved as part of the same interaction.
