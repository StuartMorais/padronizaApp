# Scanner V6 — General editable-intent safety net (2026-08-31)

The scanner must not require a new Word document to reuse vocabulary or formatting from an older template before it can surface a possible field. Red text remains useful evidence, but it is only one signal among several.

## Discovery contract

The pipeline separates **discovery** from **understanding**:

1. authoritative Padroniza tags/native controls and strong structural detectors run first;
2. semantic discovery can identify known administrative concepts and dynamic regions;
3. visual-intent fallbacks can surface intentionally formatted spans;
4. the final general editable-intent pass surfaces unfamiliar but field-like structures that remain unclaimed;
5. ambiguous fallbacks stay review-only and are never silently preselected;
6. only approved candidates are written to the DOCX, and the result must pass the normal strict tag scanner before publication.

The last pass intentionally runs after semantic discovery so a generic guess cannot steal a region from a stronger detector or consume an ID that prevents a semantic concept from being emitted.

## General non-color signals

The review-only safety net currently covers:

- unfamiliar `Rótulo: valor atual` pairs in ordinary black text;
- unfamiliar `Rótulo | valor atual` table-cell pairs when the physical relationship is strong;
- compact choices after an explicit label, such as `Modalidade: Pregão / Dispensa / Inexigibilidade`;
- explicit fill instructions such as `[INFORMAR FONTE DE RECURSOS]` and `<Descrever objeto da contratação>` in any color;
- highlighted values;
- underlined values when they are compact and tied to a nearby label;
- non-red colored values such as blue/green/purple spans;
- run/paragraph styles whose names explicitly indicate editable/form-field intent;
- run shading used as a fill cue;
- editable text nested inside Word `w:txbxContent` text boxes/shapes.

`python-docx` does not expose text-box paragraphs through `document.paragraphs`. `app/document/detection/records.py` therefore adds those nested Word paragraphs to the normal record stream with stable ordinals. Approved text-box candidates use the same transactional tag application path, and the ordinary DOCX tag scanner already traverses text boxes during round-trip validation.

## Noise controls

Higher recall is useful only if the review list stays understandable. The fallback therefore rejects or de-prioritizes common static patterns, including:

- headings, notes, table headers/reference tables and signatures already classified structurally;
- legal labels beginning with law/decree/article/section vocabulary;
- URLs and hyperlink formatting;
- ordinary prose sentences and long values;
- lower-case grammatical `ou` inside prose unless an explicit field label makes the choice structure clear;
- underlining by itself when no compact labeled value is present;
- standalone colored/highlighted headings or signatures without nearby field-prompt context;
- generic bracket omissions such as `[...]` unless the bracket content begins with an explicit fill instruction verb.

The existing red-specific safety net remains in place and runs before the general fallback. Red remains evidence, not a requirement.

## Regression coverage

Synthetic regressions cover:

- black label/value discovery;
- black slash-delimited dropdowns;
- black `[INFORMAR ...]` placeholders;
- unfamiliar adjacent table label/value pairs;
- highlighted values;
- underlined value vs. underlined legal prose;
- blue/non-red colored values;
- field-named Word character styles;
- Word text-box discovery plus approved tag round-trip;
- rejection of ordinary legal `ou` prose and editorial `[...]`.

The supplied SIAGOV example corpus was also used as an external acceptance corpus during development. All 24 supported DOCX/DOCM/PDF files completed preparation/scanning; the XLSX file remains outside the template scanner input contract. The example documents themselves are not bundled into the project archive.

## Product principle

When a strong or combined signal suggests that content may vary but Padroniza cannot confidently classify its business meaning, the preferred result is a **possible field for human review**, not silent disappearance. False positives remain cheaper than false negatives because the review step can reject a candidate, while an omitted region gives the author no recovery signal.
