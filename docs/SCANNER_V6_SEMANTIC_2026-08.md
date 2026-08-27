# Scanner V6 — Semantic Document Understanding

**Baseline:** 2026-08-27

Scanner V6 extends the Scanner V5 review-first/structure-first pipeline with a **local semantic-assistance layer** and new dynamic-region concepts. It does not replace structural detection and it does not allow AI/semantic code to edit DOCX/PDF structures directly.

## Core safety rule

```text
structure determines WHERE
semantic analysis suggests WHAT IT MEANS
human review decides WHETHER IT IS DYNAMIC
deterministic document code performs the change
strict round-trip validation verifies the result
```

Evidence authority is ordered as:

1. `authoritative` — Padroniza tags, native Word controls, native PDF fields;
2. `structural` — tables, masks, controls, geometry, repeatable structures;
3. `semantic` — meaning/type/label/concept similarity;
4. `visual_hint` — color, underlining, spacing and other weak presentation signals.

Lower-authority evidence must not override higher-authority evidence.

## Local semantic engine

Implementation: `app/document/semantic_ai/`.

The first V6 engine is deliberately small and offline. It uses:

- curated Portuguese administrative/procurement concepts;
- normalized word/bigram/character features;
- a deterministic 384-dimension hashed vector representation;
- cosine similarity;
- local review memory from related template families.

It has **no cloud API, API key, network dependency, PyTorch, sentence-transformers or bundled LLM**. This keeps government/administrative documents local and avoids making the Windows package/build dramatically heavier. The semantic result is evidence only.

## Dynamic region concepts

V6 supports three semantic scopes:

- `inline` — one value embedded inside otherwise fixed prose;
- `paragraph` — an entire existing paragraph/body becomes a multiline value;
- `list` — a bullet/numbered content region becomes a repeatable list.

New canonical field type:

- `repeatable_list`

A repeatable list has `default_value` as a list plus `list_style`, `list_punctuation`, `minimum_items` and optional `maximum_items`. It is intentionally distinct from `repeatable_table`.

## Source anchors

Semantic candidates persist a versioned `source_anchor` containing structural ownership, paragraph fingerprints, original text, context and source spans. Anchors are designed to survive ordinary Word run changes and changed values in a related version of the same document.

Resolution policy:

1. exact paragraph fingerprint/owner where possible;
2. contextual left/right anchors;
3. controlled whole-paragraph/list relocation;
4. fail safely if the location cannot be recovered.

Preflight/repository normalization rejects malformed or scope-inconsistent anchors.

## Template-family learning

Reviewed semantic candidates are stored locally in `data/semantic_learning.json` through `SemanticLearningStore`.

Stored information includes:

- family/document fingerprints;
- location signature;
- accepted/rejected decision;
- field ID/type/semantic concept;
- source anchor;
- compact source context;
- list metadata;
- review count/timestamp.

An accepted mapping may become a preselected `learned_mapping` in a related document when its anchor relocates safely. A rejected region claims that source location so a fresh semantic pass does not repeatedly ask the author about the same content.

Fresh semantic discoveries (`semantic_inline`, `semantic_prose`, `repeatable_list`) remain review-only. They do not become automatically selected merely because semantic confidence is high.

## Real semantic benchmark

The first committed narrative benchmark comes from the real government document:

`tests/fixtures/semantic_v6/justificativa_vantajosidade_adesao_ata.docx`

Expected contract:

- `procurement.items` — repeatable list;
- `procurement.ata_number`;
- `procurement.managing_agency`;
- `organization.acronym`;
- five numbered justification bodies;
- conclusion paragraph;
- signer name;
- role;
- registration.

`tools/check_semantic_benchmark.py` requires:

- 13/13 expected regions;
- zero unexpected regions on the fixture;
- zero fresh semantic discoveries preselected.

The semantic benchmark is part of the local quality gate and the fast Windows release preflight.

## Round-trip rules

Accepted semantic regions are still written only by deterministic document code. Before the staged DOCX is published, the normal scanner must read the generated tags back successfully.

For `repeatable_list`, round-trip validation also requires the same field type, list style and punctuation. This prevents the semantic writer/tag parser/normal scanner from drifting apart.

## Template schema

`TEMPLATE_SCHEMA_VERSION = 2`.

Schema 1 templates remain loadable and normalize to schema 2 in memory. Schema 2 carries semantic/dynamic metadata and repeatable-list metadata. Older versions of Padroniza must reject a future schema rather than silently interpreting it incorrectly.

## Current benchmark/quality baseline

On the 2026-08-27 Linux verification environment:

- full pytest: **234 passed, 3 skipped**;
- semantic benchmark: **13/13 required, 0 unexpected, 0 fresh semantic preselected**;
- covered core total: **79.99%** (minimum gate: 75%);
- dead-module check: PASS;
- `compileall`: PASS.

The three skipped tests require PySide6/Windows-specific GUI behavior in this environment. Ruff/Pyright executables were not installed in the Linux review environment; Windows CI remains authoritative for those stages and real GUI startup.

## Non-goals

Scanner V6 is not:

- a Word processor;
- a cloud-document upload feature;
- an LLM that rewrites templates;
- permission for semantic evidence to override native controls/tags;
- a promise that author intent can be inferred with certainty.

When semantics are ambiguous, the correct result is a clearly explained review suggestion, not an automatic rewrite.
