# Scanner V4 — Structure-First Document Understanding

**Status:** current scanner architecture baseline  
**Scanner structure version:** `4`  
**Primary implementation:** `app/document/detection/`

Scanner V4 changes Padroniza from a mostly field-first detector into a **structure-first document-understanding pipeline**. The scanner should understand where content lives and what role it plays before it creates editable fields.

## Pipeline

```text
DOCX
 ↓
DocumentStructureExtractor
 ↓
SectionResolver
 ↓
TableAnalyzer
 ↓
ContentRoleClassifier
 ↓
CandidateDetector
 ↓
Context + Type Inference
 ↓
Stable ID Resolution
 ↓
Multidimensional Confidence
 ↓
Invariants / Review Model
 ↓
Apply accepted tags to staged DOCX
 ↓
Strict re-scan / round-trip validation
 ↓
Publish only when valid
```

## Structure before fields

`app/document/detection/structure.py` builds a stable structural view of the document. It identifies:

- numbered sections and subsection ownership;
- body/header/footer zones;
- physical Word tables and their record ownership;
- explicit/manual Padroniza tags and protected structures;
- stable ownership for paragraph records so fields do not silently fall back to a generic section.

A candidate is expected to retain a meaningful section and scanner-version metadata through review and conversion to the template field model.

## Table intelligence

`table_structure.py` classifies Word tables before ordinary cell-level detection. Supported structural categories include:

- `layout`;
- `repeatable`;
- `fixed_form`;
- `editable_sheet`;
- `reference`;
- `unknown`.

High-confidence table structures own their title/header/model/continuation rows. Lower-level detectors must not flatten owned cells into unrelated top-level fields.

Multi-level/merged headers are expanded using physical Word-grid positions. For example:

```text
Quantidade
├── 2023
├── 2024
└── 2025
```

becomes distinct columns such as `quantidade_2023`, `quantidade_2024`, and `quantidade_2025`.

Valid manually tagged repeatable tables are authoritative. Scanner V4 validates them but does not reinterpret their table structure. Untagged regions in the same document remain eligible for assisted detection.

## Sections

Numbered headings such as `1.`, `1.1`, `3.`, `5.2`, and `7.` form a section tree. Instruction-list items such as `1)` and `2)` inside a notes block must not be promoted to document sections merely because they begin with a number.

A table can also provide a stronger local section title, for example a merged numbered title row. Manually reviewed section assignments are preserved as manual metadata and should not be overwritten by later smart scans.

## Content roles

`roles.py` assigns structural roles before field inference. Current roles include:

- heading;
- instruction/note;
- field prompt;
- fill area;
- example;
- fixed text;
- signature;
- table title/header/data/reference;
- tagged content;
- header/footer content.

Formatting is evidence, not an absolute rule. For example, red text in government forms may be instructional text or a real placeholder depending on context.

### Terminal prompts

A common form pattern is:

```text
numbered section
→ long notes/instructions
→ final short prompt ending in ':'
```

Scanner V4 can classify that last paragraph as a field prompt when structural/context evidence is strong enough. This is how the DFD regression fixture detects section 4's delivery/start prediction as a date field without turning the preceding notes into inputs.

## Type inference

Field type inference combines multiple signals instead of depending on one keyword. Evidence can include:

- structural role;
- label vocabulary;
- placeholder patterns;
- native Word controls;
- neighboring text;
- enclosing section;
- table header hierarchy;
- formatting/context evidence.

Phone/date/etc. recognizers must be conservative. Numeric year headers such as `2023 2024 2025` are structural table labels, not phone fields.

## Confidence and review

Candidates expose overall confidence plus dimensions such as:

- `structure`;
- `fillable`;
- `label`;
- `type`.

They also carry evidence/reasons and review priority. Low or contradictory confidence should lead to review rather than silent restructuring.

The detector can produce a local scanner report with scanner version, candidate count, protected tables, ignored ambiguous structures, and other diagnostics useful for debugging without external telemetry.

## Safety invariants

Scanner V4 applies anti-flattening and anti-duplication checks. Expected invariants include:

- no duplicate top-level field IDs;
- every emitted candidate has a meaningful structural owner/section;
- repeatable-table column IDs are non-empty and unique;
- a structured table is not simultaneously flattened into unrelated standalone fields;
- manual tagged structures are protected from reinterpretation;
- automatically written tags must be readable by the strict normal DOCX scanner.

## Transactional automatic tagging

Accepted suggestions are never published directly to the destination. Padroniza:

1. copies the source to a staged temporary DOCX;
2. applies accepted tags there;
3. saves the staged file;
4. runs the strict normal tag scanner on its own output;
5. verifies expected field IDs and repeatable-table column structure;
6. atomically replaces the destination only after validation succeeds.

If validation fails, the existing destination is left untouched.

## Regression corpus

Real scanner bugs should become permanent fixtures, ideally paired with an expected structure contract.

Current key fixtures:

- `tests/fixtures/dfd_licitacao_tradicional_sia13tdr.docx`
- `tests/fixtures/dfd_licitacao_tradicional_sia13tdr_manual_tags.docx`
- `tests/fixtures/dfd_licitacao_tradicional_sia13tdr.expected.json`

The real DFD contract requires, among other things:

- section 3 remains one 9-column repeatable table;
- `Quantidade` expands into unique 2023/2024/2025 columns;
- no standalone `SIM` candidate survives from the table;
- section 4 yields a date field from its terminal prompt;
- the fiscalização matrix is not misclassified as a repeatable table;
- revision history remains reference structure;
- accepted real-document candidates survive detect → tag → strict re-scan.

## Development rule

When a new scanner problem is reported, prefer:

1. add/retain the real document as an anonymized regression fixture when allowed;
2. identify whether the failure is structural ownership, content role, candidate discovery, type inference, ID generation, confidence, application, or strict re-scan;
3. fix the responsible stage rather than adding a broad catch-all exception;
4. add a regression contract;
5. preserve manual tags and document resources such as headers/background images.
