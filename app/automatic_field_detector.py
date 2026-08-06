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
UNDERSCORE_PLACEHOLDER_PATTERN = re.compile(r"_{4,}")
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
SECTION_NUMBER_PATTERN = re.compile(r"^\s*\d+(?:\.\d+)*\.?\s*")
LABEL_TAIL_PATTERN = re.compile(r"([^:;|]{2,120})\s*[:：]\s*$")


_SOURCE_LABELS = {
    "long_choice": "Alternativas separadas por OU",
    "inline_placeholder": "Texto de preenchimento (XXXX ou sublinhado)",
    "instruction": "Texto instrucional substituível",
    "empty_cell": "Célula vazia ao lado de um rótulo",
    "dropdown_prompt": "Indicação 'Escolher um item'",
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

        if GENERIC_DROPDOWN_PATTERN.match(text):
            label = _context_label_for_record(record, records)
            field_id = _unique_field_id(
                _make_field_id(label or "opcao"),
                known_ids,
            )
            known_ids.add(field_id)
            candidates.append(
                _candidate(
                    field_id=field_id,
                    label=label or "Selecione uma opção",
                    field_type="dropdown",
                    confidence=0.70,
                    source="dropdown_prompt",
                    preview=text,
                    location={
                        "kind": "paragraph",
                        "paragraph": record.ordinal,
                    },
                    options=[],
                    default_selected=False,
                    requires_configuration=True,
                )
            )
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
        if kind == "paragraph_block":
            _apply_paragraph_block(candidate, by_ordinal)
        elif kind == "checkbox_group":
            _apply_checkbox_group(candidate, by_ordinal)

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


def _detect_checkbox_choice_groups(
    document: _Document,
    records: list[_ParagraphRecord],
    known_ids: set[str],
    reserved_ordinals: set[int],
) -> list[dict[str, Any]]:
    del document
    by_cell: dict[int, list[_ParagraphRecord]] = defaultdict(list)
    for record in records:
        if record.cell is not None and record.ordinal not in reserved_ordinals:
            by_cell[id(record.cell._tc)].append(record)

    result: list[dict[str, Any]] = []
    for cell_records in by_cell.values():
        matched: list[tuple[_ParagraphRecord, re.Match[str]]] = []
        for record in cell_records:
            if _contains_authoritative_marker(record.paragraph):
                continue
            match = CHECKBOX_LINE_PATTERN.match(record.text or "")
            if match:
                matched.append((record, match))
        if len(matched) < 2 or len(matched) > 8:
            continue

        label = _context_label_for_record(matched[0][0], records)
        group_id = _unique_field_id(_make_field_id(label or "escolha"), known_ids)
        ui_group = f"auto_checkbox_{group_id}"
        fields: list[dict[str, Any]] = []
        paragraphs: list[int] = []
        for index, (record, match) in enumerate(matched, start=1):
            option_text = _normalize_space(match.group(1))
            option_id = _unique_field_id(
                f"{group_id}.{_slug(option_text)[:34] or f'opcao_{index}'}",
                known_ids,
            )
            known_ids.add(option_id)
            fields.append(
                {
                    "id": option_id,
                    "label": option_text,
                    "type": "checkbox",
                    "required": False,
                    "layout": "choice",
                    "layout_group": ui_group,
                    "layout_group_label": label or "Escolha uma opção",
                    "group": ui_group,
                    "selection": "single",
                    "choice_required": True,
                }
            )
            paragraphs.append(record.ordinal)

        candidate = {
            "field_id": group_id,
            "label": label or "Escolha uma opção",
            "type": "checkbox_group",
            "confidence": 0.88,
            "source": "checkbox_choice",
            "preview": " | ".join(field["label"] for field in fields),
            "location": {
                "kind": "checkbox_group",
                "paragraphs": paragraphs,
            },
            "fields": fields,
            "selected": True,
            "requires_configuration": False,
        }
        result.append(candidate)
    return result


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
    matches.sort(key=lambda match: match.start())
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
        field_type = suggest_field_type(label or field_id)
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
        label = _normalize_space(previous_cell.text).strip(" :：–—-")
        if not _is_reasonable_label(label):
            continue
        ordinal = cell_records[0].ordinal
        field_id = _unique_field_id(_make_field_id(label), known_ids)
        known_ids.add(field_id)
        result.append(
            _candidate(
                field_id=field_id,
                label=label,
                field_type=suggest_field_type(label),
                confidence=0.68,
                source="empty_cell",
                preview="Célula vazia",
                location={
                    "kind": "empty_cell",
                    "paragraph": ordinal,
                },
                default_selected=False,
            )
        )
    return result


def _context_label_for_record(
    record: _ParagraphRecord,
    records: list[_ParagraphRecord],
) -> str:
    text = record.text or ""
    if ":" in text:
        before = text.split(":", 1)[0]
        if _is_reasonable_label(before):
            return _clean_label(before)

    # Same table: prefer the previous cell in the same row.
    if record.table is not None and record.row_index is not None and record.cell_index is not None:
        try:
            row = record.table.rows[record.row_index]
            if record.cell_index > 0:
                previous = _normalize_space(row.cells[record.cell_index - 1].text)
                if _is_reasonable_label(previous):
                    return _clean_label(previous)
        except (IndexError, AttributeError):
            pass

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


def _replace_entire_paragraph(paragraph: Paragraph, text: str) -> None:
    runs = list(paragraph.runs)
    if runs:
        runs[0].text = text
        for run in runs[1:]:
            run.text = ""
    else:
        paragraph.add_run(text)


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
