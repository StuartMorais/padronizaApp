from __future__ import annotations

import re

from docx.text.paragraph import Paragraph
from docx.text.run import Run

from app.document.docx.tags import PLACEHOLDER_PATTERN
from app.document.detection.identifiers import (
    _clean_label, _is_reasonable_label, _looks_like_section_label,
    _normalize_space, _slug,
)
from app.document.detection.models import ParagraphRecord as _ParagraphRecord
from app.document.detection.patterns import (
    CHECKBOX_TOKEN_PATTERN, CURRENCY_PLACEHOLDER_PATTERN, GENERIC_DROPDOWN_PATTERN,
    INSTRUCTION_PATTERN, SAMPLE_EMAIL_PLACEHOLDER_PATTERN, SECTION_NUMBER_PATTERN,
    UNDERSCORE_PLACEHOLDER_PATTERN, X_PLACEHOLDER_PATTERN, ZERO_CPF_PLACEHOLDER_PATTERN,
    ZERO_PHONE_PLACEHOLDER_PATTERN,
)
from app.document.understanding.semantic import semantic_label, semantic_section
from app.document.understanding.smart_template import suggest_field_type

def _is_pure_fill_area_text(value: str) -> bool:
    """Return True when a cell consists only of the visual fill control.

    This is stricter than :func:`_looks_like_fill_area_text`: ``CPF: ___`` is
    *not* pure because the same cell contains another field's label, while
    ``___``, ``R$ ____`` and ``☐ Sim ☐ Não`` are pure fill areas.
    """

    text = _normalize_space(value)
    if not text:
        return True
    if X_PLACEHOLDER_PATTERN.fullmatch(text):
        return True
    if UNDERSCORE_PLACEHOLDER_PATTERN.fullmatch(text):
        return True
    if ZERO_PHONE_PLACEHOLDER_PATTERN.fullmatch(text):
        return True
    if ZERO_CPF_PLACEHOLDER_PATTERN.fullmatch(text):
        return True
    if CURRENCY_PLACEHOLDER_PATTERN.fullmatch(text):
        return True
    if SAMPLE_EMAIL_PLACEHOLDER_PATTERN.fullmatch(text):
        return True
    if GENERIC_DROPDOWN_PATTERN.fullmatch(text):
        return True
    if CHECKBOX_TOKEN_PATTERN.match(text) is not None:
        return True
    return False


def _looks_like_fill_area_text(value: str) -> bool:
    text = str(value or "")
    if not _normalize_space(text):
        return True
    return bool(
        PLACEHOLDER_PATTERN.search(text)
        or X_PLACEHOLDER_PATTERN.search(text)
        or UNDERSCORE_PLACEHOLDER_PATTERN.search(text)
        or ZERO_PHONE_PLACEHOLDER_PATTERN.search(text)
        or ZERO_CPF_PLACEHOLDER_PATTERN.search(text)
        or CURRENCY_PLACEHOLDER_PATTERN.search(text)
        or SAMPLE_EMAIL_PLACEHOLDER_PATTERN.search(text)
        or GENERIC_DROPDOWN_PATTERN.search(text)
        or CHECKBOX_TOKEN_PATTERN.search(text)
    )


def _nearest_section_title(
    record: _ParagraphRecord,
    records: list[_ParagraphRecord],
    *,
    preserve_number: bool = False,
) -> str:
    understood = semantic_section(record)
    if understood:
        return understood.rstrip(":").strip() if preserve_number else _clean_label(understood)
    for previous in reversed(records[: record.ordinal]):
        value = _normalize_space(previous.text)
        if not value:
            continue
        if SECTION_NUMBER_PATTERN.match(value) and len(value) <= 190:
            return value.rstrip(":").strip() if preserve_number else _clean_label(value)
        if previous.table_index == record.table_index:
            continue
        if _looks_like_section_label(value) and len(value) <= 190:
            return value.rstrip(":").strip() if preserve_number else _clean_label(value)
    return ""


