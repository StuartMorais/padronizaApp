from __future__ import annotations

import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from app.document.understanding.context_resolver import (
    _element_path,
    build_word_control_context_map,
)
from app.domain.field_ids import FIELD_ID_TOKEN_PATTERN
from app.domain.field_metadata import dropdown_option_values
from app.document.docx.tags import PLACEHOLDER_PATTERN, ROW_NUMBER_IDS, TagKind, parse_tag
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
REPLACEMENT_TOKEN_PATTERN = re.compile(
    "\ue000PADRONIZA:(\\d+)\ue001"
)


class DocumentGenerationError(RuntimeError):
    """
    Raised when a document cannot be generated.
    """


def generate_docx(
    template_path: Path,
    output_path: Path,
    values: dict[str, Any],
) -> None:
    """
    Fill a DOCX template and save a completed copy.

    XML-level paragraph replacement is used so placeholders in text boxes,
    shapes, headers, footers, and tables are also replaced.
    """

    template_path = Path(template_path)
    output_path = Path(output_path)

    if not template_path.exists():
        raise DocumentGenerationError(
            f"O modelo não existe: {template_path}"
        )

    try:
        document = Document(str(template_path))
        control_context_map = build_word_control_context_map(document)

        for root in iter_unique_story_roots(document):
            _expand_repeatable_rows(
                root,
                values,
            )

            _replace_placeholders_in_root(
                root,
                values,
            )

            _replace_native_controls(
                root,
                values,
                control_context_map,
            )

            _replace_legacy_checkbox_controls(
                root,
                values,
            )

        unresolved = _find_unresolved_placeholders(
            document
        )

        if unresolved:
            raise DocumentGenerationError(
                "Ainda existem campos não resolvidos: "
                + ", ".join(sorted(unresolved))
            )

        output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        document.save(str(output_path))

    except DocumentGenerationError:
        raise

    except Exception as exc:
        raise DocumentGenerationError(
            f"Não foi possível gerar o documento: {exc}"
        ) from exc


def _expand_repeatable_rows(
    root,
    values: dict[str, Any],
) -> None:
    """Duplicate Word table rows marked with ``{{repeat:field.id}}``.

    The complete ``w:tr`` element is copied, preserving borders, widths,
    shading, paragraph formatting, and merged header rows. Only the marked
    model row is repeated; headers remain untouched.
    """

    template_rows = [
        row
        for row in root.iter(qn("w:tr"))
        if REPEAT_MARKER_PATTERN.search(
            _visible_element_text(row)
        )
    ]

    for template_row in template_rows:
        row_text = _visible_element_text(template_row)
        repeat_matches = list(
            REPEAT_MARKER_PATTERN.finditer(row_text)
        )
        table_ids = {
            normalize_control_id(match.group(1).strip())
            for match in repeat_matches
        }
        if len(table_ids) != 1:
            raise DocumentGenerationError(
                "Uma linha repetível deve usar apenas um marcador repeat."
            )

        table_id = next(iter(table_ids))
        if table_id not in values:
            raise DocumentGenerationError(
                f"Nenhuma linha foi informada para a tabela repetível '{table_id}'."
            )

        raw_rows = values.get(table_id)
        if not isinstance(raw_rows, list):
            raise DocumentGenerationError(
                f"A tabela repetível '{table_id}' recebeu dados em formato inválido."
            )

        parent = template_row.getparent()
        if parent is None:
            continue
        insert_at = parent.index(template_row)

        for row_index, row_values in enumerate(raw_rows, start=1):
            if not isinstance(row_values, dict):
                raise DocumentGenerationError(
                    f"O item {row_index} da tabela '{table_id}' não é uma linha válida."
                )

            cloned_row = deepcopy(template_row)
            scoped_values = dict(values)
            for column_id, value in row_values.items():
                scoped_values[
                    f"{table_id}.{str(column_id).strip()}"
                ] = value

            number = str(
                row_values.get("__row_number__")
                or f"{row_index:02d}"
            )
            for number_id in ROW_NUMBER_IDS:
                scoped_values[number_id] = number

            _replace_placeholders_in_root(
                cloned_row,
                scoped_values,
            )
            _replace_native_controls(
                cloned_row,
                scoped_values,
                {},
            )
            _replace_legacy_checkbox_controls(
                cloned_row,
                scoped_values,
            )

            unresolved = _unresolved_in_element(
                cloned_row
            )
            if unresolved:
                raise DocumentGenerationError(
                    f"A linha {row_index} da tabela '{table_id}' possui "
                    "marcadores sem conteúdo: "
                    + ", ".join(sorted(unresolved))
                )

            parent.insert(insert_at, cloned_row)
            insert_at += 1

        parent.remove(template_row)


