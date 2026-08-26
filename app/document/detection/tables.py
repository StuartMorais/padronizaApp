from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from docx.document import Document as _Document
from docx.table import Table

from app.document.detection.candidates import _candidate
from app.document.detection.context_helpers import (
    _contains_authoritative_marker, _context_label_for_record,
    _looks_like_fill_area_text, _nearest_section_title, _repeatable_column_type,
)
from app.document.detection.identifiers import (
    _clean_label, _is_reasonable_label, _looks_like_page_header, _make_field_id,
    _normalize_space, _short_choice_label, _slug, _unique_field_id,
)
from app.document.detection.models import ParagraphRecord as _ParagraphRecord
from app.document.detection.patterns import CHOICE_SEPARATOR_PATTERN
from app.document.detection.word_helpers import _unique_row_cells
from app.document.detection.table_structure import TableKind, analyze_word_table, row_grid_cells, row_values_by_grid

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
    """Detect real repeated-record Word tables before cell-level heuristics.

    Structural analysis owns this decision.  In particular, a merged section
    title + multi-column header + one numbered model row + an ellipsis row is
    treated as a repeatable table even though older versions required two
    numbered rows.  This preserves the table relationship in the filling UI.
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
        structure = analyze_word_table(table)
        if structure.kind is not TableKind.REPEATABLE or structure.header_row is None:
            continue

        owned_rows = structure.owned_rows
        owned_records = [
            record for record in table_records
            if record.row_index in owned_rows
        ]
        if any(
            record.ordinal in reserved_ordinals
            or _contains_authoritative_marker(record.paragraph)
            for record in owned_records
        ):
            continue

        numeric_rows = [
            row_index
            for row_index in structure.data_rows
            if re.fullmatch(
                r"0*\d{1,4}",
                _normalize_space(row_values_by_grid(
                    row_grid_cells(table.rows[row_index]),
                    structure.total_columns,
                )[0]),
            )
        ]
        if not numeric_rows:
            continue

        first_record = min(
            (record for record in table_records if record.row_index == structure.header_row),
            key=lambda item: item.ordinal,
            default=min(table_records, key=lambda item: item.ordinal),
        )
        section_title = structure.title or _nearest_section_title(
            first_record, records, preserve_number=True
        )
        label = _clean_label(section_title) if section_title else "Itens da tabela"
        field_id = _unique_field_id(_make_field_id(label), known_ids)

        columns: list[dict[str, Any]] = []
        used_column_ids: set[str] = set()
        for column_index, header in enumerate(structure.header_labels):
            display = _clean_label(header) or f"Coluna {column_index + 1}"
            header_key = _slug(display)
            if column_index == 0 and header_key in {"n", "no", "numero", "item", "n_item"}:
                columns.append(
                    {
                        "id": "item",
                        "label": display or "Item",
                        "type": "auto_number",
                        "required": False,
                    }
                )
                used_column_ids.add("item")
                continue

            values = [
                _normalize_space(
                    row_values_by_grid(
                        row_grid_cells(table.rows[row_index]),
                        structure.total_columns,
                    )[column_index]
                )
                for row_index in numeric_rows
            ]
            column_id = _slug(display) or f"coluna_{column_index + 1}"
            base_column_id = column_id
            suffix = 2
            while column_id in used_column_ids:
                column_id = f"{base_column_id}_{suffix}"
                suffix += 1
            used_column_ids.add(column_id)

            options = structure.header_options.get(column_index, [])
            column_type = (
                "dropdown"
                if len(options) >= 2
                else _repeatable_column_type(display, values)
            )
            optional_header = any(
                token in display.casefold()
                for token in ("se for o caso", "opcional", "quando aplicável", "quando aplicavel")
            )
            column: dict[str, Any] = {
                "id": column_id,
                "label": display,
                "type": column_type,
                "required": not optional_header and column_type != "checkbox",
                "column_index": column_index,
            }
            if options:
                column["options"] = options
            group_label = (
                structure.header_groups[column_index]
                if column_index < len(structure.header_groups)
                else ""
            )
            if group_label:
                column["group_label"] = group_label
            columns.append(column)

        if len(columns) < 2:
            continue

        model_rows = sorted(set(numeric_rows + structure.continuation_rows))
        owned_ordinals = sorted(record.ordinal for record in owned_records)
        data_ordinals = sorted(
            record.ordinal
            for record in table_records
            if record.row_index in model_rows
        )
        candidate = _candidate(
            field_id=field_id,
            label=label,
            field_type="repeatable_table",
            confidence=structure.confidence,
            source="repeatable_table",
            preview=" | ".join(structure.header_labels)
            + f" — {len(numeric_rows)} linha(s) modelo + {len(structure.continuation_rows)} continuação(ões)",
            location={
                "kind": "repeatable_table",
                "document_table_index": top_level_index[table_key],
                "table_index": first_record.table_index,
                "header_row": structure.header_row,
                "template_row": numeric_rows[0],
                # All model/ellipsis rows except the first template row are
                # removed when the reviewed suggestion is materialized.
                "data_rows": model_rows,
                "owned_rows": owned_rows,
                "data_paragraphs": data_ordinals,
                "owned_paragraphs": owned_ordinals,
                "paragraphs": owned_ordinals,
            },
        )
        candidate["region_owner"] = "repeatable_table"
        candidate["structure_kind"] = structure.kind.value
        candidate["structure_confidence"] = structure.confidence
        candidate["structure_reasons"] = list(structure.reasons)
        candidate["columns"] = columns
        candidate["minimum_rows"] = 1
        candidate["numbering_padding"] = max(2, len(str(len(model_rows) or 1)))
        if section_title:
            candidate["section"] = section_title.rstrip(":").strip()
        candidate["selected"] = True
        result.append(candidate)

    return result


def _detect_editable_sheet_tables(
    document: _Document,
    records: list[_ParagraphRecord],
    known_ids: set[str],
    reserved_ordinals: set[int],
) -> list[dict[str, Any]]:
    """Detect a spreadsheet header that has no editable data row yet.

    Only a table classified structurally as ``EDITABLE_SHEET`` is eligible.
    This prevents a data row deep inside a fixed matrix from being mistaken for
    a new spreadsheet header merely because the following row is merged.
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
        structure = analyze_word_table(table)
        if structure.kind is not TableKind.EDITABLE_SHEET or structure.header_row is None:
            continue

        header_records = [
            record for record in table_records
            if record.row_index == structure.header_row
        ]
        if not header_records:
            continue
        if any(
            record.ordinal in reserved_ordinals
            or _contains_authoritative_marker(record.paragraph)
            for record in header_records
        ):
            continue

        first_record = min(header_records, key=lambda item: item.ordinal)
        section_title = structure.title or _nearest_section_title(
            first_record,
            records,
            preserve_number=True,
        )
        label = _clean_label(section_title) if section_title else "Itens da planilha"
        field_id = _unique_field_id(_make_field_id(label), known_ids)

        used_column_ids: set[str] = set()
        columns: list[dict[str, Any]] = []
        for column_index, header in enumerate(structure.header_labels):
            display = header or f"Coluna {column_index + 1}"
            column_id = _slug(display) or f"coluna_{column_index + 1}"
            base_column_id = column_id
            suffix = 2
            while column_id in used_column_ids:
                column_id = f"{base_column_id}_{suffix}"
                suffix += 1
            used_column_ids.add(column_id)

            header_key = _slug(display)
            if header_key in {"item", "codigo", "código"}:
                column_type = "text"
            elif any(token in header_key for token in ("descricao", "especificacao", "detalhamento")):
                column_type = "multiline"
            elif header_key in {"valor", "preco", "preço", "custo", "montante"} or header_key.endswith("_valor"):
                column_type = "currency"
            else:
                column_type = _repeatable_column_type(display, [])

            column: dict[str, Any] = {
                "id": column_id,
                "label": display,
                "type": column_type,
                "required": False,
                "column_index": column_index,
            }
            options = structure.header_options.get(column_index, [])
            if options:
                column["type"] = "dropdown"
                column["options"] = options
            columns.append(column)

        if len(columns) < 3:
            continue

        insert_before_row = structure.header_row + 1
        owned_ordinals = sorted(record.ordinal for record in header_records)
        candidate = _candidate(
            field_id=field_id,
            label=label,
            field_type="repeatable_table",
            confidence=structure.confidence,
            source="repeatable_table",
            preview=" | ".join(structure.header_labels) + " — planilha editável detectada",
            location={
                "kind": "repeatable_table",
                "document_table_index": top_level_index[table_key],
                "table_index": first_record.table_index,
                "header_row": structure.header_row,
                "template_row": -1,
                "synthetic_template_row": True,
                "insert_before_row": insert_before_row,
                "data_rows": [],
                "owned_rows": [structure.header_row],
                "owned_paragraphs": owned_ordinals,
                "paragraphs": owned_ordinals,
            },
        )
        candidate["region_owner"] = "repeatable_table"
        candidate["sheet_generated_model_row"] = True
        candidate["structure_kind"] = structure.kind.value
        candidate["structure_confidence"] = structure.confidence
        candidate["structure_reasons"] = list(structure.reasons)
        candidate["columns"] = columns
        candidate["minimum_rows"] = 1
        candidate["numbering_padding"] = 2
        candidate["selected"] = True
        if section_title:
            candidate["section"] = section_title.rstrip(":").strip()
        result.append(candidate)

    return result