def _repeatable_column_type(header: str, values: list[str]) -> str:
    for value in values:
        compact = _normalize_space(value)
        if re.fullmatch(r"_{2,}\s*/\s*_{2,}\s*/\s*_{2,}", compact):
            return "date"
        if ZERO_PHONE_PLACEHOLDER_PATTERN.fullmatch(compact):
            return "phone"
        if ZERO_CPF_PLACEHOLDER_PATTERN.fullmatch(compact):
            return "cpf"
        if CURRENCY_PLACEHOLDER_PATTERN.fullmatch(compact):
            return "currency"
        if SAMPLE_EMAIL_PLACEHOLDER_PATTERN.fullmatch(compact):
            return "email"
    return suggest_field_type(header)


def _detected_placeholder_type(label: str, preview: str) -> str:
    normalized_label = _slug(label)
    compact = _normalize_space(preview)
    if "observacao_curta" in normalized_label:
        return "text"
    # Questionnaire/matrix PDFs often reconstruct the short observation cell
    # as a modest underline next to a fixed row label. Keep those compact
    # instead of turning every label ending in ``Observação`` into a large
    # multiline editor. Long blank areas still become multiline elsewhere.
    if (
        normalized_label.endswith("_observacao")
        and re.fullmatch(r"_{2,}", compact)
        and len(compact) <= 20
    ):
        return "text"
    if re.fullmatch(r"_{2,}\s*/\s*_{2,}\s*/\s*_{2,}", compact):
        return "date"
    if ZERO_PHONE_PLACEHOLDER_PATTERN.fullmatch(compact):
        return "phone"
    if ZERO_CPF_PLACEHOLDER_PATTERN.fullmatch(compact):
        return "cpf"
    if CURRENCY_PLACEHOLDER_PATTERN.fullmatch(compact):
        return "currency"
    if SAMPLE_EMAIL_PLACEHOLDER_PATTERN.fullmatch(compact):
        return "email"
    return suggest_field_type(label)


def _same_cell_previous_label(
    record: _ParagraphRecord,
    records: list[_ParagraphRecord],
) -> str:
    if record.cell is None:
        return ""
    cell_key = id(record.cell._tc)
    for previous in reversed(records[: record.ordinal]):
        if previous.cell is None or id(previous.cell._tc) != cell_key:
            continue
        value = _normalize_space(previous.text)
        if not value or _looks_like_fill_area_text(value):
            continue
        if value.endswith((":", "：")) and _is_reasonable_label(value, maximum=140):
            return _clean_label(value)
        if _is_reasonable_label(value, maximum=100) and len(value.split()) <= 12:
            return _clean_label(value)
    return ""


def _table_axis_context(record: _ParagraphRecord) -> tuple[str, str]:
    """Return (row label, column label) for a field inside a table grid."""

    if record.table is None or record.row_index is None or record.cell_index is None:
        return "", ""
    try:
        row = record.table.rows[record.row_index]
        current_key = id(record.cell._tc) if record.cell is not None else None
        row_label = ""
        seen: set[int] = set()
        for cell in row.cells:
            key = id(cell._tc)
            if key in seen:
                continue
            seen.add(key)
            if current_key is not None and key == current_key:
                break
            value = _normalize_space(cell.text)
            if (
                _is_reasonable_label(value, maximum=120)
                and not _looks_like_fill_area_text(value)
                and not re.fullmatch(r"\d+", value)
            ):
                row_label = _clean_label(value)

        column_label = ""
        for row_index in range(record.row_index - 1, -1, -1):
            earlier = record.table.rows[row_index]
            if record.cell_index >= len(earlier.cells):
                continue
            value = _normalize_space(earlier.cells[record.cell_index].text)
            if not value or _looks_like_fill_area_text(value):
                continue
            cleaned = _clean_label(value)
            if (
                _is_reasonable_label(cleaned, maximum=90)
                and not SECTION_NUMBER_PATTERN.match(cleaned)
            ):
                column_label = cleaned
                break
        return row_label, column_label
    except (IndexError, AttributeError):
        return "", ""