def _visible_element_text(element) -> str:
    return "".join(
        node.text or ""
        for node in element.iter()
        if node.tag in {
            qn("w:t"),
            qn("w:instrText"),
        }
    )


def _unresolved_in_element(element) -> set[str]:
    unresolved: set[str] = set()
    for paragraph in element.iter(qn("w:p")):
        text = "".join(
            node.text or ""
            for node in _paragraph_text_elements(paragraph)
        )
        for match in PLACEHOLDER_PATTERN.finditer(text):
            unresolved.add(match.group(1).strip())
    return unresolved


def _replace_placeholders_in_root(
    root,
    values: dict[str, Any],
) -> None:
    """
    Replace placeholders in every paragraph, including paragraphs located
    inside text boxes.
    """

    for paragraph_element in root.iter(qn("w:p")):
        _replace_in_paragraph_element(
            paragraph_element,
            values,
        )


def _paragraph_text_elements(
    paragraph_element,
) -> list[Any]:
    """
    Return text nodes belonging to this paragraph only.

    Nested w:p elements, such as text-box paragraphs inside a drawing, are
    excluded and processed independently.
    """

    text_elements: list[Any] = []

    def walk(element) -> None:
        for child in element.iterchildren():
            if child.tag == qn("w:p"):
                continue

            if child.tag in {
                qn("w:t"),
                qn("w:instrText"),
            }:
                text_elements.append(child)
                continue

            walk(child)

    walk(paragraph_element)
    return text_elements


def _replace_in_paragraph_element(
    paragraph_element,
    values: dict[str, Any],
) -> None:
    """Replace placeholders without collapsing the paragraph runs.

    Word frequently splits a placeholder across multiple ``w:t`` nodes,
    even when it looks continuous in the editor. Rebuilding the complete
    paragraph in its first node destroys bold, italic, underline, color,
    hyperlinks, and other run-level formatting.

    Replacements are therefore applied from right to left directly to the
    nodes occupied by each placeholder. Text before and after a marker stays
    in its original node and keeps its original formatting. Replacement text
    inherits the marker's formatting except for color, which is always black.
    """

    text_elements = _paragraph_text_elements(
        paragraph_element
    )

    if not text_elements:
        return

    original_parts = [
        element.text or ""
        for element in text_elements
    ]
    original_text = "".join(original_parts)
    matches = list(
        PLACEHOLDER_PATTERN.finditer(original_text)
    )

    if not matches:
        return

    spans = _text_element_spans(
        text_elements,
        original_parts,
    )
    changed = False
    replacement_tokens: dict[str, str] = {}

    # Right-to-left processing keeps all original offsets valid while text
    # located after the current marker may grow or shrink. A temporary token
    # is inserted instead of the final value. The tokens are materialized in
    # dedicated runs afterwards, allowing only user-provided values to receive
    # an explicit black font color without recoloring surrounding template text.
    for replacement_index, match in enumerate(reversed(matches)):
        replacement = _replace_placeholder(
            match,
            values,
        )

        # Missing values intentionally leave the marker unresolved so the
        # final validation can report it with a useful field identifier.
        if replacement == match.group(0):
            continue

        token = f"\ue000PADRONIZA:{replacement_index}\ue001"
        replacement_tokens[token] = replacement

        start_index = _span_index_for_position(
            spans,
            match.start(),
        )
        end_index = _span_index_for_position(
            spans,
            match.end() - 1,
        )

        if start_index is None or end_index is None:
            raise DocumentGenerationError(
                "Não foi possível localizar um marcador no XML do documento."
            )

        start_element, start_offset, _ = spans[start_index]
        end_element, end_offset, _ = spans[end_index]
        local_start = match.start() - start_offset
        local_end = match.end() - end_offset

        if start_index == end_index:
            current_text = start_element.text or ""
            _set_text_element_value(
                start_element,
                current_text[:local_start]
                + token
                + current_text[local_end:],
            )
        else:
            start_text = start_element.text or ""
            end_text = end_element.text or ""

            _set_text_element_value(
                start_element,
                start_text[:local_start]
                + token,
            )

            for element, _, _ in spans[
                start_index + 1 : end_index
            ]:
                _set_text_element_value(
                    element,
                    "",
                )

            _set_text_element_value(
                end_element,
                end_text[local_end:],
            )

        changed = True

    if not changed:
        return

    _materialize_black_replacements(
        paragraph_element,
        replacement_tokens,
    )


