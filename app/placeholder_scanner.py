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
    ) -> None:
        field_id = normalize_control_id(field_id)

        if not field_id:
            return

        cleaned_options = _clean_options(options or [])
        existing_index = field_indexes.get(field_id)

        if existing_index is not None:
            existing = ordered_fields[existing_index]

            # Explicit control/placeholder types override a generic text guess.
            if field_type in {"checkbox", "date", "dropdown"}:
                existing["type"] = field_type

            if field_type == "dropdown" and cleaned_options:
                existing["options"] = cleaned_options

            return

        field: dict[str, Any] = {
            "id": field_id,
            "type": field_type,
        }

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
    add_field: Callable[[str, str, list[str] | None], None],
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
    add_field: Callable[
        [str, str, list[str] | None],
        None,
    ],
    untagged_controls: list[str],
) -> None:
    """
    Walk WordprocessingML in document order.

    This XML-level traversal catches paragraphs inside text boxes and shapes,
    which are not exposed through document.paragraphs.
    """

    for child in element.iterchildren():
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


def _scan_paragraph_element(
    paragraph_element,
    add_field: Callable[
        [str, str, list[str] | None],
        None,
    ],
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

        for match in PLACEHOLDER_PATTERN.finditer(text):
            parsed = _parse_placeholder(
                match.group(1)
            )

            add_field(
                parsed["id"],
                parsed["type"],
                parsed.get("options"),
            )

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


def _scan_native_control(
    sdt_element,
    add_field: Callable[
        [str, str, list[str] | None],
        None,
    ],
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
    """Converta os campos detectados em definições editáveis do modelo.

    Tipos explícitos detectados no DOCX (caixa de seleção, data e lista
    suspensa) têm prioridade sobre uma configuração antiga. Os demais dados
    já configurados, como seção, chave de perfil, grupo e regras condicionais,
    são preservados.
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
            detected_type = guess_field_type(field_id)
            detected_options: list[str | dict[str, str]] = []
        elif isinstance(scanned, dict):
            field_id = str(scanned.get("id", "")).strip()
            detected_type = str(
                scanned.get(
                    "type",
                    guess_field_type(field_id),
                )
                or "text"
            ).strip()
            detected_options = _clean_options(
                scanned.get("options", []) or []
            )
        else:
            continue

        if not field_id:
            continue

        existing = existing_by_id.get(field_id)

        if existing is not None:
            existing_type = str(
                existing.get("type", detected_type)
                or detected_type
            ).strip()

            if detected_type in {
                "checkbox",
                "date",
                "dropdown",
            }:
                final_type = detected_type
            elif existing_type == "date":
                # A configuração antiga pode ter marcado um campo comum como
                # data. Quando o DOCX não confirma esse tipo, use a detecção.
                final_type = detected_type
            else:
                final_type = existing_type

            field = dict(existing)
            field.update(
                {
                    "id": field_id,
                    "label": str(
                        existing.get("label")
                        or create_label(field_id)
                    ),
                    "type": final_type,
                    "required": (
                        False
                        if final_type == "checkbox"
                        else bool(existing.get("required", True))
                    ),
                }
            )

            if final_type == "dropdown":
                existing_options = _clean_options(
                    existing.get("options", []) or []
                )
                field["options"] = (
                    detected_options
                    or existing_options
                )
            else:
                field.pop("options", None)

            fields.append(field)
            continue

        field: dict[str, Any] = {
            "id": field_id,
            "label": create_label(field_id),
            "type": detected_type,
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


def guess_field_type(field_id: str) -> str:
    """
    Infer the field type only for placeholders that actually exist in the DOCX.

    Examples detected as date:

        {{document.date}}
        {{document.data}}
        {{signing_date}}
        {{company.foundation_date}}

    This does not create a date field by itself. A matching placeholder must
    be present in the DOCX, or the document must contain a native Date Picker.
    """

    normalized = field_id.strip().lower()

    checkbox_keywords = (
        "checkbox.",
        ".checked",
        ".selected",
        ".accepted",
        ".aceito",
        ".marcado",
    )

    if any(
        keyword in normalized
        for keyword in checkbox_keywords
    ):
        return "checkbox"

    # Split the identifier into semantic parts so "document.date" and
    # "signing_date" are recognized without matching unrelated words.
    identifier_parts = {
        part
        for part in re.split(
            r"[._\-\s]+",
            normalized,
        )
        if part
    }

    date_parts = {
        "date",
        "data",
    }

    if identifier_parts.intersection(date_parts):
        return "date"

    date_identifiers = {
        "birthdate",
        "dataassinatura",
        "datanascimento",
        "signingdate",
    }

    compact_identifier = re.sub(
        r"[^a-z0-9áàâãéêíóôõúç]",
        "",
        normalized,
    )

    if compact_identifier in date_identifiers:
        return "date"

    multiline_keywords = (
        "description",
        "descricao",
        "object",
        "objeto",
        "observation",
        "observacao",
        "notes",
        "nota",
        "texto",
        "details",
        "detalhes",
    )

    if any(
        keyword in normalized
        for keyword in multiline_keywords
    ):
        return "multiline"

    if "cnpj" in normalized:
        return "cnpj"

    if re.search(r"(^|[._-])cpf($|[._-])", normalized):
        return "cpf"

    if "cep" in normalized or "postal" in normalized:
        return "cep"

    if any(keyword in normalized for keyword in ("phone", "telefone", "celular", "whatsapp")):
        return "phone"

    if "email" in normalized or "e-mail" in normalized:
        return "email"

    if any(keyword in normalized for keyword in ("total_value", "valor_total", "price", "preco", "preço")):
        return "currency"

    if any(keyword in normalized for keyword in ("percentage", "percentual", "porcentagem")):
        return "percentage"

    return "text"
