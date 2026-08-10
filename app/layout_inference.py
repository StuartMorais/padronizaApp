from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from docx import Document
from docx.document import Document as _Document
from docx.oxml.ns import qn
from docx.table import Table, _Cell, _Row
from docx.text.paragraph import Paragraph


PLACEHOLDER_PATTERN = re.compile(r"\{\{([^{}]+)\}\}")
HEADING_NUMBER_PATTERN = re.compile(r"^\s*\d+(?:\.\d+)*[.)]?\s+")
EXCLUSIVE_PAIR_WORDS = (
    ("imediat", "parcel"),
    ("integral", "parcial"),
    ("sim", "não"),
    ("sim", "nao"),
    ("presencial", "remot"),
    ("aprov", "reprov"),
    ("aceit", "recus"),
    ("com", "sem"),
)


@dataclass(frozen=True)
class _VisualCell:
    """One physical Word cell placed on the visual table grid."""

    cell: _Cell
    start: int
    span: int
    text: str
    vertical_continuation: bool = False


@dataclass
class _TableRowInfo:
    index: int
    cells: list[_VisualCell]
    matches: list[tuple[_VisualCell, str, str, str]]
    plain_cells: list[_VisualCell]
    text: str


# Public API -----------------------------------------------------------------
def infer_docx_layout(docx_path: Path) -> dict[str, dict[str, Any]]:
    """Infer conservative form-layout metadata from a DOCX structure.

    Word uses tables both for real records and for ordinary form alignment. The
    inference deliberately distinguishes those cases:

    * ``table`` is reserved for genuine row/column data tables;
    * ``form_grid`` preserves the visual rows, merged cells and local labels of
      form-like tables.
    """

    document = Document(str(Path(docx_path)))
    metadata: dict[str, dict[str, Any]] = {}
    current_section = ""
    table_index = 0

    for block in _iter_block_items(document):
        if isinstance(block, Paragraph):
            section = _paragraph_section_title(block)
            if section:
                current_section = section

            matches = _placeholder_matches(block.text)
            if not matches:
                continue

            for field_id, _field_type, label in matches:
                values = metadata.setdefault(field_id, {})
                if current_section:
                    values.setdefault("section", current_section)
                if label:
                    values.setdefault("detected_label", label)

            checkbox_matches = [item for item in matches if item[1] == "checkbox"]
            if len(checkbox_matches) >= 2 and _looks_like_exclusive_choice(
                [item[2] or item[0] for item in checkbox_matches]
            ):
                group_id = f"choice_paragraph_{len(metadata)}"
                group_label = _choice_group_label(
                    [item[2] or item[0] for item in checkbox_matches]
                )
                for field_id, _field_type, label in checkbox_matches:
                    values = metadata.setdefault(field_id, {})
                    values.update(
                        {
                            "layout": "choice",
                            "layout_group": group_id,
                            "layout_group_label": group_label,
                            "group": group_id,
                            "selection": "single",
                            "choice_required": True,
                        }
                    )
                    if label:
                        values.setdefault("detected_label", label)
            continue

        if isinstance(block, Table):
            table_index += 1
            current_section = _analyze_table(
                block,
                table_index=table_index,
                inherited_section=current_section,
                metadata=metadata,
            ) or current_section

    return metadata