def _materialize_black_replacements(
    paragraph_element,
    replacements: dict[str, str],
) -> None:
    """Turn temporary replacement tokens into black, formatting-aware runs.

    The original run formatting is copied so bold, italic, underline, size,
    font family, and other properties remain intact. Only ``w:color`` is
    overridden for generated values. Static text before and after a marker is
    recreated with the untouched template run properties.
    """

    for run in list(paragraph_element.iter(qn("w:r"))):
        if _nearest_ancestor(run, qn("w:p")) is not paragraph_element:
            continue

        run_text = _run_visible_text(run)
        if not REPLACEMENT_TOKEN_PATTERN.search(run_text):
            continue

        segments: list[tuple[str, bool]] = []
        cursor = 0

        for token_match in REPLACEMENT_TOKEN_PATTERN.finditer(run_text):
            if token_match.start() > cursor:
                segments.append(
                    (run_text[cursor:token_match.start()], False)
                )

            token = token_match.group(0)
            segments.append((replacements.get(token, ""), True))
            cursor = token_match.end()

        if cursor < len(run_text):
            segments.append((run_text[cursor:], False))

        parent = run.getparent()
        if parent is None:
            continue

        insert_at = parent.index(run)
        for segment_text, generated in segments:
            if not segment_text:
                continue

            new_run = _clone_text_run(
                run,
                segment_text,
                force_black=generated,
            )
            parent.insert(insert_at, new_run)
            insert_at += 1

        parent.remove(run)


def _run_visible_text(run) -> str:
    """Return a run's text while retaining tabs and line-break positions."""

    parts: list[str] = []
    for child in run.iterchildren():
        if child.tag in {qn("w:t"), qn("w:instrText")}:
            parts.append(child.text or "")
        elif child.tag in {qn("w:br"), qn("w:cr")}:
            parts.append("\n")
        elif child.tag == qn("w:tab"):
            parts.append("\t")
        elif child.tag == qn("w:noBreakHyphen"):
            parts.append("\u2011")
        elif child.tag == qn("w:softHyphen"):
            parts.append("\u00ad")

    return "".join(parts)


def _clone_text_run(
    source_run,
    value: str,
    *,
    force_black: bool,
):
    new_run = OxmlElement("w:r")
    source_properties = source_run.find(qn("w:rPr"))

    if source_properties is not None:
        run_properties = deepcopy(source_properties)
    else:
        run_properties = OxmlElement("w:rPr")

    if force_black:
        _force_black_run_properties(run_properties)

    if len(run_properties):
        new_run.append(run_properties)

    _append_run_value(new_run, value)
    return new_run


