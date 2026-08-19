from __future__ import annotations

import re
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from docx import Document
from docx.oxml.ns import qn

from app.document.understanding.context_resolver import build_word_control_context_map, _element_path, usable_dropdown_options
from app.domain.fields import FieldDefinition
from app.domain.field_ids import FIELD_ID_TOKEN_PATTERN
from app.domain.field_metadata import compact_dropdown_options, normalize_repeatable_columns
from app.document.docx.tags import PLACEHOLDER_PATTERN, TagKind, parse_tag
from app.document.docx.controls import (
    classify_native_control,
    get_control_identifier,
    iter_unique_story_roots,
    normalize_control_id,
    read_dropdown_options,
)


REPEAT_MARKER_PATTERN = re.compile(
    rf"\{{\{{\s*repeat:({FIELD_ID_TOKEN_PATTERN})\s*\}}\}}",
    re.IGNORECASE,
)


def scan_docx_fields(docx_path: Path) -> list[FieldDefinition]:
    """Scan a DOCX with an mtime/size keyed cache and isolated return values."""

    path = Path(docx_path).expanduser().resolve()
    _validate_docx_path(path)
    stat = path.stat()
    raw_fields = _scan_docx_fields_cached(
        str(path), int(stat.st_mtime_ns), int(stat.st_size)
    )
    return [FieldDefinition(deepcopy(field)) for field in raw_fields]


@lru_cache(maxsize=96)
def _scan_docx_fields_cached(
    resolved_path: str,
    _mtime_ns: int,
    _size: int,
) -> tuple[dict[str, Any], ...]:
    return tuple(
        dict(field) for field in _scan_docx_fields_uncached(Path(resolved_path))
    )


def clear_docx_scan_cache() -> None:
    _scan_docx_fields_cached.cache_clear()

