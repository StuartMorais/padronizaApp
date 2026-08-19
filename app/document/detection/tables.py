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

        # Region ownership: once this physical table segment is classified as a
        # repeatable table, its header and model rows belong to that high-level
        # interpretation.  Lower-level detectors must not reinterpret header
        # cells such as ``Unidade | Quantidade`` as ordinary label/value fields.
        #
        # Keep the ownership information explicit in the candidate as a second
        # safety layer: post-processing can suppress overlapping interpretations
        # even when a future detector runs before the reservation pass.
        header_row = 0
        owned_rows = [header_row, *data_rows]
        data_ordinals = sorted(
            record.ordinal
            for record in table_records
            if record.row_index in data_rows
        )
        owned_ordinals = sorted(
            record.ordinal
            for record in table_records
            if record.row_index in owned_rows
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
                    "table_index": first_record.table_index,
                    "header_row": header_row,
                    "template_row": data_rows[0],
                    "data_rows": data_rows,
                    "owned_rows": owned_rows,
                    "data_paragraphs": data_ordinals,
                    "owned_paragraphs": owned_ordinals,
                    # ``paragraphs`` is the generic reservation contract used
                    # by the rest of the detector. Include the complete owned
                    # region, not only the rows that will receive tags.
                    "paragraphs": owned_ordinals,
                },
            )
        )
        result[-1]["region_owner"] = "repeatable_table"
        result[-1]["columns"] = columns
        if section_title:
            result[-1]["section"] = section_title.rstrip(":").strip()
        result[-1]["selected"] = True

    return result


def _detect_editable_sheet_tables(
    document: _Document,
    records: list[_ParagraphRecord],
    known_ids: set[str],
    reserved_ordinals: set[int],
) -> list[dict[str, Any]]:
    """Detect a spreadsheet header that has no editable data row yet.

    A common institutional Word pattern is a multi-column header followed by a
    merged narrative row, for example::

        Item | Quantidade | Unidade | Especificação | Valor
        [ merged explanatory / prefilled paragraph                  ]

    The header describes a real worksheet even though the source document does
    not provide numbered model rows.  Earlier detector versions preserved the
    visual header but offered no editable cells.  This detector creates a
    repeatable-table interpretation with a *synthetic* model row inserted
    between the header and the merged note when the approved suggestions are
    applied.  All header columns are editable; the merged note remains available
    to the normal prefilled-text detector as a separate full-width field.

    The rule is intentionally narrow: at least three short header cells are
    required and the immediately following row must be one merged/full-width
    cell containing either substantial prose or an empty/fill area.  This keeps
    ordinary label/value form grids out of the spreadsheet path.
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
        if len(table.rows) < 2:
            continue

        for header_row_index in range(0, len(table.rows) - 1):
            header_cells = _unique_row_cells(table.rows[header_row_index])
            if len(header_cells) < 3:
                continue
            headers = [_clean_label(cell.text) for cell in header_cells]
            if sum(_is_reasonable_label(value, maximum=100) for value in headers) < 3:
                continue
            if any(len(value) > 120 for value in headers if value):
                continue

            next_row_index = header_row_index + 1
            next_cells = _unique_row_cells(table.rows[next_row_index])
            if len(next_cells) != 1:
                continue
            merged_text = _normalize_space(next_cells[0].text)
            if merged_text:
                # Short merged rows are often totals, signatures, or section
                # separators.  Long prose (or a visual fill area) is the sheet
                # + merged-note pattern we want.
                if len(merged_text) < 55 and not _looks_like_fill_area_text(merged_text):
                    continue

            header_records = [
                record
                for record in table_records
                if record.row_index == header_row_index
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
            section_title = _nearest_section_title(
                first_record,
                records,
                preserve_number=True,
            )
            label = _clean_label(section_title) if section_title else "Itens da planilha"
            field_id = _unique_field_id(_make_field_id(label), known_ids)

            used_column_ids: set[str] = set()
            columns: list[dict[str, Any]] = []
            for column_index, header in enumerate(headers):
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
                    # ``Item`` in user-authored spreadsheets is not assumed to
                    # be an automatic row number; the user can edit it.
                    column_type = "text"
                elif any(token in header_key for token in ("descricao", "especificacao", "detalhamento")):
                    column_type = "multiline"
                elif header_key in {"valor", "preco", "preço", "custo", "montante"} or header_key.endswith("_valor"):
                    column_type = "currency"
                else:
                    column_type = _repeatable_column_type(display, [])

                columns.append(
                    {
                        "id": column_id,
                        "label": display,
                        "type": column_type,
                        "required": False,
                        "column_index": column_index,
                    }
                )

            if len(columns) < 3:
                continue

            owned_ordinals = sorted(record.ordinal for record in header_records)
            candidate = _candidate(
                field_id=field_id,
                label=label,
                field_type="repeatable_table",
                confidence=0.93,
                source="repeatable_table",
                preview=" | ".join(headers) + " — planilha editável detectada",
                location={
                    "kind": "repeatable_table",
                    "document_table_index": top_level_index[table_key],
                    "table_index": first_record.table_index,
                    "header_row": header_row_index,
                    # No source model row exists. _apply_repeatable_table will
                    # create one immediately before the merged narrative row.
                    "template_row": -1,
                    "synthetic_template_row": True,
                    "insert_before_row": next_row_index,
                    "data_rows": [],
                    "owned_rows": [header_row_index],
                    "owned_paragraphs": owned_ordinals,
                    "paragraphs": owned_ordinals,
                },
            )
            candidate["region_owner"] = "repeatable_table"
            candidate["sheet_generated_model_row"] = True
            candidate["columns"] = columns
            candidate["minimum_rows"] = 1
            candidate["numbering_padding"] = 2
            candidate["selected"] = True
            if section_title:
                candidate["section"] = section_title.rstrip(":").strip()
            result.append(candidate)
            # A single Word table should have one primary sheet header for this
            # pattern.  Stop after the first convincing match.
            break

    return result