def _append_run_value(run, value: str) -> None:
    """Append text, tabs, and line breaks to a run."""

    normalized = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    text_buffer: list[str] = []

    def flush_text() -> None:
        if not text_buffer:
            return
        text_element = OxmlElement("w:t")
        _set_text_element_value(text_element, "".join(text_buffer))
        run.append(text_element)
        text_buffer.clear()

    for character in normalized:
        if character == "\n":
            flush_text()
            run.append(OxmlElement("w:br"))
        elif character == "\t":
            flush_text()
            run.append(OxmlElement("w:tab"))
        else:
            text_buffer.append(character)

    flush_text()

    if not len(run):
        text_element = OxmlElement("w:t")
        _set_text_element_value(text_element, "")
        run.append(text_element)


def _force_black_run_properties(run_properties) -> None:
    """Apply an explicit black font color, overriding theme colors."""

    color = run_properties.find(qn("w:color"))
    if color is None:
        color = OxmlElement("w:color")
        run_properties.append(color)

    color.set(qn("w:val"), "000000")
    for attribute in (
        qn("w:themeColor"),
        qn("w:themeTint"),
        qn("w:themeShade"),
    ):
        color.attrib.pop(attribute, None)


def _force_run_black(run) -> None:
    if run is None:
        return

    run_properties = run.find(qn("w:rPr"))
    if run_properties is None:
        run_properties = OxmlElement("w:rPr")
        run.insert(0, run_properties)

    _force_black_run_properties(run_properties)


def _nearest_ancestor(element, tag):
    current = element.getparent()
    while current is not None:
        if current.tag == tag:
            return current
        current = current.getparent()
    return None


def _text_element_spans(
    text_elements: list[Any],
    original_parts: list[str],
) -> list[tuple[Any, int, int]]:
    """Map each text node to its character range in the paragraph."""

    spans: list[tuple[Any, int, int]] = []
    cursor = 0

    for element, text in zip(
        text_elements,
        original_parts,
        strict=True,
    ):
        end = cursor + len(text)
        spans.append((element, cursor, end))
        cursor = end

    return spans


def _span_index_for_position(
    spans: list[tuple[Any, int, int]],
    position: int,
) -> int | None:
    """Return the text-node index containing a character position."""

    for index, (_, start, end) in enumerate(spans):
        if start <= position < end:
            return index

    return None


def _replace_placeholder(
    match,
    values: dict[str, Any],
) -> str:
    raw_value = match.group(1).strip()
    definition = parse_tag(
        raw_value,
        clean_options=dropdown_option_values,
    )

    if definition.kind == TagKind.REPEAT:
        return ""

    field_id = normalize_control_id(definition.field_id)

    if definition.kind == TagKind.ROW_NUMBER:
        if field_id not in values:
            return match.group(0)
        return str(values[field_id] or "")

    if definition.field_type == "checkbox":
        if field_id not in values:
            return match.group(0)
        return "☑" if _value_as_bool(values[field_id]) else "☐"

    if definition.field_type == "dropdown":
        if field_id not in values:
            return match.group(0)
        return _validated_selected_text(
            values,
            field_id,
            list(definition.options),
        )

    if definition.field_type == "repeatable_list":
        if field_id not in values:
            return match.group(0)
        return _format_repeatable_list(
            values.get(field_id),
            list_style=str(definition.metadata.get("list_style", "bullet") or "bullet"),
            punctuation=str(definition.metadata.get("list_punctuation", "semicolon") or "semicolon"),
        )

    if definition.default_value is not None:
        value = values.get(field_id)
        if value is None or (isinstance(value, str) and not value.strip()):
            return definition.default_value
        return str(value)

    if field_id not in values:
        return match.group(0)

    value = values[field_id]
    if isinstance(value, bool):
        return "☑" if value else "☐"
    if value is None:
        return ""
    return str(value)


