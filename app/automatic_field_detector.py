from __future__ import annotations

import re
import shutil
import unicodedata
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

from docx import Document
from docx.document import Document as _Document
from docx.oxml.ns import qn
from docx.table import _Cell, Table
from docx.text.paragraph import Paragraph

from app.field_utils import compact_dropdown_options
from app.placeholder_scanner import PLACEHOLDER_PATTERN, scan_docx_fields
from app.smart_template import suggest_field_type


# The automatic detector is deliberately conservative. Explicit tags and Word
# form controls remain authoritative; this module only proposes additions.
X_PLACEHOLDER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:\(\d{2}\)\s*)?[Xx]{4,}(?:\s*[@./()\-]\s*[Xx]{2,})*(?![A-Za-z0-9])"
)
# Underscore masks are often short (``UF: __`` or ``Banco: ___``) and can
# include punctuation (``__/__/____``, ``___.___.___-__``).  Match the whole
# visual mask instead of only the longest underscore fragment so the inserted
# tag replaces the complete fill area.
UNDERSCORE_PLACEHOLDER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])_{2,}(?:\s*[/.:\-]\s*_{2,})*(?![A-Za-z0-9])"
)
ZERO_PHONE_PLACEHOLDER_PATTERN = re.compile(
    r"(?<!\d)\(\s*0{2}\s*\)\s*0{4,5}\s*-\s*0{4}(?!\d)"
)
SAMPLE_EMAIL_PLACEHOLDER_PATTERN = re.compile(
    r"(?i)(?<![A-Za-z0-9._%+\-])"
    r"(?:contato|email|e-mail|exemplo|teste|usuario|usu[aá]rio|user|x{4,})"
    r"@(?:empresa|exemplo|example|dominio|dom[ií]nio|x{4,})"
    r"(?:\.[A-Za-zx]{2,}){1,3}"
    r"(?![A-Za-z0-9._%+\-])"
)
CHOICE_SEPARATOR_PATTERN = re.compile(r"^\s*OU\s*$", re.IGNORECASE)
INSTRUCTION_PATTERN = re.compile(
    r"^\s*(?:informar|informe|descrever|descreva|detalhar|detalhe|"
    r"indicar|indique|justificar|justifique|preencher|preencha)\b",
    re.IGNORECASE,
)
GENERIC_DROPDOWN_PATTERN = re.compile(
    r"^\s*(?:escolher|selecione|selecionar)\s+(?:um|uma)\s+(?:item|op[cç][aã]o)\.?\s*$",
    re.IGNORECASE,
)
CHECKBOX_LINE_PATTERN = re.compile(r"^\s*(?:☐|□|☑|☒|\(\s*\))\s*(.+?)\s*$")
CHECKBOX_TOKEN_PATTERN = re.compile(r"(?:☐|□|☑|☒|\(\s*\))")
SECTION_NUMBER_PATTERN = re.compile(r"^\s*\d+(?:\.\d+)*\.?\s*")
LABEL_TAIL_PATTERN = re.compile(r"([^:;|]{2,120})\s*[:：]\s*$")


_SOURCE_LABELS = {
    "long_choice": "Alternativas separadas por OU",
    "repeatable_table": "Tabela com linhas repetíveis",
    "inline_placeholder": "Texto de preenchimento (XXXX ou sublinhado)",
    "instruction": "Texto instrucional substituível",
    "empty_cell": "Célula vazia ao lado de um rótulo",
    "dropdown_prompt": "Indicação 'Escolher um item'",
    "sample_value": "Valor de exemplo após o rótulo",
    "checkbox_choice": "Opções com caixas de seleção",
}


class AutomaticDetectionError(ValueError):
    """Raised when accepted automatic detections cannot be applied safely."""


class _ParagraphRecord:
    __slots__ = (
        "ordinal",
        "paragraph",
        "text",
        "story",
        "table_index",
        "row_index",
        "cell_index",
        "cell",
        "table",
    )

    def __init__(
        self,
        *,
        ordinal: int,
        paragraph: Paragraph,
        story: str,
        table_index: int | None = None,
        row_index: int | None = None,
        cell_index: int | None = None,
        cell: _Cell | None = None,
        table: Table | None = None,
    ) -> None:
        self.ordinal = ordinal
        self.paragraph = paragraph
        self.text = paragraph.text or ""
        self.story = story
        self.table_index = table_index
        self.row_index = row_index
        self.cell_index = cell_index
        self.cell = cell
        self.table = table


