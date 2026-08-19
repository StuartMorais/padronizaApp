from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from docx.document import Document as _Document
from docx.oxml.ns import qn

from app.document.detection.candidates import _candidate
from app.document.detection.context_helpers import (
    _contains_authoritative_marker, _context_label_for_record,
    _looks_like_fill_area_text, _nearest_section_title,
)
from app.document.detection.identifiers import (
    _clean_label, _local_label, _make_field_id, _normalize_space, _slug, _unique_field_id,
)
from app.document.detection.models import ParagraphRecord as _ParagraphRecord
from app.document.detection.patterns import (
    CHECKBOX_LINE_PATTERN, CHECKBOX_TOKEN_PATTERN, FOLLOWUP_AREA_PATTERN,
    ISOLATED_CHECK_MARK_PATTERN, SECTION_NUMBER_PATTERN,
)
from app.document.docx.controls import classify_native_control, get_control_identifier

def _detect_checkbox_choice_groups(
    document: _Document,
    records: list[_ParagraphRecord],
    known_ids: set[str],
    reserved_ordinals: set[int],
) -> list[dict[str, Any]]:
    del document
    result: list[dict[str, Any]] = []
    used_ordinals: set[int] = set(reserved_ordinals)

    # 1) Several checkbox options on the same visual line/cell, e.g.
    # ``Natureza: ☐ Material  ☐ Serviço  ☐ Material e serviço``.
    for record in records:
        if record.ordinal in used_ordinals or _contains_authoritative_marker(record.paragraph):
            continue
        parsed = _inline_checkbox_options(record.text or "")
        if parsed is None:
            continue
        prefix, options, token_spans = parsed
        label = _local_label(prefix) or _context_label_for_record(record, records)
        candidate = _checkbox_candidate(
            label=label,
            options=options,
            known_ids=known_ids,
            confidence=0.92,
            location={
                "kind": "checkbox_group_inline",
                "paragraph": record.ordinal,
                "checkbox_spans": [list(span) for span in token_spans],
            },
        )
        result.append(candidate)
        used_ordinals.add(record.ordinal)

    # 1b) One checkbox option in each cell of the same visual row.  Word forms
    # often use this for alternatives such as ``Entrega imediata`` versus
    # ``Entrega parcelada``.  The cell may also contain explanatory text after
    # a manual line break, so the ordinary whole-line checkbox regex cannot
    # safely recognize it.  Keep that explanatory text in the document and
    # use it as additional context in the client-facing option label.
    by_row: dict[tuple[str, int, int], list[_ParagraphRecord]] = defaultdict(list)
    for record in records:
        if (
            record.table_index is None
            or record.row_index is None
            or record.ordinal in used_ordinals
            or _contains_authoritative_marker(record.paragraph)
        ):
            continue
        by_row[(record.story, int(record.table_index), int(record.row_index))].append(record)

    for row_records in by_row.values():
        parsed_cells: list[tuple[_ParagraphRecord, str, tuple[int, int]]] = []
        seen_cells: set[int] = set()
        for record in sorted(row_records, key=lambda item: (item.cell_index or 0, item.ordinal)):
            if record.cell is None:
                continue
            cell_key = id(record.cell._tc)
            if cell_key in seen_cells:
                continue
            parsed = _single_checkbox_cell_option(record.text or "")
            if parsed is None:
                continue
            option_label, token_span = parsed
            seen_cells.add(cell_key)
            parsed_cells.append((record, option_label, token_span))

        if len(parsed_cells) < 2 or len(parsed_cells) > 6:
            continue

        label = _nearest_section_title(parsed_cells[0][0], records)
        if not label:
            label = _context_label_for_record(parsed_cells[0][0], records)
        candidate = _checkbox_candidate(
            label=label,
            options=[option_label for _record, option_label, _span in parsed_cells],
            known_ids=known_ids,
            confidence=0.94,
            location={
                "kind": "checkbox_group_multi_cell",
                "paragraphs": [record.ordinal for record, _label, _span in parsed_cells],
                "checkbox_spans": [list(span) for _record, _label, span in parsed_cells],
            },
        )
        result.append(candidate)
        used_ordinals.update(record.ordinal for record, _label, _span in parsed_cells)

    # 1c) Checkbox marker isolated in a narrow cell with the option text in
    # the adjacent cell. This pattern is common in institutional forms where
    # the left column contains only a square and the right column contains a
    # numbered occurrence/condition plus explanatory text.
    by_table_rows: dict[int, dict[int, list[_ParagraphRecord]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for record in records:
        if (
            record.table_index is None
            or record.row_index is None
            or record.ordinal in used_ordinals
        ):
            continue
        by_table_rows[int(record.table_index)][int(record.row_index)].append(record)

    for rows in by_table_rows.values():
        row_options: dict[
            int,
            tuple[_ParagraphRecord, str, tuple[int, int] | None, str],
        ] = {}
        row_cells: dict[int, dict[int, list[_ParagraphRecord]]] = {}
        explicit_marker_columns: set[int] = set()

        # First pass: collect rows whose marker is structurally present in the
        # narrow cell.  This is the normal case (Unicode marker, Word control,
        # symbol or drawing).
        for row_index, row_records in rows.items():
            by_cell_index: dict[int, list[_ParagraphRecord]] = defaultdict(list)
            for record in row_records:
                if record.cell_index is None:
                    continue
                by_cell_index[int(record.cell_index)].append(record)
            row_cells[row_index] = by_cell_index

            ordered_cells = sorted(by_cell_index)
            for cell_index in ordered_cells:
                marker_records = sorted(
                    by_cell_index[cell_index],
                    key=lambda item: item.ordinal,
                )
                marker = _isolated_checkbox_marker(marker_records)
                if marker is None:
                    continue
                marker_record, token_span, marker_mode = marker

                # Require the immediately adjacent visual cell. This avoids
                # pairing decorative checkboxes with unrelated text elsewhere
                # in a wide row.
                adjacent_records = sorted(
                    by_cell_index.get(cell_index + 1, []),
                    key=lambda item: item.ordinal,
                )
                option_text = _adjacent_checkbox_option_text(adjacent_records)
                if not option_text:
                    continue

                row_options[row_index] = (
                    marker_record,
                    option_text,
                    token_span,
                    marker_mode,
                )
                explicit_marker_columns.add(cell_index)
                break

        # Second pass: some institutional DOCX files draw a checked square as
        # an absolutely-positioned floating text box.  Visually it sits in the
        # narrow marker cell, but the actual table cell is completely empty.
        # Once this table has established a checkbox marker column from another
        # row, an empty cell in that same column followed by option-like text is
        # a strong signal that the row belongs to the same choice group.
        #
        # This intentionally does *not* infer a checkbox in arbitrary empty
        # cells: a structural marker must already exist in the same table and
        # the marker column must be narrow relative to its adjacent text cell.
        for row_index, by_cell_index in row_cells.items():
            if row_index in row_options:
                continue
            for cell_index in sorted(explicit_marker_columns):
                marker_records = sorted(
                    by_cell_index.get(cell_index, []),
                    key=lambda item: item.ordinal,
                )
                adjacent_records = sorted(
                    by_cell_index.get(cell_index + 1, []),
                    key=lambda item: item.ordinal,
                )
                if not marker_records or not adjacent_records:
                    continue
                if not _is_blank_checkbox_marker_cell(marker_records, adjacent_records):
                    continue
                option_text = _adjacent_checkbox_option_text(adjacent_records)
                if not option_text or not _looks_like_adjacent_choice_option(adjacent_records):
                    continue

                # Reuse the real blank paragraph in the marker cell. During
                # application it will be replaced with the normal checkbox tag.
                row_options[row_index] = (
                    marker_records[0],
                    option_text,
                    None,
                    "inferred_blank",
                )
                break

        ordered_rows = sorted(row_options)
        runs: list[list[int]] = []
        current: list[int] = []
        for row_index in ordered_rows:
            if current and row_index != current[-1] + 1:
                if len(current) >= 2:
                    runs.append(current)
                current = []
            current.append(row_index)
        if len(current) >= 2:
            runs.append(current)

        for row_run in runs:
            matched = [row_options[row_index] for row_index in row_run]
            if len(matched) > 8:
                matched = matched[:8]
            if any(record.ordinal in used_ordinals for record, _label, _span, _mode in matched):
                continue

            first_record = matched[0][0]
            label = _adjacent_checkbox_group_label(first_record, records)
            inferred_count = sum(
                1 for _record, _label, _span, mode in matched if mode == "inferred_blank"
            )
            candidate = _checkbox_candidate(
                label=label,
                options=[option for _record, option, _span, _mode in matched],
                known_ids=known_ids,
                confidence=0.89 if inferred_count else 0.93,
                location={
                    "kind": "checkbox_group_multi_cell",
                    "paragraphs": [record.ordinal for record, _label, _span, _mode in matched],
                    "checkbox_spans": [
                        list(span) if span is not None else [-1, -1]
                        for _record, _label, span, _mode in matched
                    ],
                    "checkbox_marker_modes": [
                        mode for _record, _label, _span, mode in matched
                    ],
                    "inferred_blank_markers": inferred_count,
                },
            )
            result.append(candidate)
            used_ordinals.update(record.ordinal for record, _label, _span, _mode in matched)

    # 2) Several checkbox paragraphs inside the same Word cell.
    by_cell: dict[int, list[_ParagraphRecord]] = defaultdict(list)
    for record in records:
        if record.cell is not None and record.ordinal not in used_ordinals:
            by_cell[id(record.cell._tc)].append(record)

    for cell_records in by_cell.values():
        matched: list[tuple[_ParagraphRecord, re.Match[str]]] = []
        for record in cell_records:
            if record.ordinal in used_ordinals or _contains_authoritative_marker(record.paragraph):
                continue
            match = CHECKBOX_LINE_PATTERN.match(record.text or "")
            if match:
                matched.append((record, match))
        if len(matched) < 2 or len(matched) > 8:
            continue

        label = _context_label_for_record(matched[0][0], records)
        candidate = _checkbox_candidate(
            label=label,
            options=[_normalize_space(match.group(1)) for _record, match in matched],
            known_ids=known_ids,
            confidence=0.90,
            location={
                "kind": "checkbox_group",
                "paragraphs": [record.ordinal for record, _match in matched],
            },
        )
        result.append(candidate)
        used_ordinals.update(record.ordinal for record, _match in matched)

    # 3) A checkbox on each consecutive row of a simple one-column table.
    # This is common for declarations/acknowledgements and previously made an
    # entire section disappear from automatic detection.
    by_table: dict[int, dict[int, list[_ParagraphRecord]]] = defaultdict(lambda: defaultdict(list))
    for record in records:
        if (
            record.table_index is None
            or record.row_index is None
            or record.ordinal in used_ordinals
        ):
            continue
        by_table[int(record.table_index)][int(record.row_index)].append(record)

    for rows in by_table.values():
        matching_rows: dict[int, tuple[_ParagraphRecord, re.Match[str]]] = {}
        for row_index, row_records in rows.items():
            nonempty = [record for record in row_records if _normalize_space(record.text)]
            matches: list[tuple[_ParagraphRecord, re.Match[str]]] = []
            for record in nonempty:
                if _contains_authoritative_marker(record.paragraph):
                    continue
                match = CHECKBOX_LINE_PATTERN.match(record.text or "")
                if match:
                    matches.append((record, match))
            if len(nonempty) == 1 and len(matches) == 1:
                matching_rows[row_index] = matches[0]

        ordered_rows = sorted(matching_rows)
        run: list[int] = []
        runs: list[list[int]] = []
        for row_index in ordered_rows:
            if run and row_index != run[-1] + 1:
                if len(run) >= 2:
                    runs.append(run)
                run = []
            run.append(row_index)
        if len(run) >= 2:
            runs.append(run)

        for row_run in runs:
            matched = [matching_rows[row_index] for row_index in row_run]
            if len(matched) > 8:
                matched = matched[:8]
            if any(record.ordinal in used_ordinals for record, _match in matched):
                continue
            label = _context_label_for_record(matched[0][0], records)
            candidate = _checkbox_candidate(
                label=label,
                options=[_normalize_space(match.group(1)) for _record, match in matched],
                known_ids=known_ids,
                confidence=0.87,
                location={
                    "kind": "checkbox_group",
                    "paragraphs": [record.ordinal for record, _match in matched],
                },
            )
            result.append(candidate)
            used_ordinals.update(record.ordinal for record, _match in matched)

    return result


def _detect_standalone_checkboxes(
    records: list[_ParagraphRecord],
    known_ids: set[str],
    reserved_ordinals: set[int],
) -> list[dict[str, Any]]:
    """Detect one independent checkbox embedded in an otherwise meaningful line.

    Institutional forms commonly use a declaration such as
    ``Declaro que ... ☐ Li e concordo``.  The multi-option detector correctly
    ignores it because there is only one checkbox, but the checkbox is still a
    real user input.  Keep this rule intentionally narrow: exactly one visible
    checkbox token, meaningful surrounding text, and no authoritative tag or
    Word control.
    """

    result: list[dict[str, Any]] = []
    for record in records:
        if record.ordinal in reserved_ordinals or _contains_authoritative_marker(record.paragraph):
            continue
        text = str(record.text or "")
        matches = list(CHECKBOX_TOKEN_PATTERN.finditer(text))
        if len(matches) != 1:
            continue
        match = matches[0]
        before = _normalize_space(text[: match.start()]).strip(" :：;|–—-")
        after = _normalize_space(text[match.end() :]).strip(" :：;|–—-")
        if not before and not after:
            continue
        if len(before) > 240 or len(after) > 160:
            continue

        # A single marker that is merely decorative beside an empty area is too
        # ambiguous.  Require actual declaration/option wording on at least one
        # side of the marker.
        semantic = after or before
        if len(semantic) < 2:
            continue

        if before and after:
            label = f"{before.rstrip('.;:')} — {after}"
        else:
            label = after or before
        label = _clean_label(label)
        if not label:
            continue

        field_id = _unique_field_id(_make_field_id(label), known_ids)
        result.append(
            _candidate(
                field_id=field_id,
                label=label,
                field_type="checkbox",
                confidence=0.92,
                source="checkbox_single",
                preview=_normalize_space(text),
                location={
                    "kind": "text_span",
                    "paragraph": record.ordinal,
                    "start": match.start(),
                    "end": match.end(),
                    "original": match.group(0),
                },
            )
        )
    return result


def _isolated_checkbox_marker(
    records: list[_ParagraphRecord],
) -> tuple[_ParagraphRecord, tuple[int, int] | None, str] | None:
    """Return an isolated checkbox marker from a narrow table cell.

    Real-world Word forms use several representations for the same visual
    square: Unicode box characters, bare check marks, unnamed content-control
    checkboxes, legacy form fields, Wingdings symbols and sometimes a small
    drawing/VML shape. This heuristic is intentionally limited to the narrow
    marker cell beside an option-description cell.
    """

    # Controls are inspected before visible text so a named Word control can
    # never be duplicated by automatic detection merely because its displayed
    # result happens to look like a checkbox character.
    for record in records:
        element = record.paragraph._p
        unnamed_controls = 0
        named_controls = 0
        for sdt in element.xpath(".//w:sdt"):
            properties = sdt.find(qn("w:sdtPr"))
            if properties is None:
                continue
            control_type, _control = classify_native_control(properties)
            if control_type != "checkbox":
                continue
            if get_control_identifier(sdt):
                named_controls += 1
            else:
                unnamed_controls += 1
        if named_controls:
            return None
        if unnamed_controls == 1:
            return record, None, "paragraph"

        unnamed_legacy = 0
        named_legacy = 0
        for fld_char in element.xpath(".//w:fldChar"):
            ff_data = fld_char.find(qn("w:ffData"))
            if ff_data is None or ff_data.find(qn("w:checkBox")) is None:
                continue
            name = ff_data.find(qn("w:name"))
            name_value = "" if name is None else str(name.get(qn("w:val"), "")).strip()
            if name_value:
                named_legacy += 1
            else:
                unnamed_legacy += 1
        if named_legacy:
            return None
        if unnamed_legacy == 1:
            return record, None, "paragraph"

    nonempty = [record for record in records if _normalize_space(record.text)]

    # Normal Unicode marker or a standalone check mark.
    if len(nonempty) == 1:
        record = nonempty[0]
        if _contains_authoritative_marker(record.paragraph):
            return None
        value = record.text or ""
        matches = list(CHECKBOX_TOKEN_PATTERN.finditer(value))
        if len(matches) == 1:
            match = matches[0]
            if not value[: match.start()].strip() and not value[match.end() :].strip():
                return record, (match.start(), match.end()), "text_span"

        check_matches = list(ISOLATED_CHECK_MARK_PATTERN.finditer(value))
        if len(check_matches) == 1:
            match = check_matches[0]
            if not value[: match.start()].strip() and not value[match.end() :].strip():
                return record, (match.start(), match.end()), "text_span"

    # Symbols and drawings often do not surface through paragraph.text.
    for record in records:
        element = record.paragraph._p
        if _normalize_space(record.text):
            continue

        symbols = element.xpath(".//w:sym")
        if len(symbols) == 1:
            font_name = str(symbols[0].get(qn("w:font"), "")).casefold()
            if any(token in font_name for token in ("wingdings", "webdings")):
                return record, None, "paragraph"

        # Old templates can use a tiny VML/Word drawing as the square/check.
        # Treat a single drawing in this marker-only cell as a checkbox signal;
        # the surrounding row-group requirement prevents isolated artwork from
        # becoming a field by itself.
        # Word commonly stores one drawing twice inside ``mc:AlternateContent``:
        # a DrawingML ``w:drawing`` choice plus a VML ``w:pict`` fallback.
        # Count that pair as one semantic marker rather than two independent
        # drawings. This is how many real institutional templates represent
        # an empty checkbox rectangle.
        alternate_contents = element.xpath(".//*[local-name()='AlternateContent']")
        if len(alternate_contents) == 1:
            alt = alternate_contents[0]
            alt_text = "".join((item.text or "") for item in alt.iter(qn("w:t"))).strip()
            alt_drawings = alt.xpath(".//*[local-name()='drawing' or local-name()='pict']")
            if alt_drawings and not alt_text:
                return record, None, "paragraph"

        drawings = element.xpath(".//w:drawing | .//w:pict")
        if len(drawings) == 1:
            return record, None, "paragraph"

    return None


def _cell_width_dxa(record: _ParagraphRecord) -> int | None:
    if record.cell is None:
        return None
    tc_pr = record.cell._tc.tcPr
    if tc_pr is None or tc_pr.tcW is None:
        return None
    raw = tc_pr.tcW.get(qn("w:w"))
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _is_blank_checkbox_marker_cell(
    marker_records: list[_ParagraphRecord],
    adjacent_records: list[_ParagraphRecord],
) -> bool:
    """Return whether an empty narrow cell can safely stand for a floating box.

    Some Word templates place a drawn checkbox in a floating shape whose XML
    is anchored outside the table. The table cell underneath is genuinely
    empty. We infer that row only after another row has established the same
    marker column as a checkbox column.
    """

    if not marker_records or not adjacent_records:
        return False
    if any(_normalize_space(record.text) for record in marker_records):
        return False
    for record in marker_records:
        element = record.paragraph._p
        if element.xpath(".//w:sdt | .//w:fldChar | .//w:sym | .//w:drawing | .//w:pict"):
            return False

    marker_width = _cell_width_dxa(marker_records[0])
    adjacent_width = _cell_width_dxa(adjacent_records[0])
    if marker_width is not None and adjacent_width is not None:
        if marker_width > 1800 or marker_width * 3 > adjacent_width:
            return False
    return True


def _looks_like_adjacent_choice_option(records: list[_ParagraphRecord]) -> bool:
    """Conservative evidence that the adjacent cell is an option, not prose."""

    visible = [record for record in records if _normalize_space(record.text)]
    if not visible:
        return False
    first = visible[0]
    value = _normalize_space(first.text)
    if re.match(r"^\d{1,3}[.)]\s*\S", value):
        return True
    p_pr = first.paragraph._p.pPr
    if p_pr is not None and p_pr.numPr is not None:
        return True
    # A short bold lead paragraph is also common for institutional options.
    if len(value) <= 180 and first.paragraph.runs:
        significant_runs = [run for run in first.paragraph.runs if (run.text or "").strip()]
        if significant_runs and all(bool(run.bold) for run in significant_runs):
            return True
    return False


def _adjacent_checkbox_option_text(records: list[_ParagraphRecord]) -> str:
    """Build the visible option label from the cell beside an isolated box."""

    parts: list[str] = []
    for record in records:
        value = _normalize_space(record.text)
        if not value:
            continue
        # A follow-up justification/observation prompt is a separate fill area,
        # not part of the choice label itself.
        if FOLLOWUP_AREA_PATTERN.match(value):
            break
        if _looks_like_fill_area_text(value):
            continue
        parts.append(value)
    if not parts:
        return ""
    option = " — ".join(parts)
    if len(option) > 360:
        option = option[:357].rstrip(" ,;:-") + "…"
    return _normalize_space(option)


def _adjacent_checkbox_group_label(
    record: _ParagraphRecord,
    records: list[_ParagraphRecord],
) -> str:
    """Find a concise group prompt for a vertical checkbox+description table."""

    prompt_map = {
        "ocorrência": "Ocorrência verificada",
        "ocorrências": "Ocorrências verificadas",
        "situacao": "Situação verificada",
        "situação": "Situação verificada",
        "situações": "Situações verificadas",
        "condição": "Condição verificada",
        "condições": "Condições verificadas",
        "alternativa": "Alternativa",
        "alternativas": "Alternativas",
        "opção": "Opção",
        "opções": "Opções",
    }
    tail_pattern = re.compile(
        r"(?:seguinte|seguintes)\s+"
        r"(ocorr[eê]ncias?|situa[cç][aã]o(?:ões)?|condi[cç][aã]o(?:ões)?|"
        r"alternativas?|op[cç][aã]o(?:ões)?)\s*:?\s*$",
        re.IGNORECASE,
    )
    for previous in reversed(records[: record.ordinal]):
        value = _normalize_space(previous.text)
        if not value:
            continue
        if previous.table_index == record.table_index:
            continue
        match = tail_pattern.search(value)
        if match:
            token = match.group(1).casefold()
            token = token.replace("ocorrencia", "ocorrência")
            return prompt_map.get(token, _clean_label(match.group(1)))
        if SECTION_NUMBER_PATTERN.match(value) and len(value) <= 190:
            return _clean_label(value)
        if value.endswith((":", "：")) and len(value) <= 110:
            return _clean_label(value)
        # Stop once we reach a normal prose paragraph outside this table. A
        # long declaration is context, but should not become the field label.
        if len(value) > 110:
            break
    return _nearest_section_title(record, records) or "Ocorrência verificada"


def _inline_checkbox_options(
    text: str,
) -> tuple[str, list[str], list[tuple[int, int]]] | None:
    matches = list(CHECKBOX_TOKEN_PATTERN.finditer(str(text or "")))
    if len(matches) < 2 or len(matches) > 8:
        return None

    options: list[str] = []
    spans: list[tuple[int, int]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        option = _normalize_space(text[match.end() : end]).strip(" |;–—-")
        if not option or len(option) > 220:
            return None
        options.append(option)
        spans.append((match.start(), match.end()))
    return text[: matches[0].start()], options, spans


def _single_checkbox_cell_option(
    text: str,
) -> tuple[str, tuple[int, int]] | None:
    """Parse one checkbox-led option from a table cell.

    The first visual line is the option itself.  Any following lines are kept
    as explanatory context in the UI label while remaining untouched in the
    DOCX when the checkbox token is replaced by a tag.
    """

    value = str(text or "")
    tokens = list(CHECKBOX_TOKEN_PATTERN.finditer(value))
    if len(tokens) != 1:
        return None
    token = tokens[0]
    if value[: token.start()].strip():
        return None

    remainder = value[token.end() :].strip()
    if not remainder:
        return None
    lines = [_normalize_space(line) for line in remainder.splitlines() if _normalize_space(line)]
    if not lines:
        return None
    option = lines[0].strip(" |;–—-")
    if not option or len(option) > 220:
        return None

    context = " ".join(line.strip() for line in lines[1:] if line.strip())
    if context:
        context = context.lstrip("*•-–— ").strip()
        if context and context.casefold() not in option.casefold():
            option = f"{option} — {context}"
    return _normalize_space(option), (token.start(), token.end())


def _checkbox_candidate(
    *,
    label: str,
    options: list[str],
    known_ids: set[str],
    confidence: float,
    location: dict[str, Any],
) -> dict[str, Any]:
    clean_options = [_normalize_space(option) for option in options if _normalize_space(option)]
    selection = _infer_checkbox_selection(label, clean_options)
    group_id = _unique_field_id(_make_field_id(label or "escolha"), known_ids)
    known_ids.add(group_id)
    ui_group = f"auto_checkbox_{group_id}"
    fields: list[dict[str, Any]] = []

    for index, option_text in enumerate(clean_options, start=1):
        option_id = _unique_field_id(
            f"{group_id}.{_slug(option_text)[:34] or f'opcao_{index}'}",
            known_ids,
        )
        known_ids.add(option_id)
        field: dict[str, Any] = {
            "id": option_id,
            "label": option_text,
            "type": "checkbox",
            "required": False,
            "selection": selection,
        }
        if selection == "single":
            field.update(
                {
                    "layout": "choice",
                    "layout_group": ui_group,
                    "layout_group_label": label or "Escolha uma opção",
                    "group": ui_group,
                    "choice_required": True,
                }
            )
        fields.append(field)

    return {
        "field_id": group_id,
        "label": label or ("Selecione as opções aplicáveis" if selection == "multiple" else "Escolha uma opção"),
        "type": "checkbox_group",
        "selection": selection,
        "confidence": confidence,
        "source": "checkbox_choice",
        "preview": " | ".join(clean_options),
        "location": dict(location),
        "fields": fields,
        "selected": True,
        "requires_configuration": False,
    }


def _infer_checkbox_selection(label: str, options: list[str]) -> str:
    combined = " ".join([str(label or ""), *options]).casefold()
    multiple_tokens = (
        "declaro",
        "declaramos",
        "autorizo",
        "autorizamos",
        "confirmo",
        "confirmamos",
        "aceito os termos",
        "ciência das declarações",
    )
    if any(token in combined for token in multiple_tokens):
        return "multiple"
    return "single"
