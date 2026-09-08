# Structural Table Intelligence — 2026-08

## Problem addressed

Institutional Word forms frequently use real Word tables as data structures. Earlier assisted-detection logic could inspect cells before understanding the surrounding table, which allowed a table such as:

```text
Item | Descrição | UND | Quantidade 2023/2024/2025 | Solicitada | PCA? | Justificativa
01   |           |     |                            |            | SIM  |
...  |           |     |                            |            |      |
```

to be flattened into unrelated form cards (for example a standalone `SIM` field).

## Current rule

Padroniza now analyzes the physical Word grid before ordinary cell-level heuristics are allowed to claim the region.

`app/document/detection/table_structure.py` classifies top-level Word tables as:

- `layout` — a table used mainly to position ordinary form content;
- `repeatable` — a list/grid where users can add repeated records;
- `fixed_form` — a real matrix with predetermined rows;
- `editable_sheet` — a spreadsheet-style header that needs a generated model row;
- `reference` — a history/reference table that should not be treated as an input list;
- `unknown` — a real grid whose semantics are not strong enough for automatic structural conversion.

## Repeatable-table evidence

The structural classifier uses physical evidence rather than only keywords:

- number of Word grid columns;
- horizontally merged title/header cells;
- a section/title row above the grid;
- a header row with several short labels;
- an item/number first column;
- numbered model rows;
- an ellipsis/continuation row;
- blank fillable cells;
- grouped headers spanning several physical columns.

One numbered model row plus an ellipsis row is considered strong repeatable-table evidence. This is common in government templates and avoids the previous requirement for two or more numbered source rows.

## Multi-level headers

A merged header such as:

```text
Quantidade
2023      2024      2025
```

is expanded into distinct columns:

- `Quantidade — 2023`
- `Quantidade — 2024`
- `Quantidade — 2025`

The shared `group_label` is preserved so the UI can render the relationship more clearly.

A short choice legend under a header, for example:

```text
Consta no PCA para 2026?
SIM / NÃO
```

becomes one repeatable-table dropdown column with `SIM` and `NÃO` options rather than an independent `SIM` field.

## Region ownership / anti-flattening

Once a physical table is classified as repeatable, its title/header/model/continuation rows become an owned region. Lower-level field detectors cannot reinterpret paragraphs wholly inside that region as independent top-level fields.

This is a deliberate safety rule: preserving a coherent table is preferred over silently producing a broken filling form.

## Application and generation

Accepted repeatable-table candidates are materialized into the Word template as one model row containing:

```text
{{repeat:table.id}} {{row.number}}
{{table.id.column}}
{{date:table.id.date_column}}
{{dropdown:table.id.choice|A|B}}
...
```

Extra model/ellipsis rows are removed. The existing DOCX generator then duplicates the tagged model row for the user-entered rows while preserving Word borders, widths, shading, and merged headers.

## Regression fixture

`tests/fixtures/dfd_licitacao_tradicional_sia13tdr.docx` is the real document that exposed this failure. Regression tests assert that:

- section 3 is classified as one 9-column repeatable table;
- the 2023/2024/2025 merged header is expanded correctly;
- PCA becomes a `SIM` / `NÃO` dropdown;
- `Justificativa se for o caso` is optional;
- no standalone `SIM` candidate survives;
- the original table remains a Word table after tagging;
- a synthetic equivalent can be generated end-to-end with multiple user rows;
- the fiscalização matrix is not misclassified as an editable spreadsheet;
- the revision-history table is recognized as reference structure.

When a new real-world table failure is found, add that document (when appropriate) or a minimized structural fixture before widening heuristics.

## Recovery of malformed editor work copies

A template-editor work copy can survive from an older or partial assisted-detection run. One concrete failure used the same child marker in several physical columns:

```text
{{itens.quantidade}}
{{itens.quantidade}}
{{itens.quantidade}}
```

under the grouped Word headers 2023 / 2024 / 2025. The normal scanner is intentionally strict and rejects duplicate child IDs, because generation could otherwise place the same value in several columns.

`app/document/docx/repair.py` now performs a conservative migration before the template editor's Smart Scan:

- it only touches rows that already contain exactly one `{{repeat:...}}` marker;
- unique, correctly-prefixed child IDs are left unchanged;
- duplicate child IDs are disambiguated from the physical Word header grid;
- child markers using the wrong repeat-table prefix are moved under the table and receive the structural header ID;
- repeat and row-number markers are never rewritten;
- the DOCX is saved only if a repair was actually necessary.

For the SIA33TDR failure this turns the three ambiguous quantity markers into:

```text
{{itens.quantidade_2023}}
{{itens.quantidade_2024}}
{{itens.quantidade_2025}}
```

and repairs the malformed requested-quantity marker to `{{itens.quantidade_solicitada}}`.

The repair runs against the editor's working DOCX, not the user's original source file. The DOCX scan cache is cleared after a repair so the next scan sees the migrated markers immediately. A regression test recreates the malformed work copy, proves that the strict scanner rejects it before migration, repairs it, re-runs Smart Scan successfully, and verifies that a second repair pass is idempotent.