def detect_docx_field_candidates(
    docx_path: Path,
    *,
    existing_field_ids: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """Return conservative fill-field suggestions for an untagged DOCX.

    The result is safe to display in a review dialog. It does not modify the
    document. Explicit ``{{tags}}`` and native Word controls are excluded from
    automatic replacement candidates.
    """

    path = Path(docx_path)
    if not path.exists() or not path.is_file() or path.suffix.lower() != ".docx":
        raise AutomaticDetectionError("Selecione um arquivo DOCX válido.")

    document = Document(str(path))
    records = _collect_paragraph_records(document)
    by_ordinal = {record.ordinal: record for record in records}

    known_ids = {
        str(field_id).strip()
        for field_id in (existing_field_ids or [])
        if str(field_id).strip()
    }
    try:
        known_ids.update(
            str(field.get("id", "")).strip()
            for field in scan_docx_fields(path)
            if str(field.get("id", "")).strip()
        )
    except Exception:
        # Automatic detection should still be usable when an unrelated
        # malformed native control exists. The normal scanner will report
        # that issue before the model can be saved.
        pass

    candidates: list[dict[str, Any]] = []
    reserved_ordinals: set[int] = set()

    long_choices = _detect_long_choice_blocks(
        document,
        records,
        known_ids,
    )
    for candidate in long_choices:
        candidates.append(candidate)
        reserved_ordinals.update(
            int(value)
            for value in candidate.get("location", {}).get("paragraphs", [])
        )
        known_ids.add(str(candidate.get("field_id", "")))

    repeatable_tables = _detect_repeatable_tables(
        document,
        records,
        known_ids,
        reserved_ordinals,
    )
    for candidate in repeatable_tables:
        candidates.append(candidate)
        reserved_ordinals.update(
            int(value)
            for value in candidate.get("location", {}).get("paragraphs", [])
        )
        known_ids.add(str(candidate.get("field_id", "")))

    checkbox_choices = _detect_checkbox_choice_groups(
        document,
        records,
        known_ids,
        reserved_ordinals,
    )
    for candidate in checkbox_choices:
        candidates.append(candidate)
        reserved_ordinals.update(
            int(value)
            for value in candidate.get("location", {}).get("paragraphs", [])
        )
        for field in candidate.get("fields", []) or []:
            known_ids.add(str(field.get("id", "")))

    for record in records:
        if record.ordinal in reserved_ordinals:
            continue
        if _contains_authoritative_marker(record.paragraph):
            continue

        dropdown_prompt = _detect_dropdown_prompt(
            record,
            records,
            known_ids,
        )
        if dropdown_prompt is not None:
            candidates.append(dropdown_prompt)
            known_ids.add(str(dropdown_prompt.get("field_id", "")))
            continue

        sample_value = _detect_labeled_sample_value(
            record,
            known_ids,
        )
        if sample_value is not None:
            candidates.append(sample_value)
            known_ids.add(str(sample_value.get("field_id", "")))
            continue

        labeled_instruction = _detect_labeled_instruction(
            record,
            known_ids,
        )
        if labeled_instruction is not None:
            candidates.append(labeled_instruction)
            known_ids.add(str(labeled_instruction.get("field_id", "")))
            continue

        inline = _detect_inline_placeholders(
            record,
            records,
            known_ids,
        )
        if inline:
            candidates.extend(inline)
            known_ids.update(str(item.get("field_id", "")) for item in inline)
            continue

        text = _normalize_space(record.text)
        if not text:
            continue

        if _is_instruction_candidate(record):
            label = _context_label_for_record(record, records)
            field_type = "multiline" if len(text) >= 70 else suggest_field_type(label or text)
            if field_type == "text" and len(text) >= 70:
                field_type = "multiline"
            field_id = _unique_field_id(
                _make_field_id(label or text[:60]),
                known_ids,
            )
            known_ids.add(field_id)
            candidates.append(
                _candidate(
                    field_id=field_id,
                    label=label or _instruction_label(text),
                    field_type=field_type,
                    confidence=0.84 if _paragraph_is_red(record.paragraph) else 0.76,
                    source="instruction",
                    preview=text,
                    location={
                        "kind": "paragraph",
                        "paragraph": record.ordinal,
                    },
                )
            )
            continue

        label_only = _detect_label_only_field(
            record,
            records,
            known_ids,
        )
        if label_only is not None:
            candidates.append(label_only)
            known_ids.add(str(label_only.get("field_id", "")))

    candidates.extend(
        _detect_empty_cells(
            document,
            records,
            known_ids,
            reserved_ordinals,
        )
    )

    # Stable order keeps the review screen aligned with the source document.
    candidates.sort(
        key=lambda item: (
            _candidate_first_ordinal(item),
            -float(item.get("confidence", 0.0)),
            str(item.get("field_id", "")),
        )
    )
    for index, candidate in enumerate(candidates, start=1):
        candidate["candidate_id"] = f"candidate_{index:04d}"
    return candidates


def apply_docx_field_candidates(
    source_docx: Path,
    destination_docx: Path,
    candidates: Iterable[dict[str, Any]],
) -> Path:
    """Apply approved suggestions to a copy by converting them into tags.

    This is the key safety property of assisted detection: after approval the
    existing tag scanner and DOCX engine handle the model exactly like a
    manually tagged template.
    """

    source = Path(source_docx)
    destination = Path(destination_docx)
    accepted = [deepcopy(item) for item in candidates if isinstance(item, dict)]
    if not accepted:
        raise AutomaticDetectionError("Nenhuma sugestão foi selecionada.")

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    document = Document(str(destination))
    records = _collect_paragraph_records(document)
    by_ordinal = {record.ordinal: record for record in records}

    _validate_accepted_candidates(accepted)

    # Whole-block operations are applied first. They do not invalidate the
    # stored Paragraph XML objects used by the span replacements below.
    for candidate in accepted:
        kind = str(candidate.get("location", {}).get("kind", ""))
        if kind == "repeatable_table":
            _apply_repeatable_table(candidate, document)
        elif kind == "paragraph_block":
            _apply_paragraph_block(candidate, by_ordinal)
        elif kind == "checkbox_group":
            _apply_checkbox_group(candidate, by_ordinal)
        elif kind == "checkbox_group_inline":
            _apply_inline_checkbox_group(candidate, by_ordinal)
        elif kind == "checkbox_group_multi_cell":
            _apply_multi_cell_checkbox_group(candidate, by_ordinal)

    # Apply text spans from right to left inside each paragraph so offsets stay
    # valid even when one line contains several placeholders.
    spans_by_paragraph: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for candidate in accepted:
        location = candidate.get("location", {}) or {}
        if str(location.get("kind", "")) == "text_span":
            spans_by_paragraph[int(location.get("paragraph", -1))].append(candidate)

    for ordinal, paragraph_candidates in spans_by_paragraph.items():
        record = by_ordinal.get(ordinal)
        if record is None:
            raise AutomaticDetectionError(
                "A estrutura do DOCX mudou durante a detecção automática. "
                "Execute a análise novamente."
            )
        replacements: list[tuple[int, int, str]] = []
        for candidate in paragraph_candidates:
            location = candidate.get("location", {}) or {}
            replacements.append(
                (
                    int(location.get("start", 0)),
                    int(location.get("end", 0)),
                    _tag_for_candidate(candidate),
                )
            )
        _replace_paragraph_spans(record.paragraph, replacements)

    for candidate in accepted:
        location = candidate.get("location", {}) or {}
        kind = str(location.get("kind", ""))
        if kind == "append_tag":
            ordinal = int(location.get("paragraph", -1))
            record = by_ordinal.get(ordinal)
            if record is None:
                raise AutomaticDetectionError(
                    "Não foi possível localizar uma área aprovada no DOCX. "
                    "Execute a análise novamente."
                )
            _append_tag_to_paragraph(record.paragraph, _tag_for_candidate(candidate))
            continue
        if kind not in {"paragraph", "empty_cell"}:
            continue
        ordinal = int(location.get("paragraph", -1))
        record = by_ordinal.get(ordinal)
        if record is None:
            raise AutomaticDetectionError(
                "Não foi possível localizar uma área aprovada no DOCX. "
                "Execute a análise novamente."
            )
        _replace_entire_paragraph(record.paragraph, _tag_for_candidate(candidate))

    document.save(str(destination))
    return destination


def candidate_field_definitions(
    candidates: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Convert approved candidates to normal editable field definitions."""

    fields: list[dict[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        if str(candidate.get("source", "")) == "repeatable_table":
            field_id = str(candidate.get("field_id", "")).strip()
            if not field_id:
                continue
            fields.append(
                {
                    "id": field_id,
                    "label": str(candidate.get("label", "")).strip() or field_id,
                    "type": "repeatable_table",
                    "columns": [
                        dict(column)
                        for column in candidate.get("columns", []) or []
                        if isinstance(column, dict)
                    ],
                    "minimum_rows": 1,
                    "numbering_padding": 2,
                    "required": True,
                    "label_source": "automatic_detection",
                    "type_source": "automatic_detection",
                    "detection_source": "automatic",
                    "detection_confidence": float(candidate.get("confidence", 0.0)),
                    "full_width": True,
                }
            )
            if str(candidate.get("section", "")).strip():
                fields[-1]["section"] = str(candidate.get("section", "")).strip()
            continue
        if str(candidate.get("source", "")) == "checkbox_choice":
            for raw_field in candidate.get("fields", []) or []:
                field = dict(raw_field)
                field.setdefault("required", False)
                field.setdefault("label_source", "automatic_detection")
                field.setdefault("type_source", "automatic_detection")
                field["detection_source"] = "automatic"
                field["detection_confidence"] = float(candidate.get("confidence", 0.0))
                fields.append(field)
            continue

        field_id = str(candidate.get("field_id", "")).strip()
        if not field_id:
            continue
        field: dict[str, Any] = {
            "id": field_id,
            "label": str(candidate.get("label", "")).strip(),
            "type": str(candidate.get("type", "text")).strip() or "text",
            "required": str(candidate.get("type", "text")) != "checkbox",
            "label_source": "automatic_detection",
            "type_source": "automatic_detection",
            "detection_source": "automatic",
            "detection_confidence": float(candidate.get("confidence", 0.0)),
        }
        options = compact_dropdown_options(candidate.get("options", []))
        if options:
            field["options"] = options
        placeholder = str(candidate.get("placeholder", "")).strip()
        if placeholder:
            field["placeholder"] = placeholder
        if str(candidate.get("layout", "")) == "choice":
            group = str(candidate.get("layout_group", f"auto_choice_{field_id}"))
            field.update(
                {
                    "layout": "choice",
                    "layout_group": group,
                    "layout_group_label": field["label"],
                    "group": group,
                    "selection": "single",
                    "choice_required": True,
                    "tag_type": "single_choice",
                }
            )
        # Automatically detected dates represent visible fill areas in the
        # source document (for example ``Data: __/__/____``). They must stay
        # editable instead of being silently replaced with today's date.
        if field["type"] == "date":
            field["automatic"] = False
        if field["type"] == "multiline":
            field["full_width"] = True
        fields.append(field)
    return fields


def candidate_source_label(candidate: dict[str, Any]) -> str:
    return _SOURCE_LABELS.get(
        str(candidate.get("source", "")),
        "Sugestão automática",
    )


def _candidate(
    *,
    field_id: str,
    label: str,
    field_type: str,
    confidence: float,
    source: str,
    preview: str,
    location: dict[str, Any],
    options: Iterable[Any] | None = None,
    default_selected: bool | None = None,
    requires_configuration: bool = False,
    layout: str = "",
    layout_group: str = "",
    placeholder: str = "",
) -> dict[str, Any]:
    confidence = max(0.0, min(float(confidence), 1.0))
    if default_selected is None:
        default_selected = confidence >= 0.80 and not requires_configuration
    result: dict[str, Any] = {
        "field_id": field_id,
        "label": _normalize_space(label) or field_id,
        "type": field_type,
        "confidence": confidence,
        "source": source,
        "preview": _normalize_space(preview)[:420],
        "location": dict(location),
        "selected": bool(default_selected),
        "requires_configuration": bool(requires_configuration),
    }
    cleaned_options = compact_dropdown_options(options or [])
    if cleaned_options:
        result["options"] = cleaned_options
    if layout:
        result["layout"] = layout
    if layout_group:
        result["layout_group"] = layout_group
    if str(placeholder).strip():
        result["placeholder"] = str(placeholder).strip()
    return result


def _collect_paragraph_records(document: _Document) -> list[_ParagraphRecord]:
    records: list[_ParagraphRecord] = []
    seen_cells: set[int] = set()

    def add_paragraph(
        paragraph: Paragraph,
        *,
        story: str,
        table_index: int | None = None,
        row_index: int | None = None,
        cell_index: int | None = None,
        cell: _Cell | None = None,
        table: Table | None = None,
    ) -> None:
        records.append(
            _ParagraphRecord(
                ordinal=len(records),
                paragraph=paragraph,
                story=story,
                table_index=table_index,
                row_index=row_index,
                cell_index=cell_index,
                cell=cell,
                table=table,
            )
        )

    def walk_table(table: Table, *, story: str, index: int) -> None:
        for row_index, row in enumerate(table.rows):
            for cell_index, cell in enumerate(row.cells):
                cell_key = id(cell._tc)
                if cell_key in seen_cells:
                    continue
                seen_cells.add(cell_key)
                for paragraph in cell.paragraphs:
                    add_paragraph(
                        paragraph,
                        story=story,
                        table_index=index,
                        row_index=row_index,
                        cell_index=cell_index,
                        cell=cell,
                        table=table,
                    )
                for nested in cell.tables:
                    nonlocal_table_index[0] += 1
                    walk_table(
                        nested,
                        story=story,
                        index=nonlocal_table_index[0],
                    )

    nonlocal_table_index = [-1]
    body = document.element.body
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            add_paragraph(Paragraph(child, document), story="body")
        elif child.tag == qn("w:tbl"):
            nonlocal_table_index[0] += 1
            walk_table(Table(child, document), story="body", index=nonlocal_table_index[0])

    # Headers and footers are included for ordinary placeholder suggestions,
    # but long choice-block detection remains focused on body tables.
    for section_index, section in enumerate(document.sections):
        for story_name, story in (
            (f"header_{section_index}", section.header),
            (f"footer_{section_index}", section.footer),
        ):
            for paragraph in story.paragraphs:
                add_paragraph(paragraph, story=story_name)
            for table in story.tables:
                nonlocal_table_index[0] += 1
                walk_table(table, story=story_name, index=nonlocal_table_index[0])

    return records


def _detect_long_choice_blocks(
    document: _Document,
    records: list[_ParagraphRecord],
    known_ids: set[str],
) -> list[dict[str, Any]]:
    del document
    by_cell: dict[int, list[_ParagraphRecord]] = defaultdict(list)
    for record in records:
        if record.cell is not None and record.story == "body":
            by_cell[id(record.cell._tc)].append(record)

    result: list[dict[str, Any]] = []
    for cell_records in by_cell.values():
        cell_records.sort(key=lambda item: item.ordinal)
        texts = [_normalize_space(record.text) for record in cell_records]
        separators = [
            index
            for index, text in enumerate(texts)
            if CHOICE_SEPARATOR_PATTERN.match(text)
        ]
        if len(separators) < 2:
            continue
        if any(_contains_authoritative_marker(record.paragraph) for record in cell_records):
            continue

        segment_ranges: list[tuple[int, int]] = []
        start = 0
        for separator in separators:
            segment_ranges.append((start, separator))
            start = separator + 1
        segment_ranges.append((start, len(cell_records)))

        options: list[dict[str, str]] = []
        first_content_index: int | None = None
        last_content_index: int | None = None
        for range_start, range_end in segment_ranges:
            segment_records = [
                record
                for record in cell_records[range_start:range_end]
                if _normalize_space(record.text)
            ]
            if not segment_records:
                continue
            value = _normalize_space("\n".join(record.text for record in segment_records))
            if len(value) < 5:
                continue
            # Avoid interpreting page headers repeated inside a malformed cell
            # as an option.
            if _looks_like_page_header(value):
                continue
            label = _short_choice_label(value)
            options.append({"label": label, "value": value})
            segment_first = cell_records.index(segment_records[0])
            segment_last = cell_records.index(segment_records[-1])
            first_content_index = (
                segment_first
                if first_content_index is None
                else min(first_content_index, segment_first)
            )
            last_content_index = (
                segment_last
                if last_content_index is None
                else max(last_content_index, segment_last)
            )

        if len(options) < 3 or len(options) > 10:
            continue
        if first_content_index is None or last_content_index is None:
            continue

        included = cell_records[first_content_index : last_content_index + 1]
        included_ordinals = [record.ordinal for record in included]
        # Include separators between the first and last option in the replaced
        # block, but never remove text outside that block.
        label = _context_label_for_record(included[0], records)
        field_id = _unique_field_id(
            _make_field_id(label or "justificativa"),
            known_ids,
        )
        group = f"auto_choice_{field_id}"
        result.append(
            _candidate(
                field_id=field_id,
                label=label or "Escolha uma alternativa",
                field_type="dropdown",
                confidence=0.94,
                source="long_choice",
                preview=" OU ".join(option["label"] for option in options),
                location={
                    "kind": "paragraph_block",
                    "paragraphs": included_ordinals,
                },
                options=options,
                layout="choice",
                layout_group=group,
            )
        )
    return result


def _detect_repeatable_tables(
    document: _Document,
    records: list[_ParagraphRecord],
    known_ids: set[str],
    reserved_ordinals: set[int],
) -> list[dict[str, Any]]:
    """Detect conservative numbered tables that represent repeated records.

    The automatic detector only proposes a repeatable table when the evidence
    is strong: a header row, at least two numbered data rows, and at least two
    editable columns.  This intentionally avoids turning questionnaire tables
    (which also have repeated visual rows) into repeatable item editors.
    """

    top_level_index = {
        id(table._tbl): index
        for index, table in enumerate(document.tables)
    }
    by_table: dict[int, list[_ParagraphRecord]] = defaultdict(list)
    table_refs: dict[int, Table] = {}
    for record in records:
        if record.story != "body" or record.table is None or record.table_index is None:
            continue
        table_key = id(record.table._tbl)
        if table_key not in top_level_index:
            continue
        by_table[table_key].append(record)
        table_refs[table_key] = record.table

    result: list[dict[str, Any]] = []
    for table_key, table_records in by_table.items():
        table = table_refs[table_key]
        if len(table.rows) < 3:
            continue
        if any(
            record.ordinal in reserved_ordinals
            or _contains_authoritative_marker(record.paragraph)
            for record in table_records
        ):
            continue

        header_cells = _unique_row_cells(table.rows[0])
        if len(header_cells) < 3:
            continue
        headers = [_clean_label(cell.text) for cell in header_cells]
        if sum(_is_reasonable_label(value, maximum=80) for value in headers) < 3:
            continue

        data_rows: list[int] = []
        number_values: list[int] = []
        for row_index in range(1, len(table.rows)):
            cells = _unique_row_cells(table.rows[row_index])
            if len(cells) != len(header_cells):
                break
            number_text = _normalize_space(cells[0].text)
            if not re.fullmatch(r"0*\d{1,4}", number_text):
                break
            data_rows.append(row_index)
            number_values.append(int(number_text))

        if len(data_rows) < 2:
            continue
        expected = list(range(number_values[0], number_values[0] + len(number_values)))
        if number_values != expected:
            continue

        number_header = _slug(headers[0])
        if number_header not in {"n", "no", "numero", "item", "n_item"}:
            continue

        editable_columns: list[int] = []
        for column_index in range(1, len(header_cells)):
            values = [
                _normalize_space(_unique_row_cells(table.rows[row_index])[column_index].text)
                for row_index in data_rows
            ]
            if any(_looks_like_fill_area_text(value) or not value for value in values):
                editable_columns.append(column_index)
        if len(editable_columns) < 2:
            continue

        first_record = min(table_records, key=lambda item: item.ordinal)
        section_title = _nearest_section_title(first_record, records, preserve_number=True)
        label = _clean_label(section_title) if section_title else "Itens da tabela"
        field_id = _unique_field_id(_make_field_id(label), known_ids)

        columns: list[dict[str, Any]] = [
            {
                "id": "item",
                "label": headers[0] or "Item",
                "type": "auto_number",
                "required": False,
            }
        ]
        used_column_ids = {"item"}
        for column_index in editable_columns:
            header = headers[column_index] or f"Coluna {column_index + 1}"
            column_values = [
                _normalize_space(_unique_row_cells(table.rows[row_index])[column_index].text)
                for row_index in data_rows
            ]
            column_id = _slug(header) or f"coluna_{column_index + 1}"
            base_column_id = column_id
            suffix = 2
            while column_id in used_column_ids:
                column_id = f"{base_column_id}_{suffix}"
                suffix += 1
            used_column_ids.add(column_id)
            columns.append(
                {
                    "id": column_id,
                    "label": header,
                    "type": _repeatable_column_type(header, column_values),
                    "required": True,
                    "column_index": column_index,
                }
            )

        row_ordinals = sorted(
            record.ordinal
            for record in table_records
            if record.row_index in data_rows
        )
        result.append(
            _candidate(
                field_id=field_id,
                label=label,
                field_type="repeatable_table",
                confidence=0.95,
                source="repeatable_table",
                preview=" | ".join(headers)
                + f" — {len(data_rows)} linha(s) modelo detectada(s)",
                location={
                    "kind": "repeatable_table",
                    "document_table_index": top_level_index[table_key],
                    "template_row": data_rows[0],
                    "data_rows": data_rows,
                    "paragraphs": row_ordinals,
                },
            )
        )
        result[-1]["columns"] = columns
        if section_title:
            result[-1]["section"] = section_title.rstrip(":").strip()
        result[-1]["selected"] = True

    return result


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


def _detect_inline_placeholders(
    record: _ParagraphRecord,
    records: list[_ParagraphRecord],
    known_ids: set[str],
) -> list[dict[str, Any]]:
    text = record.text or ""
    if not text or PLACEHOLDER_PATTERN.search(text):
        return []

    matches = list(X_PLACEHOLDER_PATTERN.finditer(text))
    matches.extend(UNDERSCORE_PLACEHOLDER_PATTERN.finditer(text))
    matches.extend(ZERO_PHONE_PLACEHOLDER_PATTERN.finditer(text))
    matches.extend(SAMPLE_EMAIL_PLACEHOLDER_PATTERN.finditer(text))
    matches.sort(key=lambda match: (match.start(), -(match.end() - match.start())))
    # Some patterns intentionally overlap (for example an xxxxx@example style
    # e-mail also matches the generic X placeholder). Keep only the widest
    # non-overlapping span so one visual fill area becomes one field.
    non_overlapping: list[re.Match[str]] = []
    for match in matches:
        if any(
            match.start() < existing.end() and existing.start() < match.end()
            for existing in non_overlapping
        ):
            continue
        non_overlapping.append(match)
    matches = sorted(non_overlapping, key=lambda match: match.start())
    if not matches:
        return []

    result: list[dict[str, Any]] = []
    previous_end = 0
    for match in matches:
        label = _local_label(text[previous_end : match.start()])
        if not label:
            label = _context_label_for_record(record, records)
        field_id = _unique_field_id(
            _make_field_id(label or f"campo_{record.ordinal + 1}"),
            known_ids,
        )
        known_ids.add(field_id)
        field_type = _detected_placeholder_type(label or field_id, match.group(0))
        result.append(
            _candidate(
                field_id=field_id,
                label=label or _humanize_id(field_id),
                field_type=field_type,
                confidence=0.91 if label else 0.74,
                source="inline_placeholder",
                preview=match.group(0),
                location={
                    "kind": "text_span",
                    "paragraph": record.ordinal,
                    "start": match.start(),
                    "end": match.end(),
                    "original": match.group(0),
                },
            )
        )
        previous_end = match.end()
    return result


def _detect_dropdown_prompt(
    record: _ParagraphRecord,
    records: list[_ParagraphRecord],
    known_ids: set[str],
) -> dict[str, Any] | None:
    text = record.text or ""
    if not text or PLACEHOLDER_PATTERN.search(text):
        return None

    prompt_pattern = re.compile(
        r"(?:escolher|selecione|selecionar)\s+(?:um|uma)\s+"
        r"(?:item|op[cç][aã]o)\.?\s*$",
        re.IGNORECASE,
    )
    match = prompt_pattern.search(text)
    if match is None:
        return None

    prefix = text[: match.start()]
    label = _local_label(prefix) or _context_label_for_record(record, records)
    field_id = _unique_field_id(_make_field_id(label or "opcao"), known_ids)
    return _candidate(
        field_id=field_id,
        label=label or "Selecione uma opção",
        field_type="dropdown",
        confidence=0.82 if label else 0.70,
        source="dropdown_prompt",
        preview=match.group(0),
        location={
            "kind": "text_span",
            "paragraph": record.ordinal,
            "start": match.start(),
            "end": match.end(),
            "original": match.group(0),
        },
        options=[],
        default_selected=False,
        requires_configuration=True,
    )


def _detect_labeled_sample_value(
    record: _ParagraphRecord,
    known_ids: set[str],
) -> dict[str, Any] | None:
    """Detect short example/default values that should still be editable.

    This is deliberately whitelist-based.  Institutional fixed text such as
    ``Órgão: Secretaria ...`` must stay static, while values such as
    ``País: Brasil`` are commonly examples/defaults that help the user
    understand what belongs in the field.
    """

    text = record.text or ""
    if not text or PLACEHOLDER_PATTERN.search(text) or ":" not in text:
        return None

    colon = text.find(":")
    label = _clean_label(text[:colon])
    value_start = colon + 1
    while value_start < len(text) and text[value_start].isspace():
        value_start += 1
    value = _normalize_space(text[value_start:])
    if not value or len(value) > 80:
        return None

    normalized_label = _slug(label)
    editable_example_labels = {
        "pais",
        "nacionalidade",
    }
    if normalized_label not in editable_example_labels:
        return None
    if (
        INSTRUCTION_PATTERN.match(value)
        or GENERIC_DROPDOWN_PATTERN.match(value)
        or CHECKBOX_TOKEN_PATTERN.search(value)
        or X_PLACEHOLDER_PATTERN.search(value)
        or UNDERSCORE_PLACEHOLDER_PATTERN.search(value)
        or ZERO_PHONE_PLACEHOLDER_PATTERN.search(value)
        or SAMPLE_EMAIL_PLACEHOLDER_PATTERN.search(value)
    ):
        return None

    field_id = _unique_field_id(_make_field_id(label), known_ids)
    return _candidate(
        field_id=field_id,
        label=label,
        field_type=suggest_field_type(label),
        confidence=0.86,
        source="sample_value",
        preview=value,
        location={
            "kind": "text_span",
            "paragraph": record.ordinal,
            "start": value_start,
            "end": len(text),
            "original": text[value_start:],
        },
        placeholder=value,
    )


def _detect_labeled_instruction(
    record: _ParagraphRecord,
    known_ids: set[str],
) -> dict[str, Any] | None:
    text = record.text or ""
    if not text or PLACEHOLDER_PATTERN.search(text) or ":" not in text:
        return None
    colon = text.find(":")
    label = _clean_label(text[:colon])
    tail_start = colon + 1
    while tail_start < len(text) and text[tail_start].isspace():
        tail_start += 1
    tail = text[tail_start:]
    if not _is_reasonable_label(label, maximum=120) or not INSTRUCTION_PATTERN.match(tail):
        return None
    if len(_normalize_space(tail)) < 12 or len(_normalize_space(tail)) > 800:
        return None

    field_type = suggest_field_type(label)
    if field_type == "text" and len(_normalize_space(tail)) >= 70:
        field_type = "multiline"
    field_id = _unique_field_id(_make_field_id(label), known_ids)
    return _candidate(
        field_id=field_id,
        label=label,
        field_type=field_type,
        confidence=0.90 if _paragraph_is_red(record.paragraph) else 0.82,
        source="instruction",
        preview=tail,
        location={
            "kind": "text_span",
            "paragraph": record.ordinal,
            "start": tail_start,
            "end": len(text),
            "original": tail,
        },
    )


def _detect_label_only_field(
    record: _ParagraphRecord,
    records: list[_ParagraphRecord],
    known_ids: set[str],
) -> dict[str, Any] | None:
    text = _normalize_space(record.text)
    if (
        not text.endswith(":")
        or record.cell is None
        or len(record.cell.paragraphs) != 1
        or _contains_authoritative_marker(record.paragraph)
    ):
        return None
    label = _clean_label(text)
    if not _is_reasonable_label(label, maximum=100):
        return None
    if _looks_like_section_label(text) and SECTION_NUMBER_PATTERN.match(text):
        return None

    # A bare label inside a form row is a useful suggestion when an adjacent
    # cell is another fill area. This catches forms that visually leave the
    # rest of the same cell blank, e.g. ``Responsável legal:``.
    has_form_neighbor = False
    if record.table is not None and record.row_index is not None:
        try:
            row = record.table.rows[record.row_index]
            for cell in row.cells:
                if id(cell._tc) == id(record.cell._tc):
                    continue
                neighbor = _normalize_space(cell.text)
                # When the adjacent cell is truly empty, ``_detect_empty_cells``
                # owns that fill area and uses this label as its context. Do not
                # create a second field in the label cell.
                if not neighbor:
                    return None
                if (
                    X_PLACEHOLDER_PATTERN.search(neighbor)
                    or UNDERSCORE_PLACEHOLDER_PATTERN.search(neighbor)
                    or ZERO_PHONE_PLACEHOLDER_PATTERN.search(neighbor)
                    or SAMPLE_EMAIL_PLACEHOLDER_PATTERN.search(neighbor)
                    or GENERIC_DROPDOWN_PATTERN.search(neighbor)
                ):
                    has_form_neighbor = True
                    break
        except (IndexError, AttributeError):
            pass
    if not has_form_neighbor:
        return None

    field_id = _unique_field_id(_make_field_id(label), known_ids)
    return _candidate(
        field_id=field_id,
        label=label,
        field_type=suggest_field_type(label),
        confidence=0.82,
        source="empty_cell",
        preview="Área vazia após o rótulo",
        location={
            "kind": "append_tag",
            "paragraph": record.ordinal,
        },
    )


def _detect_empty_cells(
    document: _Document,
    records: list[_ParagraphRecord],
    known_ids: set[str],
    reserved_ordinals: set[int],
) -> list[dict[str, Any]]:
    del document
    result: list[dict[str, Any]] = []
    by_cell: dict[int, list[_ParagraphRecord]] = defaultdict(list)
    for record in records:
        if record.cell is not None:
            by_cell[id(record.cell._tc)].append(record)

    visited_cells: set[int] = set()
    for record in records:
        if record.cell is None or record.table is None or record.row_index is None or record.cell_index is None:
            continue
        cell_key = id(record.cell._tc)
        if cell_key in visited_cells:
            continue
        visited_cells.add(cell_key)
        cell_records = by_cell.get(cell_key, [])
        if not cell_records or any(item.ordinal in reserved_ordinals for item in cell_records):
            continue
        if any(_normalize_space(item.text) for item in cell_records):
            continue
        if record.cell.tables:
            continue
        if record.cell_index <= 0:
            continue
        try:
            previous_cell = record.table.rows[record.row_index].cells[record.cell_index - 1]
        except (IndexError, AttributeError):
            continue
        previous_text = _normalize_space(previous_cell.text)
        label = previous_text.strip(" :：–—-")
        if not _is_reasonable_label(label):
            continue
        explicit_label = previous_text.rstrip().endswith((":", "："))
        ordinal = cell_records[0].ordinal
        field_id = _unique_field_id(_make_field_id(label), known_ids)
        known_ids.add(field_id)
        result.append(
            _candidate(
                field_id=field_id,
                label=label,
                field_type=suggest_field_type(label),
                confidence=0.84 if explicit_label else 0.68,
                source="empty_cell",
                preview="Célula vazia",
                location={
                    "kind": "empty_cell",
                    "paragraph": ordinal,
                },
                default_selected=explicit_label,
            )
        )
    return result


def _unique_row_cells(row) -> list[_Cell]:
    result: list[_Cell] = []
    seen: set[int] = set()
    for cell in row.cells:
        key = id(cell._tc)
        if key in seen:
            continue
        seen.add(key)
        result.append(cell)
    return result


def _looks_like_fill_area_text(value: str) -> bool:
    text = str(value or "")
    if not _normalize_space(text):
        return True
    return bool(
        PLACEHOLDER_PATTERN.search(text)
        or X_PLACEHOLDER_PATTERN.search(text)
        or UNDERSCORE_PLACEHOLDER_PATTERN.search(text)
        or ZERO_PHONE_PLACEHOLDER_PATTERN.search(text)
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
        if SAMPLE_EMAIL_PLACEHOLDER_PATTERN.fullmatch(compact):
            return "email"
    return suggest_field_type(header)


def _detected_placeholder_type(label: str, preview: str) -> str:
    normalized_label = _slug(label)
    compact = _normalize_space(preview)
    if "observacao_curta" in normalized_label:
        return "text"
    if re.fullmatch(r"_{2,}\s*/\s*_{2,}\s*/\s*_{2,}", compact):
        return "date"
    if ZERO_PHONE_PLACEHOLDER_PATTERN.fullmatch(compact):
        return "phone"
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
        for cell_index, cell in enumerate(row.cells):
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


def _paragraph_is_red(paragraph: Paragraph) -> bool:
    for run in paragraph.runs:
        color = run.font.color.rgb
        if color is None:
            continue
        try:
            red, green, blue = int(color[0]), int(color[1]), int(color[2])
        except Exception:
            text = str(color)
            if len(text) == 6:
                try:
                    red, green, blue = int(text[:2], 16), int(text[2:4], 16), int(text[4:], 16)
                except ValueError:
                    continue
            else:
                continue
        if red >= 150 and red > green * 1.35 and red > blue * 1.35:
            return True
    return False


def _contains_authoritative_marker(paragraph: Paragraph) -> bool:
    text = paragraph.text or ""
    if PLACEHOLDER_PATTERN.search(text):
        return True
    element = paragraph._p
    return bool(element.xpath(".//w:sdt | .//w:fldChar"))


def _tag_for_candidate(candidate: dict[str, Any]) -> str:
    field_id = str(candidate.get("field_id", "")).strip()
    field_type = str(candidate.get("type", "text")).strip().casefold()
    if not field_id:
        raise AutomaticDetectionError("Uma sugestão selecionada não possui ID de campo.")

    if field_type == "date":
        return f"{{{{date:{field_id}}}}}"
    if field_type == "checkbox":
        return f"{{{{checkbox:{field_id}}}}}"
    if field_type == "dropdown":
        options = compact_dropdown_options(candidate.get("options", []))
        if len(options) < 2:
            raise AutomaticDetectionError(
                f"A lista '{candidate.get('label', field_id)}' precisa de pelo menos duas opções."
            )
        encoded = []
        for option in options:
            if isinstance(option, dict):
                label = _safe_tag_option(option.get("label", ""))
                value = _safe_tag_option(option.get("value", ""))
                encoded.append(value if label == value else f"{label} => {value}")
            else:
                encoded.append(_safe_tag_option(option))
        prefix = "single_choice" if str(candidate.get("layout", "")) == "choice" else "dropdown"
        return "{{" + prefix + ":" + field_id + "|" + "|".join(encoded) + "}}"
    return f"{{{{{field_id}}}}}"


def _apply_paragraph_block(
    candidate: dict[str, Any],
    by_ordinal: dict[int, _ParagraphRecord],
) -> None:
    ordinals = [
        int(value)
        for value in candidate.get("location", {}).get("paragraphs", [])
    ]
    records = [by_ordinal.get(value) for value in ordinals]
    records = [record for record in records if record is not None]
    if not records:
        raise AutomaticDetectionError("Bloco de alternativas não encontrado no DOCX.")
    first = records[0].paragraph
    _replace_entire_paragraph(first, _tag_for_candidate(candidate))
    for record in records[1:]:
        _remove_paragraph(record.paragraph)


def _apply_repeatable_table(
    candidate: dict[str, Any],
    document: _Document,
) -> None:
    location = candidate.get("location", {}) or {}
    try:
        table_index = int(location.get("document_table_index", -1))
        template_row_index = int(location.get("template_row", -1))
        data_rows = sorted(
            {int(value) for value in location.get("data_rows", []) or []}
        )
    except (TypeError, ValueError):
        raise AutomaticDetectionError("Tabela repetível detectada com posição inválida.")

    if table_index < 0 or table_index >= len(document.tables):
        raise AutomaticDetectionError("A tabela repetível detectada não foi encontrada no DOCX.")
    table = document.tables[table_index]
    if template_row_index < 0 or template_row_index >= len(table.rows):
        raise AutomaticDetectionError("A linha modelo da tabela repetível não foi encontrada.")

    field_id = str(candidate.get("field_id", "")).strip()
    columns = [
        dict(column)
        for column in candidate.get("columns", []) or []
        if isinstance(column, dict)
    ]
    if not field_id or len(columns) < 2:
        raise AutomaticDetectionError("A tabela repetível detectada está incompleta.")

    row = table.rows[template_row_index]
    cells = _unique_row_cells(row)
    repeat_marker_written = False
    for column in columns:
        column_type = str(column.get("type", "text")).strip().casefold()
        column_id = str(column.get("id", "")).strip()
        if not column_id:
            continue
        if column_type == "auto_number":
            column_index = 0
            text = f"{{{{repeat:{field_id}}}}} {{{{row.number}}}}"
            repeat_marker_written = True
        else:
            try:
                column_index = int(column.get("column_index", -1))
            except (TypeError, ValueError):
                column_index = -1
            if column_index < 0:
                continue
            child_id = f"{field_id}.{column_id}"
            if column_type == "date":
                text = f"{{{{date:{child_id}}}}}"
            elif column_type == "checkbox":
                text = f"{{{{checkbox:{child_id}}}}}"
            else:
                text = f"{{{{{child_id}}}}}"

        if column_index >= len(cells):
            raise AutomaticDetectionError(
                "A estrutura de colunas da tabela repetível mudou após a análise."
            )
        _replace_cell_with_text(cells[column_index], text)

    if not repeat_marker_written:
        # The detector currently requires an auto-number column, but keep this
        # fallback so reviewed candidates remain robust if that rule evolves.
        first_editable = next(
            (
                column
                for column in columns
                if str(column.get("type", "")).casefold() != "auto_number"
            ),
            None,
        )
        if first_editable is None:
            raise AutomaticDetectionError("A tabela repetível não possui coluna editável.")
        column_index = int(first_editable.get("column_index", 0))
        paragraph = cells[column_index].paragraphs[0]
        paragraph.insert_paragraph_before(f"{{{{repeat:{field_id}}}}}")

    # Keep only the first detected data row as the Word model row. The DOCX
    # engine duplicates it according to the rows entered by the client.
    for row_index in sorted(data_rows, reverse=True):
        if row_index == template_row_index or row_index >= len(table.rows):
            continue
        table._tbl.remove(table.rows[row_index]._tr)


def _replace_cell_with_text(cell: _Cell, text: str) -> None:
    paragraphs = list(cell.paragraphs)
    if not paragraphs:
        cell.add_paragraph(text)
        return
    _replace_entire_paragraph(paragraphs[0], text)
    for paragraph in paragraphs[1:]:
        _remove_paragraph(paragraph)


def _apply_checkbox_group(
    candidate: dict[str, Any],
    by_ordinal: dict[int, _ParagraphRecord],
) -> None:
    ordinals = [
        int(value)
        for value in candidate.get("location", {}).get("paragraphs", [])
    ]
    fields = [dict(field) for field in candidate.get("fields", []) or []]
    if len(ordinals) != len(fields):
        raise AutomaticDetectionError("Grupo de caixas de seleção inconsistente.")
    for ordinal, field in zip(ordinals, fields):
        record = by_ordinal.get(ordinal)
        if record is None:
            raise AutomaticDetectionError("Opção de caixa de seleção não encontrada.")
        text = record.paragraph.text or ""
        match = CHECKBOX_LINE_PATTERN.match(text)
        if not match:
            raise AutomaticDetectionError("O texto de uma opção mudou após a análise.")
        replacement = f"{{{{checkbox:{field['id']}}}}} {match.group(1).strip()}"
        _replace_entire_paragraph(record.paragraph, replacement)


def _apply_inline_checkbox_group(
    candidate: dict[str, Any],
    by_ordinal: dict[int, _ParagraphRecord],
) -> None:
    location = candidate.get("location", {}) or {}
    ordinal = int(location.get("paragraph", -1))
    record = by_ordinal.get(ordinal)
    if record is None:
        raise AutomaticDetectionError("Grupo de caixas de seleção não encontrado.")
    fields = [dict(field) for field in candidate.get("fields", []) or []]
    spans = [
        tuple(int(value) for value in span)
        for span in location.get("checkbox_spans", []) or []
        if isinstance(span, (list, tuple)) and len(span) == 2
    ]
    if len(fields) != len(spans) or not fields:
        raise AutomaticDetectionError("Grupo de caixas de seleção inconsistente.")
    replacements = [
        (start, end, f"{{{{checkbox:{field['id']}}}}}")
        for (start, end), field in zip(spans, fields, strict=True)
    ]
    _replace_paragraph_spans(record.paragraph, replacements)


def _apply_multi_cell_checkbox_group(
    candidate: dict[str, Any],
    by_ordinal: dict[int, _ParagraphRecord],
) -> None:
    location = candidate.get("location", {}) or {}
    ordinals = [int(value) for value in location.get("paragraphs", []) or []]
    spans = [
        tuple(int(value) for value in span)
        for span in location.get("checkbox_spans", []) or []
        if isinstance(span, (list, tuple)) and len(span) == 2
    ]
    fields = [dict(field) for field in candidate.get("fields", []) or []]
    if not fields or len(fields) != len(ordinals) or len(fields) != len(spans):
        raise AutomaticDetectionError("Grupo de caixas de seleção entre células inconsistente.")

    for ordinal, span, field in zip(ordinals, spans, fields, strict=True):
        record = by_ordinal.get(ordinal)
        if record is None:
            raise AutomaticDetectionError("Opção de caixa de seleção não encontrada.")
        start, end = span
        text = record.paragraph.text or ""
        if start < 0 or end <= start or end > len(text):
            raise AutomaticDetectionError("A posição de uma opção mudou após a análise.")
        if not CHECKBOX_TOKEN_PATTERN.fullmatch(text[start:end]):
            raise AutomaticDetectionError("O marcador de uma opção mudou após a análise.")
        _replace_paragraph_spans(
            record.paragraph,
            [(start, end, f"{{{{checkbox:{field['id']}}}}}")],
        )


def _replace_entire_paragraph(paragraph: Paragraph, text: str) -> None:
    runs = list(paragraph.runs)
    if runs:
        runs[0].text = text
        for run in runs[1:]:
            run.text = ""
    else:
        paragraph.add_run(text)


def _append_tag_to_paragraph(paragraph: Paragraph, tag: str) -> None:
    current = paragraph.text or ""
    separator = "" if not current or current.endswith((" ", "\t")) else " "
    paragraph.add_run(separator + str(tag))


def _replace_paragraph_spans(
    paragraph: Paragraph,
    replacements: Iterable[tuple[int, int, str]],
) -> None:
    text_elements = _paragraph_text_elements(paragraph._p)
    original_parts = [element.text or "" for element in text_elements]
    original_text = "".join(original_parts)
    if not text_elements:
        raise AutomaticDetectionError("O trecho detectado não contém texto editável no DOCX.")

    spans: list[tuple[Any, int, int]] = []
    cursor = 0
    for element, text in zip(text_elements, original_parts, strict=True):
        end = cursor + len(text)
        spans.append((element, cursor, end))
        cursor = end

    for start, end, replacement in sorted(replacements, key=lambda item: item[0], reverse=True):
        if start < 0 or end <= start or end > len(original_text):
            raise AutomaticDetectionError("Posição de preenchimento inválida no DOCX.")
        start_index = _span_index_for_position(spans, start)
        end_index = _span_index_for_position(spans, end - 1)
        if start_index is None or end_index is None:
            raise AutomaticDetectionError("Não foi possível localizar o trecho detectado no XML do DOCX.")

        start_element, start_offset, _ = spans[start_index]
        end_element, end_offset, _ = spans[end_index]
        local_start = start - start_offset
        local_end = end - end_offset

        if start_index == end_index:
            current = start_element.text or ""
            _set_text_element_value(
                start_element,
                current[:local_start] + replacement + current[local_end:],
            )
            continue

        start_text = start_element.text or ""
        end_text = end_element.text or ""
        _set_text_element_value(start_element, start_text[:local_start] + replacement)
        for element, _node_start, _node_end in spans[start_index + 1 : end_index]:
            _set_text_element_value(element, "")
        _set_text_element_value(end_element, end_text[local_end:])


def _paragraph_text_elements(paragraph_element) -> list[Any]:
    elements: list[Any] = []

    def walk(element) -> None:
        for child in element.iterchildren():
            if child.tag == qn("w:p"):
                continue
            if child.tag in {qn("w:t"), qn("w:instrText")} :
                elements.append(child)
                continue
            walk(child)

    walk(paragraph_element)
    return elements


def _span_index_for_position(
    spans: list[tuple[Any, int, int]],
    position: int,
) -> int | None:
    for index, (_element, start, end) in enumerate(spans):
        if start <= position < end:
            return index
    return None


def _set_text_element_value(text_element, value: Any) -> None:
    normalized = str(value or "")
    text_element.text = normalized
    space_attribute = "{http://www.w3.org/XML/1998/namespace}space"
    if normalized.startswith(" ") or normalized.endswith(" "):
        text_element.set(space_attribute, "preserve")
    else:
        text_element.attrib.pop(space_attribute, None)


def _remove_paragraph(paragraph: Paragraph) -> None:
    element = paragraph._element
    parent = element.getparent()
    if parent is not None:
        parent.remove(element)
    paragraph._p = paragraph._element = None


def _validate_accepted_candidates(candidates: list[dict[str, Any]]) -> None:
    ids: list[str] = []
    for candidate in candidates:
        source = str(candidate.get("source", ""))
        if source == "checkbox_choice":
            for field in candidate.get("fields", []) or []:
                field_id = str(field.get("id", "")).strip()
                if not field_id:
                    raise AutomaticDetectionError("Uma opção detectada não possui ID.")
                ids.append(field_id)
            continue
        field_id = str(candidate.get("field_id", "")).strip()
        if not field_id:
            raise AutomaticDetectionError("Uma sugestão selecionada não possui ID.")
        ids.append(field_id)
        if str(candidate.get("source", "")) == "repeatable_table":
            columns = [
                dict(column)
                for column in candidate.get("columns", []) or []
                if isinstance(column, dict)
            ]
            column_ids = [str(column.get("id", "")).strip() for column in columns]
            if len(columns) < 2 or any(not column_id for column_id in column_ids):
                raise AutomaticDetectionError(
                    f"A tabela repetível '{candidate.get('label', field_id)}' não possui colunas válidas."
                )
            if len(set(column_ids)) != len(column_ids):
                raise AutomaticDetectionError(
                    f"A tabela repetível '{candidate.get('label', field_id)}' possui colunas repetidas."
                )
        if str(candidate.get("type", "")) == "dropdown":
            if len(compact_dropdown_options(candidate.get("options", []))) < 2:
                raise AutomaticDetectionError(
                    f"Configure pelo menos duas opções para '{candidate.get('label', field_id)}'."
                )
    duplicates = sorted({field_id for field_id in ids if ids.count(field_id) > 1})
    if duplicates:
        raise AutomaticDetectionError(
            "IDs repetidos nas sugestões: " + ", ".join(duplicates)
        )


def _safe_tag_option(value: Any) -> str:
    text = _normalize_space(value)
    if not text:
        raise AutomaticDetectionError("Uma opção detectada está vazia.")
    if "}}" in text:
        raise AutomaticDetectionError(
            "Uma opção contém '}}', sequência reservada para fechar tags."
        )
    return text.replace("|", " / ")


def _candidate_first_ordinal(candidate: dict[str, Any]) -> int:
    location = candidate.get("location", {}) or {}
    if "paragraph" in location:
        try:
            return int(location["paragraph"])
        except (TypeError, ValueError):
            return 10**9
    paragraphs = location.get("paragraphs", []) or []
    try:
        return min(int(value) for value in paragraphs)
    except (TypeError, ValueError):
        return 10**9


def _short_choice_label(value: str) -> str:
    cleaned = _clean_label(value)
    lowered = cleaned.casefold()
    rules = (
        (("não se aplica", "nao se aplica"), "Não se aplica"),
        (("não ser superior", "nao ser superior", "provável valor"), "Valor abaixo do limite"),
        (("demandas supervenientes", "art. 13"), "Demanda superveniente"),
        (("emergencial", "calamidade pública", "calamidade publica"), "Emergência ou calamidade"),
        (("sigilos", "sigilosa", "sigilosas"), "Informações sigilosas"),
        (("verificado posteriormente", "setor administrativo"), "Análise administrativa posterior"),
    )
    for tokens, label in rules:
        if any(token in lowered for token in tokens):
            return label
    first_sentence = re.split(r"(?<=[.!?;])\s+", cleaned, maxsplit=1)[0]
    if len(first_sentence) <= 88:
        return first_sentence
    return first_sentence[:85].rstrip(" ,;:-") + "…"


def _looks_like_page_header(value: str) -> bool:
    lowered = value.casefold()
    tokens = (
        "secretaria de estado",
        "governo da paraíba",
        "governo da paraiba",
        "sistema integrado de gerenciamento",
        "cep:",
    )
    return sum(token in lowered for token in tokens) >= 2


def _local_label(value: str) -> str:
    text = _normalize_space(value)
    match = LABEL_TAIL_PATTERN.search(text)
    if match:
        return _clean_label(match.group(1))
    # After another placeholder the remaining text normally starts with the
    # next local label, e.g. " Matrícula: ".
    text = text.strip(" |;–—-")
    if _is_reasonable_label(text):
        return _clean_label(text)
    return ""


def _instruction_label(text: str) -> str:
    cleaned = _normalize_space(text)
    cleaned = re.sub(
        r"^(?:informar|informe|descrever|descreva|detalhar|detalhe|"
        r"indicar|indique|justificar|justifique|preencher|preencha)\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    if len(cleaned) > 76:
        cleaned = cleaned[:73].rstrip(" ,;:-") + "…"
    return cleaned[:1].upper() + cleaned[1:] if cleaned else "Campo a preencher"


def _make_field_id(label: str) -> str:
    slug = _slug(label)
    slug = SECTION_NUMBER_PATTERN.sub("", slug)
    slug = slug.strip("._-")
    if not slug:
        slug = "campo"
    if slug[0].isdigit():
        slug = "campo_" + slug
    return f"auto.{slug[:72]}"


def _unique_field_id(base: str, used: set[str]) -> str:
    base = str(base or "auto.campo").strip()
    candidate = base
    index = 2
    while candidate in used:
        candidate = f"{base}_{index}"
        index += 1
    return candidate


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    normalized = "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    ).casefold()
    normalized = SECTION_NUMBER_PATTERN.sub("", normalized)
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized)
    return normalized.strip("_")


def _humanize_id(field_id: str) -> str:
    text = str(field_id).split(".")[-1].replace("_", " ").replace("-", " ")
    return text[:1].upper() + text[1:]


def _clean_label(value: str) -> str:
    text = _normalize_space(value)
    text = SECTION_NUMBER_PATTERN.sub("", text)
    text = text.strip(" :：–—-\t\r\n")
    return text


def _looks_like_section_label(value: str) -> bool:
    raw = _normalize_space(value)
    if not raw or len(raw) > 190:
        return False
    return bool(re.match(r"^\d+(?:\.\d+)*\.?\s+", raw)) or raw.endswith(":")


def _is_reasonable_label(value: str, *, maximum: int = 150) -> bool:
    text = _normalize_space(value).strip(" :：–—-")
    if len(text) < 2 or len(text) > maximum:
        return False
    if PLACEHOLDER_PATTERN.search(text):
        return False
    if CHOICE_SEPARATOR_PATTERN.match(text):
        return False
    return sum(character.isalpha() for character in text) >= 2


def _normalize_space(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()