def _format_repeatable_list(
    raw_value: Any,
    *,
    list_style: str = "bullet",
    punctuation: str = "semicolon",
) -> str:
    if not isinstance(raw_value, list):
        raise DocumentGenerationError("Uma lista repetível recebeu dados em formato inválido.")
    items = [str(value or "").strip() for value in raw_value if str(value or "").strip()]
    if not items:
        return ""
    style = str(list_style or "bullet").casefold()
    punctuation = str(punctuation or "semicolon").casefold()
    lines: list[str] = []
    for index, item in enumerate(items, start=1):
        if style == "numbered":
            prefix = f"{index}. "
        elif style == "plain":
            prefix = ""
        else:
            prefix = "• "
        if punctuation == "semicolon":
            suffix = "." if index == len(items) else ";"
        elif punctuation == "period":
            suffix = "."
        else:
            suffix = ""
        lines.append(prefix + item.rstrip(";,. ") + suffix)
    return "\n".join(lines)


def _validate_dropdown_selection(
    field_id: str,
    selected_value: str,
    options: list[str],
) -> None:
    if selected_value and options and selected_value not in options:
        raise DocumentGenerationError(
            f"A opção '{selected_value}' não é válida "
            f"para a lista suspensa '{field_id}'."
        )


def _validated_selected_text(
    values: dict[str, Any],
    field_id: str,
    options: list[str],
) -> str:
    selected_value = str(values[field_id] or "").strip()
    _validate_dropdown_selection(
        field_id,
        selected_value,
        options,
    )
    return selected_value


def _replace_native_controls(
    root,
    values: dict[str, Any],
    control_context_map: dict[str, dict[str, Any]],
) -> None:
    for sdt_element in root.iter(qn("w:sdt")):
        properties = sdt_element.find(qn("w:sdtPr"))

        if properties is None:
            continue

        control_type, control_element = classify_native_control(
            properties
        )
        if control_type is None:
            continue

        hint = dict(
            control_context_map.get(
                _element_path(sdt_element),
                {},
            )
            or {}
        )
        field_id = (
            get_control_identifier(sdt_element)
            or str(hint.get("id", "")).strip()
        )

        if not field_id:
            # The scanner does not expose a native control that cannot be
            # identified even after contextual resolution.  Generation must
            # follow the same contract: leave such decorative/legacy controls
            # untouched instead of failing on a field the user could never
            # fill in the UI.
            continue

        if field_id not in values:
            raise DocumentGenerationError(
                f"Nenhum conteúdo foi informado para '{field_id}'."
            )

        if control_type == "checkbox":
            _set_native_checkbox_state(
                sdt_element,
                _value_as_bool(
                    values[field_id]
                ),
            )
            continue

        if control_type == "date":
            _set_content_control_text(
                sdt_element,
                str(values[field_id] or ""),
            )
            continue

        options = read_dropdown_options(
            control_element
        )

        selected_value = _validated_selected_text(
            values, field_id, options
        )

        _set_content_control_text(
            sdt_element,
            selected_value,
        )



def _value_as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().casefold() in {
        "1",
        "true",
        "yes",
        "sim",
        "checked",
        "marcado",
        "x",
        "☑",
    }


def _set_native_checkbox_state(
    sdt_element,
    checked: bool,
) -> None:
    properties = sdt_element.find(qn("w:sdtPr"))
    if properties is None:
        return

    checkbox = properties.find(qn("w14:checkbox"))
    if checkbox is None:
        return

    checked_element = checkbox.find(qn("w14:checked"))
    if checked_element is None:
        checked_element = OxmlElement("w14:checked")
        checkbox.insert(0, checked_element)

    checked_element.set(
        qn("w14:val"),
        "1" if checked else "0",
    )
    _set_content_control_text(
        sdt_element,
        "☑" if checked else "☐",
    )


