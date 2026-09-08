# Scanner V6 — Visual-intent safety net (2026-08-31)

This change addresses a recurring field-localization failure mode found in real SIAGOV documents: a new DOCX/DOCM can visually mark editable content in red, but the scanner used to ignore the region unless its exact wording matched a known vocabulary or one narrow `A ou B` pattern.

## Contract

Deterministic tags/native controls remain authoritative. Existing structural detectors still run first. The new visual layer is a **review-only fallback**: it broadens discovery without broadening silent application.

After the higher-confidence passes, unclaimed red content can now become one of:

- `colored_prompt`: a short, entirely-red field-like prompt/value, including labels not previously known to Padroniza;
- `colored_inline_choice`: a red inline option span using `OU`, `|`, spaced `/`, or a short semicolon-separated option list;
- `colored_choice_block`: red alternatives split across consecutive paragraphs and explicit `OU` separators;
- `colored_visual_field`: an otherwise-unclaimed red span/paragraph that looks intentionally editable, including angle-bracket instructions such as `< Informar a descrição do objeto ... >`.

All new ambiguous visual sources stay unchecked in the review dialog. This intentionally changes the failure mode from **silent false negative** to **visible possible field**.

## Formatting resolution

Red detection now follows common Word inheritance paths instead of inspecting only `run.font.color.rgb`:

1. direct run formatting;
2. character style and its base styles;
3. paragraph style and its base styles.

This prevents visually identical placeholders from being treated differently solely because one author applied red through a Word style.

## Noise controls

The fallback intentionally ignores common static guidance prefixes such as `Notas`, `Importante`, `Atenção`, `Aviso`, and short column-filling instructions. Whole red legal/policy paragraphs longer than the fallback limit are not converted unless a stronger detector claims them. Section headings in the body are not treated as short colored prompts.

Semicolons are only treated as option delimiters in short list-like text because semicolons are ordinary punctuation in legal clauses.

## PDF reliability found by the SIAGOV corpus

Several supplied SIAGOV PDFs contained invisible XML-invalid control bytes in extracted text. PyMuPDF returned the bytes correctly, but python-docx rejected them and aborted PDF -> DOCX preparation with `All strings must be XML compatible`.

The integrated PDF converter now strips only XML 1.0-invalid control characters at DOCX insertion boundaries while preserving printable Unicode. The affected PDFs now prepare and reach the scanner instead of failing before localization.

## Regression coverage

The automatic-field detector now tests:

- unknown red prompts;
- red inherited from a Word character style;
- inline red angle-bracket placeholders while preserving surrounding static prose;
- red slash-delimited dropdown options;
- red body `A / OU / B` choice blocks;
- suppression of static red `Importante:` guidance;
- PDF table text containing XML-invalid control characters.

Quality state after the change:

- `pytest`: 265 passed, 3 skipped;
- semantic benchmark: 13/13 required, 0 unexpected, 0 fresh semantic preselected;
- Python compilation: pass;
- dead-module gate: pass.
