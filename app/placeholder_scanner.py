from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from docx import Document
from docx.oxml.ns import qn

from app.field_utils import compact_dropdown_options
from app.word_control_utils import (
    classify_native_control,
    get_control_identifier,
    iter_unique_story_roots,
    normalize_control_id,
    read_dropdown_options,
)


PLACEHOLDER_PATTERN = re.compile(r"\{\{([^{}]+)\}\}")


def scan_docx_fields(docx_path: Path) -> list[dict[str, Any]]:
    """
    Scan placeholders and native Word controls in a DOCX.

    Supported placeholders:

        {{company.name}}
        {{document.date}}
        {{date:document.date}}
        {{checkbox:declaration.accepted}}
        {{dropdown:process.modality|Pregão|Concorrência|Dispensa}}

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

    ordered_fields: list[dict[str, Any]] = []
    field_indexes: dict[str, int] = {}
    untagged_controls: list[str] = []

    def add_field(
        field_id: str,
        field_type: str,
        options: list[Any] | None = None,
        label: str = "",
    ) -> None:
        field_id = normalize_control_id(field_id)
        label = _clean_context_label(label)

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

            return

        field: dict[str, Any] = {
            "id": field_id,
            "type": field_type,
        }

        if label:
            field["label"] = label
            field["label_source"] = "document_context"

        if inferred_from_context:
            field["type_source"] = "document_context"

        if field_type == "dropdown":
            field["options"] = cleaned_options

        field_indexes[field_id] = len(ordered_fields)
        ordered_fields.append(field)

    for root in iter_unique_story_roots(document):
        _scan_xml_container(
            root,
            add_field,
            untagged_controls,
        )

    if untagged_controls:
        details = "\n".join(
            f"- {item}"
            for item in untagged_controls
        )

        raise ValueError(
            "Um ou mais controles do Word não possuem um identificador utilizável.\n\n"
            "Para um controle moderno, selecione-o no Word, abra "
            "Desenvolvedor > Propriedades e informe uma Marca exclusiva.\n"
            "Para uma caixa de seleção antiga, defina o nome do indicador/campo.\n\n"
            f"{details}"
        )

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
) -> None:
    if _scan_native_control(
        control_element,
        add_field,
        untagged_controls,
    ):
        return

    content = control_element.find(qn("w:sdtContent"))
    if content is not None:
        scan_nested_content(content)


def _scan_xml_container(
    element,
    add_field: Callable[..., None],
    untagged_controls: list[str],
) -> None:
    """
    Walk WordprocessingML in document order.

    This XML-level traversal catches paragraphs inside text boxes and shapes,
    which are not exposed through document.paragraphs.
    """

    for child in element.iterchildren():
        if child.tag == qn("w:tr"):
            _scan_table_row_element(
                child,
                add_field,
                untagged_controls,
            )
            continue

        if child.tag == qn("w:p"):
            _scan_paragraph_element(
                child,
                add_field,
                untagged_controls,
            )
            continue

        if child.tag == qn("w:sdt"):
            _scan_content_control(
                child,
                add_field,
                untagged_controls,
                lambda content: _scan_xml_container(
                    content, add_field, untagged_controls
                ),
            )
            continue

        _scan_xml_container(
            child,
            add_field,
            untagged_controls,
        )



def _scan_table_row_element(
    row_element,
    add_field: Callable[..., None],
    untagged_controls: list[str],
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
                )

        _scan_xml_container(
            cell,
            add_field,
            untagged_controls,
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
                )
                continue

            if child.tag == qn("w:sdt"):
                inspect_buffer()
                _scan_content_control(
                    child,
                    add_field,
                    untagged_controls,
                    walk,
                )
                continue

            if child.tag == qn("w:fldChar"):
                legacy_result = _read_legacy_checkbox_identifier(
                    child
                )

                if legacy_result is not None:
                    inspect_buffer()

                    if legacy_result:
                        add_field(
                            legacy_result,
                            "checkbox",
                            None,
                        )
                    else:
                        untagged_controls.append(
                            "Caixa de seleção antiga do Word sem identificação"
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

def _scan_native_control(
    sdt_element,
    add_field: Callable[..., None],
    untagged_controls: list[str],
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

    field_id = get_control_identifier(sdt_element)
    control_labels = {
        "checkbox": "caixa de seleção",
        "date": "seletor de data",
        "dropdown": "lista suspensa",
    }

    if not field_id:
        untagged_controls.append(
            "Controle do Word sem identificação: "
            + control_labels[control_type]
        )
        return True

    if control_type == "checkbox":
        add_field(field_id, "checkbox", None)
        return True

    if control_type == "date":
        add_field(field_id, "date", None)
        return True

    options = read_dropdown_options(
        control_element
    )

    if not options:
        raise ValueError(
            f"A lista suspensa nativa '{field_id}' não contém "
            "opções configuradas."
        )

    add_field(field_id, "dropdown", options)
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
    raw_value = raw_value.strip()

    if raw_value.lower().startswith("checkbox:"):
        field_id = raw_value.split(":", 1)[1].strip()

        if not field_id:
            raise ValueError(
                'Um marcador de caixa de seleção não possui ID de campo.'
            )

        return {
            "id": field_id,
            "type": "checkbox",
        }

    if raw_value.lower().startswith("date:"):
        field_id = raw_value.split(":", 1)[1].strip()

        if not field_id:
            raise ValueError(
                'Um marcador de data não possui ID de campo.'
            )

        return {
            "id": field_id,
            "type": "date",
        }

    if raw_value.lower().startswith("dropdown:"):
        definition = raw_value.split(":", 1)[1]

        parts = [
            part.strip()
            for part in definition.split("|")
        ]

        field_id = parts[0] if parts else ""
        options = _clean_options(parts[1:])

        if not field_id:
            raise ValueError(
                'Um marcador de lista suspensa não possui ID de campo.'
            )

        if not options:
            raise ValueError(
                f"A lista suspensa '{field_id}' não contém opções.\n\n"
                "Use: {{dropdown:campo.id|Opção A|Opção B}}\n"
                "Para textos longos: {{dropdown:campo.id|Título curto => Texto completo}}"
            )

        return {
            "id": field_id,
            "type": "dropdown",
            "options": options,
        }

    # Normal placeholders are detected too. Date-like IDs such as
    # {{document.date}} are classified as date by guess_field_type().
    return {
        "id": raw_value,
        "type": guess_field_type(raw_value),
    }



def create_default_fields(
    scanned_fields: list[str | dict[str, Any]],
    existing_fields: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
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

    fields: list[dict[str, Any]] = []

    for scanned in scanned_fields:
        if isinstance(scanned, str):
            field_id = scanned.strip()
            detected_label = ""
            detected_type = guess_field_type(field_id)
            detected_options: list[str | dict[str, str]] = []
            label_source = "identifier"
            type_source = "identifier"
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

            fields.append(field)
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

        fields.append(field)

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