def _context_label_for_record(
    record: _ParagraphRecord,
    records: list[_ParagraphRecord],
) -> str:
    understood_label, understood_source, understood_confidence = semantic_label(record)
    if understood_label and understood_confidence >= 0.72 and understood_source != "section_fallback":
        return _clean_label(understood_label)

    text = record.text or ""
    if ":" in text:
        before = text.split(":", 1)[0]
        if _is_reasonable_label(before):
            return _clean_label(before)

    same_cell = _same_cell_previous_label(record, records)
    if same_cell:
        return same_cell

    # Same table: prefer the previous cell in the same row.
    if record.table is not None and record.row_index is not None and record.cell_index is not None:
        try:
            row = record.table.rows[record.row_index]
            if record.cell_index > 0:
                previous = _normalize_space(row.cells[record.cell_index - 1].text)
                if _is_reasonable_label(previous) and not _looks_like_fill_area_text(previous):
                    return _clean_label(previous)
        except (IndexError, AttributeError):
            pass

        row_label, column_label = _table_axis_context(record)
        if row_label and column_label and row_label.casefold() != column_label.casefold():
            return f"{row_label} — {column_label}"
        if column_label:
            return column_label
        if row_label:
            return row_label

        # Search earlier rows for a section-like merged title or a short label.
        try:
            for row_index in range(record.row_index - 1, -1, -1):
                row = record.table.rows[row_index]
                unique_texts: list[str] = []
                seen_tc: set[int] = set()
                for cell in row.cells:
                    key = id(cell._tc)
                    if key in seen_tc:
                        continue
                    seen_tc.add(key)
                    value = _normalize_space(cell.text)
                    if value and value not in unique_texts:
                        unique_texts.append(value)
                if not unique_texts:
                    continue
                for value in unique_texts:
                    cleaned = _clean_label(value)
                    if _looks_like_section_label(cleaned):
                        return cleaned
                if len(unique_texts) == 1 and _is_reasonable_label(unique_texts[0], maximum=180):
                    return _clean_label(unique_texts[0])
        except (IndexError, AttributeError):
            pass

    # Document order fallback.
    for previous in reversed(records[: record.ordinal]):
        value = _normalize_space(previous.text)
        if not value:
            continue
        cleaned = _clean_label(value)
        if _looks_like_section_label(cleaned):
            return cleaned
        if _is_reasonable_label(cleaned, maximum=120):
            return cleaned
        break
    return ""


def _is_instruction_candidate(record: _ParagraphRecord) -> bool:
    text = _normalize_space(record.text)
    if not INSTRUCTION_PATTERN.match(text):
        return False
    if len(text) < 12 or len(text) > 800:
        return False
    # A paragraph containing several sentences of ordinary policy text can
    # begin with an imperative. Red text or table placement increases safety.
    return _paragraph_is_red(record.paragraph) or record.cell is not None


def _run_is_red(run: Run) -> bool:
    """Return True when a Word run is explicitly rendered as red.

    Keeping this at run granularity is important for institutional forms where
    only the editable fragment inside an otherwise static sentence is colored.
    """

    color = run.font.color.rgb
    if color is None:
        return False
    try:
        red, green, blue = int(color[0]), int(color[1]), int(color[2])
    except Exception:
        text = str(color)
        if len(text) != 6:
            return False
        try:
            red, green, blue = int(text[:2], 16), int(text[2:4], 16), int(text[4:], 16)
        except ValueError:
            return False
    return red >= 150 and red > green * 1.35 and red > blue * 1.35


def _paragraph_is_red(paragraph: Paragraph) -> bool:
    return any(_run_is_red(run) for run in paragraph.runs)


def _contains_authoritative_marker(paragraph: Paragraph) -> bool:
    text = paragraph.text or ""
    if PLACEHOLDER_PATTERN.search(text):
        return True
    element = paragraph._p
    return bool(element.xpath(".//w:sdt | .//w:fldChar"))