def _replace_legacy_checkbox_controls(
    root,
    values: dict[str, Any],
) -> None:
    """
    Update legacy Word FORMCHECKBOX fields without removing any boxes.
    """

    for fld_char in root.iter(qn("w:fldChar")):
        ff_data = fld_char.find(qn("w:ffData"))

        if ff_data is None:
            continue

        checkbox = ff_data.find(qn("w:checkBox"))

        if checkbox is None:
            continue

        name = ff_data.find(qn("w:name"))

        if name is None:
            continue

        field_id = _normalize_checkbox_identifier(
            name.get(qn("w:val"), "")
        )

        if not field_id:
            continue

        checked = _value_as_bool(
            values.get(field_id, False)
        )

        checked_element = checkbox.find(
            qn("w:checked")
        )

        if checked_element is None:
            checked_element = OxmlElement(
                "w:checked"
            )
            checkbox.append(checked_element)

        checked_element.set(
            qn("w:val"),
            "1" if checked else "0",
        )

        default_element = checkbox.find(
            qn("w:default")
        )

        if default_element is None:
            default_element = OxmlElement(
                "w:default"
            )
            checkbox.append(default_element)

        default_element.set(
            qn("w:val"),
            "1" if checked else "0",
        )


def _normalize_checkbox_identifier(
    value: str,
) -> str:
    return normalize_control_id(value)

def _set_content_control_text(
    sdt_element,
    value: str,
) -> None:
    properties = sdt_element.find(qn("w:sdtPr"))

    if properties is not None:
        showing_placeholder = properties.find(
            qn("w:showingPlcHdr")
        )

        if showing_placeholder is not None:
            properties.remove(showing_placeholder)

    content = sdt_element.find(
        qn("w:sdtContent")
    )

    if content is None:
        return

    text_elements = list(
        content.iter(qn("w:t"))
    )

    if text_elements:
        _set_text_with_breaks(
            text_elements[0],
            value,
        )
        _force_run_black(
            _nearest_ancestor(
                text_elements[0],
                qn("w:r"),
            )
        )

        for text_element in text_elements[1:]:
            text_element.text = ""

        return

    paragraph = next(
        content.iter(qn("w:p")),
        None,
    )

    run = OxmlElement("w:r")
    run_properties = OxmlElement("w:rPr")
    _force_black_run_properties(run_properties)
    run.append(run_properties)
    text = OxmlElement("w:t")
    run.append(text)
    _set_text_with_breaks(text, value)

    if paragraph is not None:
        paragraph.append(run)
    else:
        content.append(run)


def _set_text_element_value(
    text_element,
    value: Any,
) -> None:
    """Set text while keeping Word's significant-space metadata valid."""

    normalized = str(value or "")
    text_element.text = normalized
    space_attribute = (
        "{http://www.w3.org/XML/1998/namespace}space"
    )

    if normalized.startswith(" ") or normalized.endswith(" "):
        text_element.set(
            space_attribute,
            "preserve",
        )
    else:
        text_element.attrib.pop(
            space_attribute,
            None,
        )


def _set_text_with_breaks(
    text_element,
    value: Any,
) -> None:
    """Write text and convert embedded newlines to Word line breaks."""
    normalized = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    segments = normalized.split("\n")
    parent = text_element.getparent()

    first = segments[0] if segments else ""
    _set_text_element_value(
        text_element,
        first,
    )

    if parent is None or len(segments) <= 1:
        return

    insert_at = parent.index(text_element) + 1
    for segment in segments[1:]:
        line_break = OxmlElement("w:br")
        parent.insert(insert_at, line_break)
        insert_at += 1

        next_text = OxmlElement("w:t")
        _set_text_element_value(
            next_text,
            segment,
        )
        parent.insert(insert_at, next_text)
        insert_at += 1


def _find_unresolved_placeholders(
    document,
) -> set[str]:
    unresolved: set[str] = set()

    for root in iter_unique_story_roots(document):
        for paragraph_element in root.iter(qn("w:p")):
            text = "".join(
                element.text or ""
                for element in _paragraph_text_elements(
                    paragraph_element
                )
            )

            for match in PLACEHOLDER_PATTERN.finditer(text):
                unresolved.add(match.group(1))

    return unresolved