def _scan_docx_fields_uncached(docx_path: Path) -> list[FieldDefinition]:
    """
    Scan placeholders and native Word controls in a DOCX.

    Supported placeholders:

        {{company.name}}
        {{document.date}}
        {{date:document.date}}
        {{checkbox:declaration.accepted}}
        {{dropdown:process.modality|Pregão|Concorrência|Dispensa}}
        {{single_choice:pca.status|Consta no PCA|Não consta no PCA}}

    Date behavior:

    - {{document.date}} is detected as a date field.
    - {{document.data}} is detected as a date field.
    - {{date:document.date}} is detected as a date field.
    - A native Word Date Picker with Tag "document.date" is detected as date.

    A date is created only when the matching placeholder/control exists in
    the DOCX. The scanner does not add date fields that are absent.

    The XML scanner also searches text boxes, shapes, headers, footers, tables,
    and ordinary paragraphs.
    """

    docx_path = Path(docx_path)
    _validate_docx_path(docx_path)

    document = Document(str(docx_path))
    control_context_map = build_word_control_context_map(document)

    ordered_fields: list[FieldDefinition] = []
    field_indexes: dict[str, int] = {}
    untagged_controls: list[str] = []

    def add_field(
        field_id: str,
        field_type: str,
        options: list[Any] | None = None,
        label: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        field_id = normalize_control_id(field_id)
        metadata = dict(metadata or {})
        native_choice_label = (
            field_type == "checkbox"
            and str(metadata.get("detection_source", "")).strip().casefold().startswith("native_word")
        )
        label = (
            _clean_native_choice_label(label)
            if native_choice_label
            else _clean_context_label(label)
        )

        if not field_id:
            return

        context_type = guess_field_type(
            field_id,
            label,
        )
        inferred_from_context = (
            field_type == "text"
            and context_type != "text"
        )
        if inferred_from_context:
            field_type = context_type

        cleaned_options = _clean_options(options or [])
        existing_index = field_indexes.get(field_id)

        if existing_index is not None:
            existing = ordered_fields[existing_index]

            # Explicit controls and stronger contextual suggestions override
            # only a generic text guess.
            if field_type in {"checkbox", "date", "dropdown"}:
                existing["type"] = field_type
            elif (
                str(existing.get("type", "text")) == "text"
                and field_type != "text"
            ):
                existing["type"] = field_type
                existing["type_source"] = "document_context"

            if label and not str(existing.get("label", "")).strip():
                existing["label"] = label
                existing["label_source"] = "document_context"

            if field_type == "dropdown" and cleaned_options:
                existing["options"] = cleaned_options

            if field_type == "repeatable_table":
                detected_columns = normalize_repeatable_columns(
                    metadata.get("columns", [])
                )
                if detected_columns:
                    existing["columns"] = detected_columns
                for key in (
                    "minimum_rows",
                    "numbering_padding",
                    "marker",
                ):
                    if key in metadata:
                        existing[key] = metadata[key]

            for key in (
                "layout",
                "layout_group",
                "layout_group_label",
                "group",
                "selection",
                "choice_required",
                "tag_type",
                "label_source",
                "section",
                "section_source",
                "type_source",
                "detection_source",
                "context_evidence",
                "context_confidence",
                "context_resolver_version",
                "id_source",
                "auto_tagged",
                "profile_identity",
                "context_needs_review",
                "context_review_reason",
                "default_value",
            ):
                value = metadata.get(key)
                if value in (None, "", False):
                    continue
                current = existing.get(key)
                if current in (None, "", "auto", False):
                    existing[key] = value
            if (
                metadata.get("layout") == "choice"
                and label
                and not str(existing.get("layout_group_label", "")).strip()
            ):
                existing["layout_group_label"] = label

            return

        field = FieldDefinition({
            "id": field_id,
            "type": field_type,
        })

        if label:
            field["label"] = label
            field["label_source"] = "document_context"

        if inferred_from_context:
            field["type_source"] = "document_context"

        if field_type == "dropdown":
            field["options"] = cleaned_options

        if field_type == "repeatable_table":
            field["columns"] = normalize_repeatable_columns(
                metadata.get("columns", [])
            )
            field["minimum_rows"] = max(
                0,
                int(metadata.get("minimum_rows", 1) or 0),
            )
            field["numbering_padding"] = max(
                1,
                int(metadata.get("numbering_padding", 2) or 2),
            )
            field["marker"] = str(
                metadata.get("marker", f"repeat:{field_id}")
            )

        for key in (
            "layout",
            "layout_group",
            "layout_group_label",
            "group",
            "selection",
            "choice_required",
            "tag_type",
            "label_source",
            "section",
            "section_source",
            "type_source",
            "detection_source",
            "context_evidence",
            "context_confidence",
            "context_resolver_version",
            "id_source",
            "auto_tagged",
            "profile_identity",
            "context_needs_review",
            "context_review_reason",
            "default_value",
        ):
            value = metadata.get(key)
            if value not in (None, "", False):
                field[key] = value
        if (
            metadata.get("layout") == "choice"
            and label
            and not str(field.get("layout_group_label", "")).strip()
        ):
            field["layout_group_label"] = label

        field_indexes[field_id] = len(ordered_fields)
        ordered_fields.append(field)

    for root in iter_unique_story_roots(document):
        _scan_xml_container(
            root,
            add_field,
            untagged_controls,
            control_context_map,
        )

    # Detector V3 resolves unnamed Word controls from nearby context instead
    # of treating missing Developer metadata as a fatal model error.

    return ordered_fields


def scan_docx_placeholders(docx_path: Path) -> list[str]:
    """
    Compatibility function returning only field IDs.
    """

    return [
        field["id"]
        for field in scan_docx_fields(docx_path)
    ]


def _validate_docx_path(docx_path: Path) -> None:
    if not docx_path.exists():
        raise FileNotFoundError(
            f"Arquivo DOCX não encontrado: {docx_path}"
        )

    if not docx_path.is_file():
        raise ValueError(
            'O caminho DOCX selecionado não é um arquivo.'
        )

    if docx_path.suffix.lower() != ".docx":
        raise ValueError(
            'O arquivo selecionado deve ser um documento DOCX.'
        )

    if docx_path.stat().st_size == 0:
        raise ValueError(
            'O arquivo DOCX selecionado está vazio.'
        )


def _scan_content_control(
    control_element,
    add_field: Callable[..., None],
    untagged_controls: list[str],
    scan_nested_content: Callable[[Any], None],
    control_context_map: dict[str, dict[str, Any]],
) -> None:
    if _scan_native_control(
        control_element,
        add_field,
        untagged_controls,
        control_context_map,
    ):
        return

    content = control_element.find(qn("w:sdtContent"))
    if content is not None:
        scan_nested_content(content)


def _scan_xml_container(
    element,
    add_field: Callable[..., None],
    untagged_controls: list[str],
    control_context_map: dict[str, dict[str, Any]],
) -> None:
    """
    Walk WordprocessingML in document order.

    This XML-level traversal catches paragraphs inside text boxes and shapes,
    which are not exposed through document.paragraphs.
    """

    for child in element.iterchildren():
        if child.tag == qn("w:tbl"):
            _scan_table_element(
                child,
                add_field,
                untagged_controls,
                control_context_map,
            )
            continue

        if child.tag == qn("w:tr"):
            _scan_table_row_element(
                child,
                add_field,
                untagged_controls,
                control_context_map,
            )
            continue

        if child.tag == qn("w:p"):
            _scan_paragraph_element(
                child,
                add_field,
                untagged_controls,
                control_context_map,
            )
            continue

        if child.tag == qn("w:sdt"):
            _scan_content_control(
                child,
                add_field,
                untagged_controls,
                lambda content: _scan_xml_container(
                    content, add_field, untagged_controls, control_context_map
                ),
                control_context_map,
            )
            continue

        _scan_xml_container(
            child,
            add_field,
            untagged_controls,
            control_context_map,
        )


def _scan_table_element(
    table_element,
    add_field: Callable[..., None],
    untagged_controls: list[str],
    control_context_map: dict[str, dict[str, Any]],
) -> None:
    """Scan a Word table while preserving row context.

    A row containing ``{{repeat:table.id}}`` becomes one repeatable-table
    field. The remaining markers in that same row become its columns and are
    therefore not exposed as independent top-level fields.
    """

    rows = [
        child
        for child in table_element.iterchildren()
        if child.tag == qn("w:tr")
    ]
    total_columns = max(
        (
            sum(span for _cell, _start, span in _row_cells_with_positions(row))
            for row in rows
        ),
        default=0,
    )

    previous_rows: list[Any] = []
    for row in rows:
        if _scan_repeatable_row(
            row,
            previous_rows,
            total_columns,
            add_field,
        ):
            previous_rows.append(row)
            continue

        _scan_table_row_element(
            row,
            add_field,
            untagged_controls,
            control_context_map,
        )
        previous_rows.append(row)


def _scan_repeatable_row(
    row_element,
    previous_rows: list[Any],
    total_columns: int,
    add_field: Callable[..., None],
) -> bool:
    row_text = _xml_visible_text(row_element)
    repeat_matches = list(REPEAT_MARKER_PATTERN.finditer(row_text))
    if not repeat_matches:
        return False

    for cell, _start, _span in _row_cells_with_positions(row_element):
        properties = cell.find(qn("w:tcPr"))
        if (
            properties is not None
            and properties.find(qn("w:vMerge")) is not None
        ):
            raise ValueError(
                "A linha marcada como repetível contém uma célula mesclada "
                "verticalmente. Use uma linha modelo sem mesclagem vertical."
            )

    table_ids = {
        match.group(1).strip()
        for match in repeat_matches
    }
    if len(table_ids) != 1:
        raise ValueError(
            "Uma linha repetível deve usar apenas um marcador repeat.\n\n"
            "Exemplo: {{repeat:itens}}"
        )

    table_id = next(iter(table_ids))
    columns: list[dict[str, Any]] = []
    seen_column_ids: set[str] = set()

    for cell, start, span in _row_cells_with_positions(row_element):
        cell_text = _xml_visible_text(cell)
        markers = list(PLACEHOLDER_PATTERN.finditer(cell_text))
        header_label = _header_label_for_cell(
            previous_rows,
            start,
            span,
            total_columns,
        )

        for marker_match in markers:
            raw_marker = marker_match.group(1).strip()
            tag_definition = parse_tag(
                raw_marker,
                clean_options=_clean_options,
                infer_type=guess_field_type,
            )
            if tag_definition.kind is TagKind.REPEAT:
                continue

            if tag_definition.kind is TagKind.ROW_NUMBER:
                column_id = "item"
                if column_id in seen_column_ids:
                    continue
                columns.append(
                    {
                        "id": column_id,
                        "label": header_label or "Item",
                        "type": "auto_number",
                        "required": False,
                        "marker": raw_marker,
                    }
                )
                seen_column_ids.add(column_id)
                continue

            parsed = _parse_placeholder(raw_marker)
            marker_id = str(parsed.get("id", "")).strip()
            prefix = f"{table_id}."
            if not marker_id.startswith(prefix):
                raise ValueError(
                    f"O marcador '{{{{{raw_marker}}}}}' está na linha repetível "
                    f"'{table_id}', mas não começa com '{prefix}'.\n\n"
                    f"Use, por exemplo: {{{{{table_id}.descricao}}}}"
                )

            column_id = marker_id[len(prefix):].strip()
            if not column_id or "." in column_id:
                raise ValueError(
                    "As colunas de uma tabela repetível devem usar IDs simples "
                    "após o nome da tabela.\n\n"
                    f"Exemplo: {{{{{table_id}.quantidade}}}}"
                )
            if column_id in seen_column_ids:
                raise ValueError(
                    f"A coluna '{column_id}' aparece mais de uma vez na linha "
                    f"repetível '{table_id}'."
                )

            context_label = _label_from_placeholder_context(
                cell_text,
                marker_match.start(),
                0,
            )
            resolved_label = (
                context_label
                or header_label
                or create_label(column_id)
            )
            column_type = str(parsed.get("type", "text"))
            explicit_type_prefix = str(
                parsed.get("metadata", {}).get("tag_type", "")
            ) in {"date", "checkbox", "dropdown", "single_choice", "default_or_text"}
            if not explicit_type_prefix:
                # A normal repeatable marker such as ``{{table.item}}`` gets a
                # preliminary type from the complete marker ID.  Re-infer it
                # from the child column itself so words in the parent table ID
                # (for example ``quantidade_a_ser_contratada``) cannot turn
                # Item, Unidade or Valor into integers. Explicit prefixes keep
                # their declared type.
                column_type = guess_field_type(
                    column_id,
                    resolved_label,
                )
            column: dict[str, Any] = {
                "id": column_id,
                "label": resolved_label,
                "type": column_type,
                "required": column_type != "checkbox",
                "marker": marker_id,
            }
            if column["type"] == "dropdown":
                column["options"] = _clean_options(
                    parsed.get("options", [])
                )
            columns.append(column)
            seen_column_ids.add(column_id)

    if not columns:
        raise ValueError(
            f"A linha repetível '{table_id}' não possui colunas.\n\n"
            f"Adicione marcadores como {{{{{table_id}.descricao}}}} na mesma linha."
        )

    add_field(
        table_id,
        "repeatable_table",
        None,
        "",
        {
            "columns": columns,
            "minimum_rows": 1,
            "numbering_padding": 2,
            "marker": f"repeat:{table_id}",
        },
    )
    return True


def _row_cells_with_positions(
    row_element,
) -> list[tuple[Any, int, int]]:
    cells: list[tuple[Any, int, int]] = []
    position = 0
    for cell in row_element.iterchildren():
        if cell.tag != qn("w:tc"):
            continue

        span = 1
        properties = cell.find(qn("w:tcPr"))
        if properties is not None:
            grid_span = properties.find(qn("w:gridSpan"))
            if grid_span is not None:
                try:
                    span = max(
                        1,
                        int(grid_span.get(qn("w:val"), "1")),
                    )
                except (TypeError, ValueError):
                    span = 1

        cells.append((cell, position, span))
        position += span
    return cells


def _header_label_for_cell(
    previous_rows: list[Any],
    start: int,
    span: int,
    total_columns: int,
) -> str:
    labels: list[str] = []
    end = start + span

    for row in previous_rows:
        row_labels: list[str] = []
        for cell, cell_start, cell_span in _row_cells_with_positions(row):
            cell_end = cell_start + cell_span
            if cell_end <= start or cell_start >= end:
                continue
            # Section-title rows commonly span the entire table and should not
            # become part of every column label.
            if total_columns and cell_span >= total_columns:
                continue
            text = _clean_header_text(
                _xml_visible_text(cell)
            )
            if text and text not in row_labels:
                row_labels.append(text)

        if row_labels:
            combined = " / ".join(row_labels)
            if combined not in labels:
                labels.append(combined)

    if not labels:
        return ""
    return " — ".join(labels[-2:])


def _clean_header_text(value: Any) -> str:
    text = PLACEHOLDER_PATTERN.sub(
        "",
        str(value or ""),
    )
    text = re.sub(r"\s+", " ", text).strip(" :：–—-\t\r\n")
    if not text or len(text) > 100:
        return ""
    return text



def _scan_table_row_element(
    row_element,
    add_field: Callable[..., None],
    untagged_controls: list[str],
    control_context_map: dict[str, dict[str, Any]],
) -> None:
    """Scan a table row and use the previous cell as a field label.

    This supports common Word forms where one cell contains ``Órgão`` and the
    next cell contains only ``{{orgao.nome}}``. Ordinary same-cell labels are
    still handled by the paragraph scanner.
    """

    cells = [
        child
        for child in row_element.iterchildren()
        if child.tag == qn("w:tc")
    ]

    for index, cell in enumerate(cells):
        current_text = _xml_visible_text(cell)
        matches = list(PLACEHOLDER_PATTERN.finditer(current_text))
        text_without_markers = PLACEHOLDER_PATTERN.sub(
            "",
            current_text,
        ).strip(" \t\r\n:：–—-")

        if (
            index > 0
            and len(matches) == 1
            and not text_without_markers
        ):
            previous_label = _clean_context_label(
                _xml_visible_text(cells[index - 1])
            )
            if previous_label:
                parsed = _parse_placeholder(
                    matches[0].group(1)
                )
                add_field(
                    parsed["id"],
                    parsed["type"],
                    parsed.get("options"),
                    previous_label,
                    parsed.get("metadata"),
                )

        _scan_xml_container(
            cell,
            add_field,
            untagged_controls,
            control_context_map,
        )


def _xml_visible_text(element) -> str:
    return "".join(
        node.text or ""
        for node in element.iter()
        if node.tag in {
            qn("w:t"),
            qn("w:instrText"),
        }
    )

def _scan_paragraph_element(
    paragraph_element,
    add_field: Callable[..., None],
    untagged_controls: list[str],
    control_context_map: dict[str, dict[str, Any]],
) -> None:
    """
    Scan one paragraph, including placeholders split across several runs.

    Nested paragraphs, such as those inside a text box drawing, are scanned
    separately so text from unrelated paragraphs is never concatenated.
    """

    text_buffer: list[str] = []

    def inspect_buffer() -> None:
        text = "".join(text_buffer)
        text_buffer.clear()

        previous_end = 0
        for match in PLACEHOLDER_PATTERN.finditer(text):
            parsed = _parse_placeholder(
                match.group(1)
            )
            context_label = _label_from_placeholder_context(
                text,
                match.start(),
                previous_end,
            )

            add_field(
                parsed["id"],
                parsed["type"],
                parsed.get("options"),
                context_label,
                parsed.get("metadata"),
            )
            previous_end = match.end()

    def walk(element) -> None:
        for child in element.iterchildren():
            if child.tag == qn("w:p"):
                inspect_buffer()

                _scan_paragraph_element(
                    child,
                    add_field,
                    untagged_controls,
                    control_context_map,
                )
                continue

            if child.tag == qn("w:sdt"):
                inspect_buffer()
                _scan_content_control(
                    child,
                    add_field,
                    untagged_controls,
                    walk,
                    control_context_map,
                )
                continue

            if child.tag == qn("w:fldChar"):
                legacy_result = _read_legacy_checkbox_identifier(
                    child
                )

                if legacy_result is not None:
                    inspect_buffer()

                    hint = dict(control_context_map.get(id(child), {}) or {})
                    field_id = legacy_result or str(hint.get("id", "")).strip()
                    if field_id:
                        add_field(
                            field_id,
                            "checkbox",
                            None,
                            str(hint.get("label", "") or ""),
                            {
                                key: value
                                for key, value in hint.items()
                                if key not in {"id", "type", "label", "options"}
                            },
                        )
                    else:
                        untagged_controls.append(
                            "Caixa de seleção antiga do Word sem identificação resolvível"
                        )

                    continue

            if child.tag in {
                qn("w:t"),
                qn("w:instrText"),
            }:
                text_buffer.append(child.text or "")
                continue

            walk(child)

    walk(paragraph_element)
    inspect_buffer()



def _label_from_placeholder_context(
    paragraph_text: str,
    marker_start: int,
    segment_start: int,
) -> str:
    """Return a conservative field label found immediately before a marker.

    A label is accepted only when the visible text ends with a label separator,
    for example ``Órgão: {{orgao.nome}}``. This avoids turning ordinary prose
    before an embedded marker into an accidental form label.
    """

    segment = paragraph_text[segment_start:marker_start]
    if not segment:
        return ""

    # Keep only the current visual fragment when several markers share a line.
    segment = re.split(r"[\n\r\t]", segment)[-1]
    candidate = re.sub(r"\s+", " ", segment).strip()
    if not candidate:
        return ""

    separator = re.search(r"\s*[:：–—-]\s*$", candidate)
    if separator is None:
        return ""

    candidate = candidate[:separator.start()].strip()
    candidate = re.sub(
        r"^[\s•·▪◦*\-–—\d.)]+",
        "",
        candidate,
    ).strip()
    return _clean_context_label(candidate)


def _clean_context_label(value: Any) -> str:
    label = re.sub(r"\s+", " ", str(value or "")).strip()
    label = label.strip(" :：–—-")
    if not label or len(label) > 100:
        return ""
    if "{{" in label or "}}" in label:
        return ""
    # Labels are short headings, not complete sentences.
    if label.count(".") > 1 or label.endswith((".", ";", "?", "!")):
        return ""
    return label

def _clean_native_choice_label(value: Any) -> str:
    label = re.sub(r"\s+", " ", str(value or "")).strip()
    label = label.strip(" :：–—-\t\r\n")
    if not label or len(label) > 140:
        return ""
    if "{{" in label or "}}" in label:
        return ""
    return label


def _scan_native_control(
    sdt_element,
    add_field: Callable[..., None],
    untagged_controls: list[str],
    control_context_map: dict[str, dict[str, Any]],
) -> bool:
    """
    Scan a modern Word content control.

    Returns True when the control is a recognized checkbox, date picker,
    dropdown, or combo box.
    """

    properties = sdt_element.find(qn("w:sdtPr"))

    if properties is None:
        return False

    control_type, control_element = classify_native_control(
        properties
    )
    if control_type is None:
        return False

    hint = dict(control_context_map.get(_element_path(sdt_element), {}) or {})
    field_id = get_control_identifier(sdt_element) or str(hint.get("id", "")).strip()
    label = str(hint.get("label", "") or "").strip()
    metadata = {
        key: value
        for key, value in hint.items()
        if key not in {"id", "type", "label", "options"}
    }

    if not field_id:
        # The context map normally guarantees a stable fallback ID. Keep this
        # branch only as a defensive compatibility fallback.
        untagged_controls.append("Controle do Word sem identificação resolvível")
        return True

    if control_type == "checkbox":
        add_field(field_id, "checkbox", None, label, metadata)
        return True

    if control_type == "date":
        add_field(field_id, "date", None, label, metadata)
        return True

    hinted_options = list(hint.get("options", []) or [])
    options = hinted_options or usable_dropdown_options(read_dropdown_options(control_element))
    if not options:
        metadata["context_needs_review"] = True
        metadata["context_review_reason"] = "Lista suspensa nativa sem opções configuradas."

    add_field(field_id, "dropdown", options, label, metadata)
    return True


def _read_legacy_checkbox_identifier(
    fld_char_element,
) -> str | None:
    """
    Return:
        None  -> not a legacy checkbox
        ""    -> legacy checkbox without a name
        value -> legacy checkbox field name
    """

    ff_data = fld_char_element.find(qn("w:ffData"))

    if ff_data is None:
        return None

    checkbox = ff_data.find(qn("w:checkBox"))

    if checkbox is None:
        return None

    name = ff_data.find(qn("w:name"))

    if name is None:
        return ""

    return normalize_control_id(
        name.get(qn("w:val"), "")
    )


def _clean_options(
    options: Any,
) -> list[str | dict[str, str]]:
    return compact_dropdown_options(options)


def _parse_placeholder(
    raw_value: str,
) -> dict[str, Any]:
    definition = parse_tag(
        raw_value,
        clean_options=_clean_options,
        infer_type=guess_field_type,
    )

    if definition.kind == TagKind.REPEAT:
        raise ValueError(
            "O marcador repeat deve estar dentro da linha modelo de uma tabela do Word.\n\n"
            "Exemplo: {{repeat:itens}}"
        )
    if definition.kind == TagKind.ROW_NUMBER:
        raise ValueError(
            "O marcador {{row.number}} só pode ser usado na mesma linha de "
            "uma tabela que contenha {{repeat:...}}."
        )

    result: dict[str, Any] = {
        "id": definition.field_id,
        "type": definition.field_type,
    }
    if definition.options:
        result["options"] = list(definition.options)
    if definition.metadata:
        result["metadata"] = dict(definition.metadata)
    return result



def create_default_fields(
    scanned_fields: list[str | dict[str, Any]],
    existing_fields: list[dict[str, Any]] | None = None,
) -> list[FieldDefinition]:
    """Convert detected fields into editable template definitions.

    Labels found immediately before markers in the DOCX are preferred over
    labels generated from technical identifiers. Explicit Word controls keep
    precedence, while existing manual labels and field types are preserved.
    """

    existing_by_id = {
        str(field.get("id", "")).strip(): dict(field)
        for field in (existing_fields or [])
        if isinstance(field, dict)
        and str(field.get("id", "")).strip()
    }

    fields: list[FieldDefinition] = []

    for scanned in scanned_fields:
        if isinstance(scanned, str):
            field_id = scanned.strip()
            detected_label = ""
            detected_type = guess_field_type(field_id)
            detected_options: list[str | dict[str, str]] = []
            label_source = "identifier"
            type_source = "identifier"
            detected_columns: list[dict[str, Any]] = []
            minimum_rows = 0
            numbering_padding = 2
            detected_metadata: dict[str, Any] = {}
        elif isinstance(scanned, dict):
            field_id = str(scanned.get("id", "")).strip()
            detected_label = _clean_context_label(
                scanned.get("label", "")
            )
            detected_type = str(
                scanned.get(
                    "type",
                    guess_field_type(
                        field_id,
                        detected_label,
                    ),
                )
                or "text"
            ).strip()
            detected_options = _clean_options(
                scanned.get("options", []) or []
            )
            label_source = str(
                scanned.get(
                    "label_source",
                    "document_context" if detected_label else "identifier",
                )
            )
            type_source = str(
                scanned.get(
                    "type_source",
                    "document_context" if detected_label else "identifier",
                )
            )
            detected_columns = normalize_repeatable_columns(
                scanned.get("columns", [])
            )
            minimum_rows = max(
                0,
                int(scanned.get("minimum_rows", 1) or 0),
            )
            numbering_padding = max(
                1,
                int(scanned.get("numbering_padding", 2) or 2),
            )
            detected_metadata = {
                key: scanned[key]
                for key in (
                    "layout",
                    "layout_group",
                    "layout_group_label",
                    "group",
                    "selection",
                    "choice_required",
                    "tag_type",
                    "section",
                    "section_source",
                    "type_source",
                    "detection_source",
                    "context_evidence",
                    "context_confidence",
                    "context_resolver_version",
                    "id_source",
                    "auto_tagged",
                    "profile_identity",
                    "context_needs_review",
                    "context_review_reason",
                    "default_value",
                )
                if key in scanned and scanned[key] not in (None, "", False)
            }
        else:
            continue

        if not field_id:
            continue

        automatic_label = create_label(field_id)
        final_detected_label = detected_label or automatic_label
        existing = existing_by_id.get(field_id)

        if existing is not None:
            existing_type = str(
                existing.get("type", detected_type)
                or detected_type
            ).strip()
            existing_type_source = str(
                existing.get("type_source", "")
            ).strip()

            if detected_type in {
                "checkbox",
                "date",
                "dropdown",
            }:
                final_type = detected_type
            elif (
                existing_type == "text"
                and detected_type != "text"
                and existing_type_source in {
                    "",
                    "identifier",
                    "document_context",
                    "automatic",
                }
            ):
                final_type = detected_type
            elif existing_type == "date" and detected_type != "date":
                final_type = detected_type
            else:
                final_type = existing_type

            existing_label = str(
                existing.get("label", "")
            ).strip()
            existing_label_source = str(
                existing.get("label_source", "")
            ).strip()
            may_refresh_label = (
                not existing_label
                or existing_label == automatic_label
                or existing_label_source in {
                    "identifier",
                    "document_context",
                    "automatic",
                }
            )
            final_label = (
                final_detected_label
                if may_refresh_label
                else existing_label
            )

            field = dict(existing)
            field.update(
                {
                    "id": field_id,
                    "label": final_label,
                    "type": final_type,
                    "required": (
                        False
                        if final_type == "checkbox"
                        else bool(existing.get("required", True))
                    ),
                }
            )
            if may_refresh_label:
                field["label_source"] = label_source
            if final_type == detected_type and final_type != existing_type:
                field["type_source"] = type_source

            if final_type == "dropdown":
                existing_options = _clean_options(
                    existing.get("options", []) or []
                )
                field["options"] = detected_options or existing_options
            else:
                field.pop("options", None)

            if final_type == "repeatable_table":
                existing_columns = normalize_repeatable_columns(
                    existing.get("columns", [])
                )
                existing_by_column = {
                    str(column.get("id", "")): dict(column)
                    for column in existing_columns
                }
                merged_columns: list[dict[str, Any]] = []
                for detected_column in detected_columns:
                    column_id = str(detected_column.get("id", ""))
                    existing_column = existing_by_column.get(column_id)
                    if existing_column is None:
                        merged_columns.append(dict(detected_column))
                        continue

                    merged = dict(existing_column)
                    detected_marker = str(
                        detected_column.get("marker", "")
                    ).strip()
                    if detected_marker:
                        merged["marker"] = detected_marker
                    if not str(merged.get("label", "")).strip():
                        merged["label"] = detected_column.get(
                            "label",
                            column_id,
                        )
                    if str(merged.get("type", "text")) == "text":
                        merged["type"] = detected_column.get(
                            "type",
                            "text",
                        )
                    if merged.get("type") == "dropdown" and not merged.get("options"):
                        merged["options"] = detected_column.get("options", [])
                    merged_columns.append(merged)

                field["columns"] = (
                    merged_columns
                    or existing_columns
                )
                field["minimum_rows"] = max(
                    0,
                    int(existing.get("minimum_rows", minimum_rows) or 0),
                )
                field["numbering_padding"] = max(
                    1,
                    int(existing.get("numbering_padding", numbering_padding) or 2),
                )
                field["required"] = bool(existing.get("required", True))
                field.pop("options", None)
            else:
                field.pop("columns", None)

            for key, value in detected_metadata.items():
                current = field.get(key)
                if current in (None, "", "auto", False):
                    field[key] = value

            fields.append(FieldDefinition(field))
            continue

        field: dict[str, Any] = {
            "id": field_id,
            "label": final_detected_label,
            "label_source": label_source,
            "type": detected_type,
            "type_source": type_source,
            "required": detected_type != "checkbox",
        }

        if detected_type == "dropdown":
            field["options"] = detected_options

        if detected_type == "repeatable_table":
            field["columns"] = detected_columns
            field["minimum_rows"] = minimum_rows
            field["numbering_padding"] = numbering_padding
            field["required"] = True

        field.update(detected_metadata)
        fields.append(FieldDefinition(field))

    return fields

def create_label(field_id: str) -> str:
    """Crie um rótulo legível a partir de um ID de campo."""

    raw_id = str(field_id).strip()
    generic_labels = {
        "valor": "Conteúdo",
        "value": "Conteúdo",
        "texto": "Conteúdo",
        "text": "Conteúdo",
        "campo": "Campo a preencher",
        "field": "Campo a preencher",
    }
    generic_label = generic_labels.get(raw_id.casefold())
    if generic_label is not None:
        return generic_label

    return (
        raw_id
        .replace(".", " ")
        .replace("_", " ")
        .replace("-", " ")
        .title()
    )


def guess_field_type(
    field_id: str,
    context_label: str = "",
) -> str:
    """Infer a field type from its identifier and nearby DOCX label.

    The rules are deliberately conservative. In particular, a generic ID such
    as ``valor`` remains text; monetary formatting is used only when the ID or
    label clearly indicates price, amount, estimated value, or total value.
    """

    normalized = " ".join(
        part
        for part in (
            str(field_id).strip().casefold(),
            str(context_label).strip().casefold(),
        )
        if part
    )
    identifier = str(field_id).strip().casefold()

    checkbox_keywords = (
        "checkbox.",
        ".checked",
        ".selected",
        ".accepted",
        ".aceito",
        ".marcado",
    )
    if any(keyword in identifier for keyword in checkbox_keywords):
        return "checkbox"

    parts = {
        part
        for part in re.split(r"[._\-\s/()]+", normalized)
        if part
    }
    compact = re.sub(
        r"[^a-z0-9áàâãéêíóôõúç]",
        "",
        normalized,
    )

    if parts.intersection({"date", "data"}) or compact in {
        "birthdate",
        "dataassinatura",
        "datanascimento",
        "signingdate",
    }:
        return "date"

    if any(
        keyword in normalized
        for keyword in (
            "description",
            "descricao",
            "descrição",
            "object",
            "objeto",
            "observation",
            "observacao",
            "observação",
            "observacoes",
            "observações",
            "notes",
            "nota",
            "details",
            "detalhes",
            "justification",
            "justificativa",
            "fundamentacao",
            "fundamentação",
        )
    ):
        return "multiline"

    if "cnpj" in normalized:
        return "cnpj"
    if re.search(r"(^|[._\-\s])cpf($|[._\-\s])", normalized):
        return "cpf"
    if "cep" in parts or "postal" in normalized or "código postal" in normalized:
        return "cep"
    if any(
        keyword in normalized
        for keyword in (
            "phone",
            "telefone",
            "celular",
            "whatsapp",
            "mobile",
        )
    ):
        return "phone"
    if "email" in normalized or "e-mail" in normalized:
        return "email"

    currency_keywords = (
        "total_value",
        "valor_total",
        "valor total",
        "valor estimado",
        "valor_estimado",
        "preco",
        "preço",
        "price",
        "amount",
        "montante",
        "currency",
        "custo total",
        "custo_total",
        "orçamento",
        "orcamento",
    )
    if any(keyword in normalized for keyword in currency_keywords):
        return "currency"

    if any(
        keyword in normalized
        for keyword in (
            "percentage",
            "percentual",
            "porcentagem",
            "percent",
            "alíquota",
            "aliquota",
        )
    ):
        return "percentage"

    if parts.intersection({"quantidade", "quantity", "qty", "count"}):
        return "integer"

    return "text"