def apply_layout_metadata(
    fields: list[dict[str, Any]],
    inferred: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge inferred metadata without overwriting deliberate user choices."""

    result: list[dict[str, Any]] = []
    for source in normalize_form_layout(fields):
        field = dict(source)
        field_id = str(field.get("id", "")).strip()
        suggestion = inferred.get(field_id, {})

        detected_label = str(suggestion.get("detected_label", "")).strip()
        current_label = str(field.get("label", "")).strip()
        label_source = str(field.get("label_source", "")).strip()
        if detected_label and (
            not current_label
            or label_source in {"", "identifier", "document_context", "automatic"}
        ):
            field["label"] = detected_label
            field["label_source"] = "document_context"

        inferred_section = str(suggestion.get("section", "")).strip()
        current_section = str(field.get("section", "")).strip()
        if inferred_section and (
            not current_section
            or current_section in {"Dados do documento", "Informações adicionais"}
        ):
            field["section"] = inferred_section
            field["section_source"] = "document_context"

        current_layout = str(field.get("layout", "")).strip().casefold()
        current_layout_group = str(field.get("layout_group", "")).strip()
        inferred_layout = str(suggestion.get("layout", "")).strip().casefold()

        # Automatic checkbox-choice detection initially renders a group as a
        # standalone choice card.  When the DOCX structure later proves that
        # the same options live inside a real table row (for example
        # ``Item | Situação | Observação``), keep the exclusivity semantics but
        # re-home the controls into the inferred table cell.  Explicit/manual
        # layout choices remain untouched.
        automatic_embedded_choice = (
            str(field.get("detection_source", "")).strip().casefold() == "automatic"
            and str(field.get("type", "")).strip().casefold() == "checkbox"
            and current_layout == "choice"
            and inferred_layout in {"table", "form_grid"}
            and str(suggestion.get("layout_group", "")).strip()
            and str(suggestion.get("layout_row", "")).strip()
        )
        if automatic_embedded_choice:
            original_choice_group = str(
                field.get("group") or current_layout_group
            ).strip()
            original_choice_label = str(
                field.get("layout_group_label", "")
            ).strip()
            for stale_key in (
                "layout",
                "layout_group",
                "layout_group_label",
                "layout_row",
                "layout_row_label",
                "layout_row_header_label",
                "layout_column",
                "layout_column_index",
                "layout_column_span",
                "layout_grid_columns",
                "layout_order",
                "layout_static_rows",
                "layout_row_static_cells",
                "layout_position_locked",
            ):
                field.pop(stale_key, None)
            if original_choice_group:
                field["group"] = original_choice_group
            if original_choice_label:
                field["choice_group_label"] = original_choice_label
            field["selection"] = "single"
            field["choice_required"] = bool(field.get("choice_required", True))
            field["compact_choice"] = True
            current_layout = ""
            current_layout_group = ""
        automatic_layout_migration = (
            current_layout in {"table", "form_grid"}
            and inferred_layout in {"table", "form_grid"}
            and current_layout != inferred_layout
            and current_layout_group.startswith("doc_table_")
        )
        if automatic_layout_migration:
            for stale_key in (
                "layout",
                "layout_group",
                "layout_group_label",
                "layout_row",
                "layout_row_label",
                "layout_column",
                "layout_column_index",
                "layout_column_span",
                "layout_grid_columns",
                "layout_order",
                "layout_static_rows",
                "layout_row_static_cells",
                "layout_position_locked",
            ):
                field.pop(stale_key, None)

        for key in (
            "layout",
            "layout_group",
            "layout_group_label",
            "layout_row",
            "layout_row_label",
            "layout_row_header_label",
            "layout_column",
            "layout_column_index",
            "layout_column_span",
            "layout_grid_columns",
            "layout_order",
            "layout_static_rows",
            "layout_row_static_cells",
            "layout_position_locked",
            "group",
            "selection",
            "choice_required",
        ):
            value = suggestion.get(key)
            if value in (None, "", []):
                continue
            current = field.get(key)
            if current in (None, "", "auto", []):
                field[key] = value

        result.append(field)
    return normalize_form_layout(result)


def normalize_form_layout(
    fields: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return defensive layout metadata suitable for rendering and saving.

    Word tables often contain invisible grid columns or an empty cell before a
    single input. Reproducing that geometry literally leaves an isolated field
    on the right side of the form. A row with one editable field and no
    same-row static content is therefore expanded across the available grid.

    Set ``layout_position_locked`` on a field when an exact partial-row
    placement is intentional.
    """

    result = [dict(source) for source in fields if isinstance(source, dict)]
    groups: OrderedDict[tuple[str, str], list[dict[str, Any]]] = OrderedDict()
    for field in result:
        if str(field.get("layout", "auto")).strip().casefold() != "form_grid":
            continue
        group = str(field.get("layout_group", "")).strip()
        if not group:
            continue
        section = str(field.get("section", "")).strip()
        groups.setdefault((section, group), []).append(field)

    for _group_key, group_fields in groups.items():
        grid_columns = max(
            [_safe_layout_int(field.get("layout_grid_columns"), 1) for field in group_fields]
            + [1]
        )
        grid_columns = max(1, min(grid_columns, 12))

        rows: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
        row_static: dict[str, list[dict[str, Any]]] = {}
        for index, field in enumerate(group_fields):
            row_key = str(field.get("layout_row", f"row_{index}")).strip() or f"row_{index}"
            field["layout_row"] = row_key
            field["layout_grid_columns"] = grid_columns
            rows.setdefault(row_key, []).append(field)
            for cell in field.get("layout_row_static_cells", []) or []:
                if not isinstance(cell, dict):
                    continue
                cell_row = str(cell.get("layout_row", row_key)).strip() or row_key
                row_static.setdefault(cell_row, []).append(cell)

        for row_key, row_fields in rows.items():
            for field in row_fields:
                start = _safe_layout_int(field.get("layout_column_index"), 0)
                span = _safe_layout_int(field.get("layout_column_span"), 1)
                start = max(0, min(start, grid_columns - 1))
                span = max(1, min(span, grid_columns - start))
                field["layout_column_index"] = start
                field["layout_column_span"] = span

            # A very common Word-form pattern uses one cell only as the label
            # and the immediately adjacent cell as the fill area.  Once the
            # empty cell receives a tag, rendering the label cell as separate
            # static content creates the ugly "label card + input" result.
            # Absorb that label cell into the field's visual span instead.
            #
            # Also discard stale static prompt metadata that occupies the same
            # physical cell as an editable field (for example
            # ``Tipo: Escolher um item`` after that prompt was converted to a
            # dropdown).  This keeps old automatically-generated model data
            # from producing false overlap errors.
            static_cells = [
                dict(cell)
                for cell in row_static.get(row_key, [])
                if isinstance(cell, dict) and str(cell.get("text", "")).strip()
            ]
            suppressed_static_keys: set[tuple[int, int, str]] = set()

            for static_cell in static_cells:
                static_start = _safe_layout_int(static_cell.get("layout_column_index"), 0)
                static_span = _safe_layout_int(static_cell.get("layout_column_span"), 1)
                static_end = static_start + max(1, static_span)
                static_text = str(static_cell.get("text", "")).strip()
                static_key = (static_start, max(1, static_span), static_text)

                for field in row_fields:
                    field_start = _safe_layout_int(field.get("layout_column_index"), 0)
                    field_span = _safe_layout_int(field.get("layout_column_span"), 1)
                    field_end = field_start + max(1, field_span)

                    if (
                        static_end == field_start
                        and _static_cell_describes_field(static_text, field)
                        and not bool(field.get("layout_position_locked", False))
                    ):
                        field["layout_column_index"] = static_start
                        field["layout_column_span"] = min(
                            grid_columns - static_start,
                            max(1, static_span) + max(1, field_span),
                        )
                        suppressed_static_keys.add(static_key)
                        break

                    overlaps = static_start < field_end and field_start < static_end
                    if overlaps and _static_cell_describes_field(static_text, field):
                        suppressed_static_keys.add(static_key)
                        break

            if suppressed_static_keys:
                for field in row_fields:
                    cleaned_cells: list[dict[str, Any]] = []
                    for cell in field.get("layout_row_static_cells", []) or []:
                        if not isinstance(cell, dict):
                            continue
                        key = (
                            _safe_layout_int(cell.get("layout_column_index"), 0),
                            max(1, _safe_layout_int(cell.get("layout_column_span"), 1)),
                            str(cell.get("text", "")).strip(),
                        )
                        if key not in suppressed_static_keys:
                            cleaned_cells.append(dict(cell))
                    if cleaned_cells:
                        field["layout_row_static_cells"] = cleaned_cells
                    else:
                        field.pop("layout_row_static_cells", None)

            same_row_static = [
                cell
                for cell in static_cells
                if (
                    _safe_layout_int(cell.get("layout_column_index"), 0),
                    max(1, _safe_layout_int(cell.get("layout_column_span"), 1)),
                    str(cell.get("text", "")).strip(),
                )
                not in suppressed_static_keys
            ]
            if (
                len(row_fields) == 1
                and not same_row_static
                and not bool(row_fields[0].get("layout_position_locked", False))
            ):
                # One field with no peer/context should never float in a
                # leftover Word grid column. This also fixes long text areas.
                row_fields[0]["layout_column_index"] = 0
                row_fields[0]["layout_column_span"] = grid_columns
                row_fields[0]["full_width"] = True

    return result


def _static_cell_describes_field(text: str, field: dict[str, Any]) -> bool:
    """Return True when static text is really the field's own label/prompt."""

    static_text = " ".join(str(text or "").split()).strip()
    label = " ".join(str(field.get("label", "") or "").split()).strip()
    if not static_text or not label:
        return False

    static_folded = static_text.casefold().rstrip(" :：–—-")
    label_folded = label.casefold().rstrip(" :：–—-")
    if static_folded == label_folded:
        return True

    prefix = label_folded + ":"
    compact_static = static_text.casefold().replace("：", ":").strip()
    if not compact_static.startswith(prefix):
        return False
    tail = compact_static[len(prefix) :].strip().rstrip(".")
    return bool(
        re.fullmatch(
            r"(?:escolher|selecione|selecionar)\s+(?:um|uma)\s+(?:item|op[cç][aã]o)",
            tail,
            re.IGNORECASE,
        )
    )


def layout_quality_issues(fields: Iterable[dict[str, Any]]) -> list[str]:
    """Return hard layout problems that should block template saving."""

    issues: list[str] = []
    source_fields = [dict(field) for field in fields if isinstance(field, dict)]
    groups: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
    for field in source_fields:
        if str(field.get("layout", "auto")).strip().casefold() != "form_grid":
            continue
        field_id = str(field.get("id", "")).strip() or "campo sem ID"
        group = str(field.get("layout_group", "")).strip()
        row = str(field.get("layout_row", "")).strip()
        if not group:
            issues.append(f"{field_id}: Grade do documento sem grupo")
            continue
        if not row:
            issues.append(f"{field_id}: Grade do documento sem linha")
            continue
        groups.setdefault(group, []).append(field)

    for group, group_fields in groups.items():
        rows: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
        static_by_row: dict[str, list[dict[str, Any]]] = {}
        for field in group_fields:
            row = str(field.get("layout_row", "")).strip()
            rows.setdefault(row, []).append(field)
            for cell in field.get("layout_row_static_cells", []) or []:
                if isinstance(cell, dict):
                    cell_row = str(cell.get("layout_row", row)).strip() or row
                    static_by_row.setdefault(cell_row, []).append(cell)

        for row, row_fields in rows.items():
            totals = {
                _safe_layout_int(field.get("layout_grid_columns"), 1)
                for field in row_fields
            }
            if len(totals) > 1:
                issues.append(f"{group}/{row}: campos usam totais de colunas diferentes")
            total = max(totals or {1})
            total = max(1, total)

            occupied: list[tuple[int, int, str]] = []
            seen_cells: set[tuple[int, int]] = set()
            for field in row_fields:
                start = _safe_layout_int(field.get("layout_column_index"), 0)
                span = _safe_layout_int(field.get("layout_column_span"), 1)
                field_id = str(field.get("id", "")).strip() or "campo"
                if start < 0 or span < 1 or start + span > total:
                    issues.append(f"{group}/{row}: posição inválida em {field_id}")
                    continue
                cell_key = (start, span)
                # Several tags in the same physical Word cell are intentionally
                # stacked and do not count as an overlap.
                if cell_key not in seen_cells:
                    occupied.append((start, start + span, field_id))
                    seen_cells.add(cell_key)

            for cell in static_by_row.get(row, []):
                start = _safe_layout_int(cell.get("layout_column_index"), 0)
                span = _safe_layout_int(cell.get("layout_column_span"), 1)
                label = str(cell.get("text", "")).strip() or "texto fixo"
                if start < 0 or span < 1 or start + span > total:
                    issues.append(f"{group}/{row}: posição inválida no texto fixo '{label[:40]}'")
                    continue
                occupied.append((start, start + span, label))

            occupied.sort(key=lambda item: (item[0], item[1]))
            for previous, current in zip(occupied, occupied[1:]):
                if current[0] < previous[1]:
                    issues.append(
                        f"{group}/{row}: células sobrepostas entre '{previous[2]}' e '{current[2]}'"
                    )

    # Keep the readiness panel readable even for badly malformed templates.
    return list(dict.fromkeys(issues))[:12]


def _safe_layout_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def layout_blocks(fields: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return ordered semantic layout blocks used by the form and preview UI."""

    blocks: list[dict[str, Any]] = []
    normal_buffer: list[dict[str, Any]] = []
    grouped_indexes: dict[tuple[str, str], int] = {}

    def flush_normal() -> None:
        nonlocal normal_buffer
        if normal_buffer:
            blocks.append({"type": "grid", "fields": normal_buffer})
            normal_buffer = []

    for source in normalize_form_layout(fields):
        field = dict(source)
        layout = str(field.get("layout", "auto")).strip().casefold()
        field_type = str(field.get("type", "text")).strip().casefold()

        if layout == "choice" or (
            layout not in {"table", "form_grid"}
            and
            field_type == "checkbox"
            and str(field.get("selection", "")).casefold()
            in {"single", "exclusive", "radio"}
            and str(field.get("group", "")).strip()
        ):
            flush_normal()
            group = str(
                field.get("layout_group") or field.get("group") or field.get("id")
            ).strip()
            key = ("choice", group)
            index = grouped_indexes.get(key)
            if index is None:
                index = len(blocks)
                grouped_indexes[key] = index
                blocks.append(
                    {
                        "type": "choice",
                        "group": group,
                        "label": str(field.get("layout_group_label", "")).strip(),
                        "fields": [],
                    }
                )
            blocks[index]["fields"].append(field)
            continue

        if layout in {"table", "form_grid"} and str(
            field.get("layout_group", "")
        ).strip():
            flush_normal()
            group = str(field.get("layout_group", "")).strip()
            key = (layout, group)
            index = grouped_indexes.get(key)
            if index is None:
                index = len(blocks)
                grouped_indexes[key] = index
                blocks.append(
                    {
                        "type": layout,
                        "group": group,
                        "label": str(field.get("layout_group_label", "")).strip(),
                        "fields": [],
                        "static_rows": [],
                        "row_static_cells": [],
                    }
                )
            block = blocks[index]
            block["fields"].append(field)
            if layout == "form_grid":
                known = {
                    _static_row_key(row)
                    for row in block.get("static_rows", [])
                    if isinstance(row, dict)
                }
                for row in field.get("layout_static_rows", []) or []:
                    if not isinstance(row, dict):
                        continue
                    row_key = _static_row_key(row)
                    if row_key not in known:
                        block["static_rows"].append(dict(row))
                        known.add(row_key)

                known_row_cells = {
                    _row_static_cell_key(cell)
                    for cell in block.get("row_static_cells", [])
                    if isinstance(cell, dict)
                }
                for cell in field.get("layout_row_static_cells", []) or []:
                    if not isinstance(cell, dict):
                        continue
                    cell_key = _row_static_cell_key(cell)
                    if cell_key not in known_row_cells:
                        block["row_static_cells"].append(dict(cell))
                        known_row_cells.add(cell_key)
            continue

        normal_buffer.append(field)

    flush_normal()
    return blocks


# Table analysis --------------------------------------------------------------
def _analyze_table(
    table: Table,
    *,
    table_index: int,
    inherited_section: str,
    metadata: dict[str, dict[str, Any]],
) -> str:
    grid_columns = _table_grid_columns(table)
    rows = _table_rows(table, grid_columns)
    data_header_index = _find_data_table_header(rows)
    header_by_column = _header_map(rows[data_header_index]) if data_header_index is not None else {}

    current_section = inherited_section
    segment_index = 0
    current_group = f"doc_table_{table_index}_segment_{segment_index}"
    static_rows_by_group: dict[str, list[dict[str, Any]]] = OrderedDict()
    first_form_field_by_group: dict[str, str] = {}
    # A real data-table header is valid only inside its own logical segment.
    # Large institutional forms often place several numbered sections in one
    # physical Word table.  Without scoping, a header such as
    # ``Trecho | Origem | Destino | Data`` can incorrectly classify fields in
    # the following section as another data row.
    active_data_headers: dict[int, str] = {}

    for row in rows:
        if not row.matches:
            possible_section = _table_section_title(row.text, row.cells, grid_columns)
            if possible_section:
                current_section = possible_section
                segment_index += 1
                current_group = f"doc_table_{table_index}_segment_{segment_index}"
                static_rows_by_group.setdefault(current_group, [])
                active_data_headers = {}
                continue

            if row.index == data_header_index:
                active_data_headers = dict(header_by_column)
                continue

            for cell in row.plain_cells:
                text = _cell_label_without_tags(cell.text)
                if not text:
                    continue
                static_rows_by_group.setdefault(current_group, []).append(
                    {
                        "layout_order": row.index,
                        "layout_column_index": cell.start,
                        "layout_column_span": cell.span,
                        "layout_grid_columns": grid_columns,
                        "text": text,
                    }
                )
            continue

        checkbox_matches = [item for item in row.matches if item[2] == "checkbox"]
        only_checkboxes = len(checkbox_matches) == len(row.matches)
        choice_labels = [item[3] or item[1] for item in checkbox_matches]
        if (
            len(checkbox_matches) >= 2
            and only_checkboxes
            and _looks_like_exclusive_choice(choice_labels)
        ):
            choice_group = f"choice_{table_index}_{row.index}"
            group_label = _choice_group_from_row(
                row.text,
                choice_labels,
                current_section,
            )
            for _cell, field_id, _field_type, label in checkbox_matches:
                values = metadata.setdefault(field_id, {})
                values.update(
                    {
                        "section": current_section,
                        "layout": "choice",
                        "layout_group": choice_group,
                        "layout_group_label": group_label,
                        "layout_order": row.index,
                        "group": choice_group,
                        "selection": "single",
                        "choice_required": True,
                    }
                )
                if label:
                    values.setdefault("detected_label", label)
            continue

        is_data_row = bool(active_data_headers) and _row_matches_data_header(
            row, active_data_headers
        )

        if is_data_row:
            _apply_data_table_row(
                row,
                table_index=table_index,
                current_section=current_section,
                header_by_column=active_data_headers,
                metadata=metadata,
            )
            continue

        # Form grid: preserve each Word row, physical cell start and grid span.
        group = current_group
        static_rows_by_group.setdefault(group, [])
        same_row_static_cells = [
            {
                "layout_row": f"row_{row.index}",
                "layout_order": row.index,
                "layout_column_index": cell.start,
                "layout_column_span": max(1, cell.span),
                "layout_grid_columns": grid_columns,
                "text": _cell_label_without_tags(cell.text),
            }
            for cell in row.plain_cells
            if _cell_label_without_tags(cell.text)
        ]
        for match_index, (cell, field_id, _field_type, label) in enumerate(row.matches):
            values = metadata.setdefault(field_id, {})
            if current_section:
                values.setdefault("section", current_section)
            if label:
                values.setdefault("detected_label", label)
            values.update(
                {
                    "layout": "form_grid",
                    "layout_group": group,
                    "layout_group_label": current_section,
                    "layout_row": f"row_{row.index}",
                    "layout_column_index": cell.start,
                    "layout_column_span": max(1, cell.span),
                    "layout_grid_columns": grid_columns,
                    "layout_order": row.index,
                }
            )
            if match_index == 0 and same_row_static_cells:
                values["layout_row_static_cells"] = same_row_static_cells
            first_form_field_by_group.setdefault(group, field_id)

    # Store static context once, on the first field of each form-grid group.
    for group, field_id in first_form_field_by_group.items():
        static_rows = static_rows_by_group.get(group, [])
        if static_rows:
            metadata.setdefault(field_id, {})["layout_static_rows"] = static_rows

    return current_section


def _apply_data_table_row(
    row: _TableRowInfo,
    *,
    table_index: int,
    current_section: str,
    header_by_column: dict[int, str],
    metadata: dict[str, dict[str, Any]],
) -> None:
    table_group = f"doc_table_{table_index}"
    field_starts = [cell.start for cell, *_rest in row.matches]
    row_label = _row_label_from_visual_cells(row.plain_cells, field_starts)
    row_header_label = _header_for_position(0, header_by_column) or "Função"

    for cell, field_id, _field_type, label in row.matches:
        values = metadata.setdefault(field_id, {})
        if current_section:
            values.setdefault("section", current_section)
        if label:
            values.setdefault("detected_label", label)
        column_label = _header_for_position(cell.start, header_by_column) or label
        values.update(
            {
                "layout": "table",
                "layout_group": table_group,
                "layout_group_label": current_section,
                "layout_row": f"row_{row.index}",
                "layout_row_label": row_label,
                "layout_row_header_label": row_header_label,
                "layout_column": column_label,
                "layout_column_index": cell.start,
                "layout_order": row.index,
            }
        )


def _table_rows(table: Table, grid_columns: int) -> list[_TableRowInfo]:
    rows: list[_TableRowInfo] = []
    for row_index, row in enumerate(table.rows):
        visual_cells = _visual_cells(row, table, grid_columns)
        matches: list[tuple[_VisualCell, str, str, str]] = []
        plain_cells: list[_VisualCell] = []
        row_text_parts: list[str] = []

        for visual_cell in visual_cells:
            if visual_cell.vertical_continuation:
                continue
            cell_text = _clean_text(visual_cell.text)
            if cell_text:
                row_text_parts.append(cell_text)
            cell_matches = _placeholder_matches(cell_text)
            if cell_matches:
                local_label = _cell_label_without_tags(cell_text)
                for field_id, field_type, detected_label in cell_matches:
                    matches.append(
                        (
                            visual_cell,
                            field_id,
                            field_type,
                            detected_label or local_label,
                        )
                    )
            elif cell_text:
                plain_cells.append(visual_cell)

        rows.append(
            _TableRowInfo(
                index=row_index,
                cells=visual_cells,
                matches=matches,
                plain_cells=plain_cells,
                text=" ".join(row_text_parts).strip(),
            )
        )
    return rows


def _visual_cells(row: _Row, table: Table, grid_columns: int) -> list[_VisualCell]:
    start = _row_grid_before(row)
    result: list[_VisualCell] = []
    for tc in row._tr.tc_lst:
        tc_pr = tc.tcPr
        grid_span = getattr(tc_pr, "gridSpan", None)
        try:
            span = int(grid_span.val) if grid_span is not None else 1
        except (TypeError, ValueError):
            span = 1
        span = max(1, span)

        v_merge = getattr(tc_pr, "vMerge", None)
        vertical_continuation = False
        if v_merge is not None:
            value = getattr(v_merge, "val", None)
            vertical_continuation = value not in {"restart", True}

        cell = _Cell(tc, table)
        result.append(
            _VisualCell(
                cell=cell,
                start=start,
                span=span,
                text=cell.text,
                vertical_continuation=vertical_continuation,
            )
        )
        start += span

    # Broken/legacy DOCX files sometimes omit tblGrid. Keep the inferred grid
    # at least as large as the occupied visual columns.
    if result and grid_columns < max(item.start + item.span for item in result):
        grid_columns = max(item.start + item.span for item in result)
    return result


def _table_grid_columns(table: Table) -> int:
    try:
        count = len(table._tbl.tblGrid.gridCol_lst)
    except (AttributeError, TypeError):
        count = 0
    if count:
        return count
    maximum = 1
    for row in table.rows:
        start = _row_grid_before(row)
        for tc in row._tr.tc_lst:
            grid_span = getattr(tc.tcPr, "gridSpan", None)
            try:
                span = int(grid_span.val) if grid_span is not None else 1
            except (TypeError, ValueError):
                span = 1
            start += max(1, span)
        maximum = max(maximum, start)
    return maximum


def _row_grid_before(row: _Row) -> int:
    tr_pr = row._tr.trPr
    if tr_pr is None:
        return 0
    node = tr_pr.find(qn("w:gridBefore"))
    if node is None:
        return 0
    try:
        return max(0, int(node.get(qn("w:val"), "0")))
    except (TypeError, ValueError):
        return 0


def _find_data_table_header(rows: list[_TableRowInfo]) -> int | None:
    """Find a real tabular header, requiring repeated aligned data rows.

    Requiring at least two aligned rows prevents ordinary two-column Word forms
    from being mistaken for data tables.
    """

    for candidate in rows:
        if candidate.matches:
            continue
        nonempty = [cell for cell in candidate.plain_cells if _clean_text(cell.text)]
        if len(nonempty) < 2:
            continue
        labels = [_cell_label_without_tags(cell.text) for cell in nonempty]
        if any(not label or len(label) > 80 for label in labels):
            continue

        header_map = {cell.start: label for cell, label in zip(nonempty, labels)}
        aligned_rows = 0
        for later in rows[candidate.index + 1 :]:
            if not later.matches:
                # Stop at a new numbered/merged section title.
                if _table_section_title(later.text, later.cells, _grid_size_from_cells(later.cells)):
                    break
                continue
            if _row_matches_data_header(later, header_map):
                aligned_rows += 1
            if aligned_rows >= 2:
                return candidate.index
    return None


def _row_matches_data_header(
    row: _TableRowInfo,
    header_by_column: dict[int, str],
) -> bool:
    if len(row.matches) < 2 or len({cell.start for cell, *_ in row.matches}) < 2:
        return False
    matched = sum(
        1
        for cell, *_rest in row.matches
        if _header_for_position(cell.start, header_by_column)
    )
    if matched < 2:
        return False
    field_starts = [cell.start for cell, *_rest in row.matches]
    has_leading_row_label = any(
        cell.start < min(field_starts)
        for cell in row.plain_cells
        if _cell_label_without_tags(cell.text)
    )
    return has_leading_row_label or matched >= max(2, len(header_by_column) - 1)


def _header_map(row: _TableRowInfo) -> dict[int, str]:
    return {
        cell.start: _cell_label_without_tags(cell.text)
        for cell in row.plain_cells
        if _cell_label_without_tags(cell.text)
    }


def _header_for_position(position: int, headers: dict[int, str]) -> str:
    if position in headers:
        return headers[position]
    before = [start for start in headers if start <= position]
    return headers[max(before)] if before else ""


# Generic document helpers ----------------------------------------------------
def _iter_block_items(parent: _Document | _Cell) -> Iterable[Paragraph | Table]:
    parent_element = parent.element.body if isinstance(parent, _Document) else parent._tc
    for child in parent_element.iterchildren():
        if child.tag.endswith("}p"):
            yield Paragraph(child, parent)
        elif child.tag.endswith("}tbl"):
            yield Table(child, parent)


def _paragraph_section_title(paragraph: Paragraph) -> str:
    text = _clean_text(paragraph.text)
    if not text or len(text) > 140 or PLACEHOLDER_PATTERN.search(text):
        return ""

    style_name = str(getattr(paragraph.style, "name", "") or "").casefold()
    is_heading_style = any(
        token in style_name
        for token in ("heading", "título", "titulo", "cabeçalho", "cabecalho")
    )
    is_numbered_heading = bool(HEADING_NUMBER_PATTERN.match(text)) and (
        text.endswith(":") or len(text) <= 100
    )
    bold_runs = [run for run in paragraph.runs if run.text.strip()]
    mostly_bold = bool(bold_runs) and sum(bool(run.bold) for run in bold_runs) >= max(
        1, len(bold_runs) - 1
    )

    if is_heading_style or is_numbered_heading or (mostly_bold and text.endswith(":")):
        return text.rstrip(":").strip()
    return ""


def _table_section_title(
    text: str,
    cells: list[_VisualCell],
    grid_columns: int,
) -> str:
    clean = _clean_text(text)
    if not clean or len(clean) > 150 or PLACEHOLDER_PATTERN.search(clean):
        return ""
    occupied = [cell for cell in cells if _clean_text(cell.text) and not cell.vertical_continuation]
    single_full_width = (
        len(occupied) == 1
        and occupied[0].start == 0
        and occupied[0].span >= max(1, grid_columns)
    )
    if single_full_width or HEADING_NUMBER_PATTERN.match(clean):
        if clean.endswith(":") or HEADING_NUMBER_PATTERN.match(clean):
            return clean.rstrip(":").strip()
    return ""


def _placeholder_matches(text: str) -> list[tuple[str, str, str]]:
    result: list[tuple[str, str, str]] = []
    previous_end = 0
    for match in PLACEHOLDER_PATTERN.finditer(str(text or "")):
        raw = match.group(1).strip()
        field_type, field_id = _parse_tag(raw)
        if not field_id or field_type == "repeat":
            previous_end = match.end()
            continue
        before = text[previous_end : match.start()]
        label_before = _clean_label(before)
        after = text[match.end() :]
        label_after = _clean_label(after.split("{{", 1)[0])
        result.append((field_id, field_type, label_before or label_after))
        previous_end = match.end()
    return result


def _parse_tag(raw: str) -> tuple[str, str]:
    value = raw.strip()
    lowered = value.casefold()
    for prefix, field_type in (
        ("checkbox:", "checkbox"),
        ("date:", "date"),
        ("dropdown:", "dropdown"),
        ("single_choice:", "dropdown"),
        ("repeat:", "repeat"),
    ):
        if lowered.startswith(prefix):
            payload = value.split(":", 1)[1]
            field_id = payload.split("|", 1)[0].strip()
            return field_type, field_id
    return "text", value.split("|", 1)[0].strip()


def _cell_label_without_tags(text: str) -> str:
    return _clean_label(PLACEHOLDER_PATTERN.sub(" ", str(text or "")))


def _clean_label(text: str) -> str:
    value = _clean_text(text).strip(" :：–—-|;,.\t\r\n")
    value = re.sub(r"^[☐☑✓✔□■◻◼]+\s*", "", value).strip()
    if not value or len(value) > 160:
        return ""
    return value


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _row_label_from_visual_cells(
    plain_cells: list[_VisualCell],
    field_columns: list[int],
) -> str:
    if not plain_cells:
        return ""
    first_field = min(field_columns) if field_columns else 10**6
    before = [
        cell
        for cell in plain_cells
        if cell.start < first_field and _cell_label_without_tags(cell.text)
    ]
    if before:
        return _cell_label_without_tags(before[-1].text)
    return _cell_label_without_tags(plain_cells[0].text)


def _looks_like_exclusive_choice(labels: list[str]) -> bool:
    normalized = [re.sub(r"\s+", " ", label.casefold()).strip() for label in labels if label]
    if len(normalized) < 2:
        return False
    joined = " | ".join(normalized)
    for left, right in EXCLUSIVE_PAIR_WORDS:
        if left in joined and right in joined:
            return True
    return len(normalized) == 2 and any(
        token in joined
        for token in ("modalidade", "prazo", "forma", "tipo", "opção", "opcao")
    )


def _choice_group_label(labels: list[str]) -> str:
    words = [re.split(r"\s+", label.strip()) for label in labels if label.strip()]
    if not words:
        return "Escolha uma opção"
    common: list[str] = []
    for parts in zip(*words):
        if len({part.casefold() for part in parts}) == 1:
            common.append(parts[0])
        else:
            break
    label = " ".join(common).strip(" :：–—-")
    return label if len(label) >= 3 else "Escolha uma opção"


def _choice_group_from_row(row_text: str, labels: list[str], section: str) -> str:
    cleaned = row_text
    for label in labels:
        cleaned = re.sub(re.escape(label), " ", cleaned, flags=re.IGNORECASE)
    cleaned = PLACEHOLDER_PATTERN.sub(" ", cleaned)
    cleaned = _clean_label(cleaned)
    if cleaned:
        return cleaned
    common = _choice_group_label(labels)
    if common != "Escolha uma opção":
        return common
    return section or "Escolha uma opção"


def _row_static_cell_key(cell: dict[str, Any]) -> tuple[Any, ...]:
    return (
        cell.get("layout_row"),
        cell.get("layout_order"),
        cell.get("layout_column_index"),
        cell.get("layout_column_span"),
        cell.get("layout_grid_columns"),
        str(cell.get("text", "")).strip(),
    )


def _static_row_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row.get("layout_order"),
        row.get("layout_column_index"),
        row.get("layout_column_span"),
        str(row.get("text", "")),
    )


def _grid_size_from_cells(cells: list[_VisualCell]) -> int:
    return max((cell.start + cell.span for cell in cells), default=1)
