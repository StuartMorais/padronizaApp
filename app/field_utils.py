from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any


EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


FIELD_TYPE_ALIASES = {
    "string": "text",
    "input": "text",
    "lineedit": "text",
    "textarea": "multiline",
    "longtext": "multiline",
    "long_text": "multiline",
    "paragraph": "multiline",
    "bool": "checkbox",
    "boolean": "checkbox",
    "check": "checkbox",
    "select": "dropdown",
    "choice": "dropdown",
    "choices": "dropdown",
    "combobox": "dropdown",
    "combo": "dropdown",
    "datetime": "date",
    "money": "currency",
    "number": "decimal",
    "percent": "percentage",
    "table": "repeatable_table",
    "repeating_table": "repeatable_table",
    "repeatable": "repeatable_table",
}


FIELD_TYPE_ORDER = (
    "text",
    "multiline",
    "date",
    "checkbox",
    "dropdown",
    "currency",
    "integer",
    "decimal",
    "percentage",
    "cnpj",
    "cpf",
    "cep",
    "phone",
    "email",
    "repeatable_table",
)

SUPPORTED_FIELD_TYPES = set(FIELD_TYPE_ORDER)


def is_assisted_detection_field(field: dict[str, Any] | None) -> bool:
    """Recognize fields created by assisted detection, including older saves.

    Early assisted-detection builds did not persist ``detection_source`` through
    repository normalization, but their generated IDs consistently used the
    ``auto.`` namespace. Keeping that fallback makes the correction UX appear
    for models created with those versions too.
    """

    if not isinstance(field, dict):
        return False
    if str(field.get("detection_source", "")).strip().casefold() == "automatic":
        return True
    return str(field.get("id", "")).strip().casefold().startswith("auto.")


def uses_assisted_detection(fields: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> bool:
    """Return True when at least one field originated from assisted detection."""

    return any(is_assisted_detection_field(field) for field in fields)


EDITOR_PRESERVED_METADATA_KEYS = (
    "tag_type",
    "layout_order",
    "layout_static_rows",
    "layout_row_static_cells",
    "layout_row_header_label",
    "layout_position_locked",
    "label_source",
    "section_source",
    "type_source",
    "validation_hint",
    "format_hint",
    "placeholder",
    "example",
    "detection_source",
    "detection_confidence",
    "choice_group_label",
    "compact_choice",
    "choice_required",
)


def preserved_editor_field_metadata(original: dict[str, Any] | None) -> dict[str, Any]:
    """Keep non-column metadata while a field passes through the model editor.

    Some automatic-detection semantics are intentionally not exposed as table
    columns.  In particular, an exclusive checkbox group can be embedded into
    a Word form-grid while retaining a separate semantic question label.  If
    that ``choice_group_label`` is discarded, the renderer falls back to the
    surrounding section title, which is misleading.
    """

    if not isinstance(original, dict):
        return {}
    from copy import deepcopy

    return {
        key: deepcopy(original[key])
        for key in EDITOR_PRESERVED_METADATA_KEYS
        if key in original
    }


REPEATABLE_COLUMN_TYPE_ALIASES = {
    **FIELD_TYPE_ALIASES,
    "auto": "auto_number",
    "numbering": "auto_number",
    "row_number": "auto_number",
}

REPEATABLE_COLUMN_TYPES = (
    "auto_number",
    "text",
    "multiline",
    "date",
    "checkbox",
    "dropdown",
    "currency",
    "integer",
    "decimal",
    "percentage",
    "cnpj",
    "cpf",
    "cep",
    "phone",
    "email",
)


def normalize_repeatable_columns(value: Any) -> list[dict[str, Any]]:
    """Normalize repeatable-table column definitions.

    Columns are stored as small field definitions. The ``marker`` key keeps
    the complete marker identifier used inside the Word model, while ``id``
    is the short key stored in each generated row.
    """

    if not isinstance(value, (list, tuple)):
        return []

    columns: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw_column in value:
        if not isinstance(raw_column, dict):
            continue

        column_id = str(raw_column.get("id", "")).strip()
        if not column_id or column_id in seen_ids:
            continue

        configured_type = str(raw_column.get("type", "text")).casefold()
        column_type = REPEATABLE_COLUMN_TYPE_ALIASES.get(
            configured_type,
            configured_type,
        )
        if column_type not in REPEATABLE_COLUMN_TYPES:
            column_type = "text"

        column: dict[str, Any] = {
            "id": column_id,
            "label": str(
                raw_column.get(
                    "label",
                    column_id.replace("_", " ").replace("-", " ").title(),
                )
            ).strip()
            or column_id,
            "type": column_type,
            "required": (
                False
                if column_type in {"auto_number", "checkbox"}
                else bool(raw_column.get("required", False))
            ),
        }

        marker = str(raw_column.get("marker", "")).strip()
        if marker:
            column["marker"] = marker

        if column_type == "dropdown":
            column["options"] = compact_dropdown_options(
                raw_column.get("options", [])
            )

        for key in (
            "placeholder",
            "validation_hint",
            "format_hint",
            "min",
            "max",
            "min_length",
            "max_length",
            "pattern",
            "pattern_message",
            "width",
        ):
            if key in raw_column:
                column[key] = raw_column[key]

        seen_ids.add(column_id)
        columns.append(column)

    _disambiguate_repeatable_column_labels(columns)
    return columns


def _disambiguate_repeatable_column_labels(
    columns: list[dict[str, Any]],
) -> None:
    """Give repeated grid headers distinct labels derived from column IDs.

    Word forms frequently use one merged header cell for several physical
    columns, for example ``Quantidade / 2023 / 2024 / 2025``. The scanner
    sees the same merged header for every marker below it. Showing that same
    long label three times in the application makes the fields impossible to
    distinguish even though document generation is correct.

    Only duplicated labels are adjusted. Unique labels and manually chosen
    labels remain untouched.
    """

    indexes_by_label: dict[str, list[int]] = {}
    for index, column in enumerate(columns):
        label_key = _repeatable_label_key(column.get("label", ""))
        if label_key:
            indexes_by_label.setdefault(label_key, []).append(index)

    for duplicate_indexes in indexes_by_label.values():
        if len(duplicate_indexes) < 2:
            continue

        candidates = [
            _repeatable_column_label_from_id(
                str(columns[index].get("id", ""))
            )
            for index in duplicate_indexes
        ]
        candidate_keys = [
            _repeatable_label_key(candidate)
            for candidate in candidates
        ]

        # Do not replace a duplicated label unless the technical identifiers
        # can produce one clear, different label for every column.
        if (
            any(not key for key in candidate_keys)
            or len(set(candidate_keys)) != len(candidate_keys)
        ):
            continue

        for index, candidate in zip(duplicate_indexes, candidates):
            columns[index]["label"] = candidate
            columns[index]["label_source"] = "identifier_disambiguation"


def _repeatable_label_key(value: Any) -> str:
    return re.sub(
        r"[^a-z0-9áàâãéêíóôõúç]+",
        " ",
        str(value or "").casefold(),
    ).strip()


def _repeatable_column_label_from_id(column_id: str) -> str:
    raw_id = str(column_id or "").strip()
    generic_labels = {
        "item": "Item",
        "valor": "Conteúdo",
        "value": "Conteúdo",
        "texto": "Conteúdo",
        "text": "Conteúdo",
        "campo": "Campo a preencher",
        "field": "Campo a preencher",
    }
    generic = generic_labels.get(raw_id.casefold())
    if generic is not None:
        return generic

    return (
        raw_id
        .replace(".", " ")
        .replace("_", " ")
        .replace("-", " ")
        .title()
    )


def normalize_dropdown_options(value: Any) -> list[dict[str, str]]:
    """Normalize simple or structured dropdown choices.

    A string remains a regular option. A mapping may provide a short visible
    label and a different, potentially long, value inserted into the DOCX.
    The compact text syntax ``Título => texto completo`` is also accepted.
    """
    if isinstance(value, str):
        raw_options: list[Any] = value.split("|")
    elif isinstance(value, dict):
        structured_keys = {
            "label",
            "title",
            "displayText",
            "name",
            "value",
            "text",
            "output",
            "content",
        }
        raw_options = (
            [value]
            if structured_keys.intersection(value)
            else list(value.values())
        )
    elif isinstance(value, (list, tuple)):
        raw_options = list(value)
    else:
        raw_options = []

    result: list[dict[str, str]] = []
    seen_values: set[str] = set()
    for option in raw_options:
        if isinstance(option, dict):
            label = _first_nonempty_text(
                option.get("label"),
                option.get("title"),
                option.get("displayText"),
                option.get("name"),
            )
            output = _first_nonempty_text(
                option.get("value"),
                option.get("text"),
                option.get("output"),
                option.get("content"),
                label,
            )
        else:
            text = str(option or "").strip()
            if "=>" in text:
                raw_label, raw_output = text.split("=>", 1)
                label = raw_label.strip()
                output = raw_output.strip()
            else:
                label = text
                output = text

        output = str(output or "").strip()
        label = str(label or output).strip()
        if not output or output in seen_values:
            continue
        seen_values.add(output)
        result.append({"label": label or output, "value": output})
    return result


def compact_dropdown_options(value: Any) -> list[str | dict[str, str]]:
    """Keep ordinary choices concise while preserving label/value pairs."""
    compact: list[str | dict[str, str]] = []
    for option in normalize_dropdown_options(value):
        if option["label"] == option["value"]:
            compact.append(option["value"])
        else:
            compact.append({
                "label": option["label"],
                "value": option["value"],
            })
    return compact


def dropdown_option_values(value: Any) -> list[str]:
    return [
        option["value"]
        for option in normalize_dropdown_options(value)
    ]


def _first_nonempty_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def condition_matches(
    condition: Any,
    values: dict[str, Any],
) -> bool:
    """Evaluate a template field visibility condition."""
    if not condition:
        return True

    normalized_condition = condition
    if isinstance(normalized_condition, str):
        if "=" not in normalized_condition:
            return True
        field_id, expected = normalized_condition.split("=", 1)
        normalized_condition = {
            "field": field_id.strip(),
            "equals": expected.strip(),
        }

    if not isinstance(normalized_condition, dict):
        return True

    source_id = str(
        normalized_condition.get("field", "")
    ).strip()
    actual = values.get(source_id)

    if "equals" in normalized_condition:
        expected = normalized_condition.get("equals")
        if isinstance(actual, bool) and not isinstance(expected, bool):
            expected = str(expected).casefold() in {
                "1",
                "true",
                "yes",
                "sim",
                "checked",
            }
        return (
            actual == expected
            or str(actual).casefold() == str(expected).casefold()
        )

    if "not_equals" in normalized_condition:
        expected = normalized_condition.get("not_equals")
        return not (
            actual == expected
            or str(actual).casefold() == str(expected).casefold()
        )

    return bool(actual) if normalized_condition.get("truthy") else True


def digits_only(value: Any) -> str:
    return re.sub(r"\D+", "", str(value or ""))


# noinspection SpellCheckingInspection
def infer_field_type(
    field_id: str,
    configured_type: str = "text",
) -> str:
    configured = FIELD_TYPE_ALIASES.get(
        str(configured_type).lower(),
        str(configured_type).lower(),
    )
    if configured not in {"text", ""}:
        return (
            configured
            if configured in SUPPORTED_FIELD_TYPES
            else "text"
        )

    normalized = str(field_id).casefold()
    parts = {
        part
        for part in re.split(r"[._\-\s/()]+", normalized)
        if part
    }

    if "cnpj" in normalized:
        return "cnpj"
    if re.search(r"(^|[._\-])cpf($|[._\-])", normalized):
        return "cpf"
    if "cep" in parts or "postal" in normalized:
        return "cep"
    if any(
        token in normalized
        for token in (
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
    if any(
        token in normalized
        for token in (
            "total_value",
            "valor_total",
            "valor_estimado",
            "price",
            "preco",
            "preço",
            "amount",
            "montante",
            "currency",
            "custo_total",
            "orcamento",
            "orçamento",
        )
    ):
        return "currency"
    if any(
        token in normalized
        for token in (
            "percentage",
            "percentual",
            "porcentagem",
            "percent",
            "aliquota",
            "alíquota",
        )
    ):
        return "percentage"
    if parts.intersection({"quantidade", "quantity", "qty", "count"}):
        return "integer"

    return configured if configured in SUPPORTED_FIELD_TYPES else "text"


def validation_hint(field: dict[str, Any]) -> str:
    """Return a short user-facing format hint for a field definition."""

    field_id = str(field.get("id", ""))
    field_type = infer_field_type(
        field_id,
        str(field.get("type", "text")),
    )
    custom = str(
        field.get("validation_hint", "")
        or field.get("format_hint", "")
    ).strip()
    if custom:
        return custom

    if field_type == "repeatable_table":
        minimum_rows = max(0, int(field.get("minimum_rows", 1) or 0))
        if minimum_rows:
            return (
                "Adicione pelo menos "
                f"{minimum_rows} item(ns). É possível colar linhas copiadas do Excel."
            )
        return "Adicione, duplique, remova ou cole linhas conforme necessário."

    hints = {
        "cnpj": "Formato esperado: 00.000.000/0000-00",
        "cpf": "Formato esperado: 000.000.000-00",
        "cep": "Formato esperado: 00000-000",
        "phone": "Informe DDD e número. Exemplo: (83) 99999-9999",
        "email": "Exemplo: nome@orgao.gov.br",
        "currency": "Digite os centavos normalmente. Exemplo: R$ 1.250,00",
        "integer": "Use somente números inteiros.",
        "decimal": "Use vírgula ou ponto para as casas decimais.",
        "percentage": "Informe uma porcentagem entre 0% e 100%.",
        "date": "Formato exibido: dia/mês/ano.",
    }
    return hints.get(field_type, "")

def format_cnpj(value: Any) -> str:
    digits = digits_only(value)[:14]
    if len(digits) <= 2:
        return digits
    if len(digits) <= 5:
        return f"{digits[:2]}.{digits[2:]}"
    if len(digits) <= 8:
        return f"{digits[:2]}.{digits[2:5]}.{digits[5:]}"
    if len(digits) <= 12:
        return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:]}"
    return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"


def format_cpf(value: Any) -> str:
    digits = digits_only(value)[:11]
    if len(digits) <= 3:
        return digits
    if len(digits) <= 6:
        return f"{digits[:3]}.{digits[3:]}"
    if len(digits) <= 9:
        return f"{digits[:3]}.{digits[3:6]}.{digits[6:]}"
    return f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}"


def format_cep(value: Any) -> str:
    digits = digits_only(value)[:8]
    return f"{digits[:5]}-{digits[5:]}" if len(digits) > 5 else digits


def format_phone(value: Any) -> str:
    digits = digits_only(value)[:11]
    if len(digits) <= 2:
        return digits
    if len(digits) <= 6:
        return f"({digits[:2]}) {digits[2:]}"
    if len(digits) <= 10:
        return f"({digits[:2]}) {digits[2:6]}-{digits[6:]}"
    return f"({digits[:2]}) {digits[2:7]}-{digits[7:]}"


def _decimal_from_localized(value: Any) -> Decimal:
    text = str(value or "").strip().replace("R$", "").replace("%", "").strip()
    if not text:
        return Decimal("0")

    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    else:
        text = text.replace(" ", "")

    return Decimal(text)


def format_currency(value: Any) -> str:
    digits = digits_only(value)
    if not digits:
        return ""

    decimal_value = Decimal(digits) / Decimal("100")
    formatted = f"{decimal_value:,.2f}"
    formatted = formatted.replace(",", "_").replace(".", ",").replace("_", ".")
    return f"R$ {formatted}"


def format_decimal(value: Any, places: int = 2) -> str:
    text = str(value or "").strip()
    if not text:
        return ""

    try:
        number = _decimal_from_localized(text)
    except InvalidOperation:
        filtered = re.sub(r"[^0-9,.-]", "", text)
        try:
            number = _decimal_from_localized(filtered)
        except InvalidOperation:
            return text

    pattern = f"{{:,.{max(0, places)}f}}"
    formatted = pattern.format(number)
    return formatted.replace(",", "_").replace(".", ",").replace("_", ".")


def format_percentage(value: Any) -> str:
    text = str(value or "").replace("%", "").strip()
    text = re.sub(r"[^0-9,.-]", "", text)
    if not text:
        return ""

    # Percentage input behaves like an ordinary number, not currency cents.
    # Typing 25 therefore produces 25%, rather than 0,25%.
    if "," in text:
        integer_part, decimal_part = text.split(",", 1)
    elif "." in text:
        integer_part, decimal_part = text.split(".", 1)
    else:
        integer_part, decimal_part = text, ""

    integer_digits = digits_only(integer_part) or "0"
    integer_digits = str(int(integer_digits))
    decimal_digits = digits_only(decimal_part)[:2]
    formatted = integer_digits
    if decimal_digits:
        formatted += f",{decimal_digits}"
    return f"{formatted}%"


def format_input(field_type: str, value: Any) -> str:
    field_type = infer_field_type("", field_type)
    if field_type == "cnpj":
        return format_cnpj(value)
    if field_type == "cpf":
        return format_cpf(value)
    if field_type == "cep":
        return format_cep(value)
    if field_type == "phone":
        return format_phone(value)
    if field_type == "currency":
        return format_currency(value)
    if field_type == "integer":
        return digits_only(value)
    if field_type == "percentage":
        return format_percentage(value)
    return str(value or "")


def validate_cnpj(value: Any) -> bool:
    digits = digits_only(value)
    if len(digits) != 14 or len(set(digits)) == 1:
        return False

    def digit(base: str, weights: list[int]) -> str:
        total = sum(int(number) * weight for number, weight in zip(base, weights))
        remainder = total % 11
        return "0" if remainder < 2 else str(11 - remainder)

    first = digit(digits[:12], [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    second = digit(digits[:12] + first, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    return digits[-2:] == first + second


def validate_cpf(value: Any) -> bool:
    digits = digits_only(value)
    if len(digits) != 11 or len(set(digits)) == 1:
        return False

    total_1 = sum(int(digits[index]) * (10 - index) for index in range(9))
    first = (total_1 * 10) % 11
    first = 0 if first == 10 else first

    total_2 = sum(int(digits[index]) * (11 - index) for index in range(10))
    second = (total_2 * 10) % 11
    second = 0 if second == 10 else second

    return digits[-2:] == f"{first}{second}"


def validate_field(
    field: dict[str, Any],
    value: Any,
) -> str | None:
    field_id = str(field.get("id", ""))
    field_type = infer_field_type(
        field_id,
        str(field.get("type", "text")),
    )
    label = str(field.get("label", field_id))

    if field_type == "repeatable_table":
        rows = value if isinstance(value, list) else []
        minimum_rows = max(
            0,
            int(
                field.get(
                    "minimum_rows",
                    1 if field.get("required", False) else 0,
                )
                or 0
            ),
        )
        meaningful_rows = [
            row
            for row in rows
            if isinstance(row, dict)
            and any(
                bool(cell)
                if isinstance(cell, bool)
                else bool(str(cell or "").strip())
                for key, cell in row.items()
                if not str(key).startswith("__")
            )
        ]

        if len(meaningful_rows) < minimum_rows:
            return (
                f"{label} exige pelo menos "
                f"{minimum_rows} item(ns) preenchido(s)."
            )

        columns = normalize_repeatable_columns(
            field.get("columns", [])
        )
        if not columns:
            return f"{label} não possui colunas configuradas."

        for row_index, row in enumerate(meaningful_rows, start=1):
            for column in columns:
                column_type = str(column.get("type", "text"))
                if column_type == "auto_number":
                    continue

                column_id = str(column.get("id", "")).strip()
                column_label = str(
                    column.get("label", column_id)
                ).strip() or column_id
                validation_column = dict(column)
                validation_column["id"] = f"{field_id}.{column_id}"
                validation_column["label"] = (
                    f"{label}, item {row_index}, {column_label}"
                )
                error = validate_field(
                    validation_column,
                    row.get(column_id),
                )
                if error:
                    return error

        return None

    if field_type == "checkbox":
        return None

    text = str(value or "").strip()
    if bool(field.get("required", False)) and not text:
        return f"{label} é obrigatório."
    if not text:
        return None

    if field_type == "cnpj" and not validate_cnpj(text):
        return f"{label} contém um CNPJ inválido."
    if field_type == "cpf" and not validate_cpf(text):
        return f"{label} contém um CPF inválido."
    if field_type == "cep" and len(digits_only(text)) != 8:
        return f"{label} deve conter 8 dígitos de CEP."
    if field_type == "phone" and len(digits_only(text)) not in {10, 11}:
        return (
            f"{label} deve conter DDD e um telefone "
            "brasileiro válido."
        )
    if field_type == "email" and not EMAIL_PATTERN.fullmatch(text):
        return f"{label} contém um endereço de e-mail inválido."
    if field_type == "integer" and not re.fullmatch(r"[+-]?\d+", text):
        return f"{label} deve ser um número inteiro."

    numeric_value: Decimal | None = None
    if field_type in {"currency", "decimal", "percentage"}:
        try:
            numeric_value = _decimal_from_localized(text)
        except InvalidOperation:
            return f"{label} deve conter um número válido."

    if field_type == "percentage" and numeric_value is not None:
        minimum = Decimal(str(field.get("min", 0)))
        maximum = Decimal(str(field.get("max", 100)))
        if numeric_value < minimum or numeric_value > maximum:
            return (
                f"{label} deve estar entre "
                f"{format_decimal(minimum)}% e "
                f"{format_decimal(maximum)}%."
            )

    minimum_length = field.get("min_length")
    maximum_length = field.get("max_length")
    if minimum_length not in {None, ""}:
        try:
            minimum_length_value = int(minimum_length)
        except (TypeError, ValueError):
            minimum_length_value = 0
        if minimum_length_value > 0 and len(text) < minimum_length_value:
            return (
                f"{label} deve conter pelo menos "
                f"{minimum_length_value} caracteres."
            )
    if maximum_length not in {None, ""}:
        try:
            maximum_length_value = int(maximum_length)
        except (TypeError, ValueError):
            maximum_length_value = 0
        if maximum_length_value > 0 and len(text) > maximum_length_value:
            return (
                f"{label} deve conter no máximo "
                f"{maximum_length_value} caracteres."
            )

    pattern = str(field.get("pattern", "")).strip()
    if pattern:
        try:
            matches_pattern = re.fullmatch(pattern, text) is not None
        except re.error:
            matches_pattern = True
        if not matches_pattern:
            return str(
                field.get("pattern_message")
                or f"{label} não está no formato esperado."
            )

    return None

def sample_value(field: dict[str, Any]) -> Any:
    field_id = str(field.get("id", "")).casefold()
    field_type = infer_field_type(field_id, str(field.get("type", "text")))

    if field_type == "repeatable_table":
        row: dict[str, Any] = {}
        for column in normalize_repeatable_columns(field.get("columns", [])):
            column_type = str(column.get("type", "text"))
            if column_type == "auto_number":
                continue
            row[str(column.get("id", ""))] = sample_value(column)
        return [row]

    samples: dict[str, Any] = {
        "cnpj": "12.345.678/0001-95",
        "cpf": "529.982.247-25",
        "cep": "70040-010",
        "phone": "(61) 99876-5432",
        "email": "contato@empresa.com.br",
        "currency": "R$ 125.430,50",
        "integer": "10",
        "decimal": "15,50",
        "percentage": "12,50%",
        "multiline": 'Observações de exemplo para validação do documento.',
        "checkbox": True,
    }

    if field_type == "dropdown":
        values = dropdown_option_values(field.get("options", []))
        return values[0] if values else ""
    if field_type in samples:
        return samples[field_type]
    if "process" in field_id or "processo" in field_id or "edital" in field_id:
        return "123/2026"
    if "company" in field_id or "empresa" in field_id or "name" in field_id or "nome" in field_id:
        return 'Empresa Exemplo Ltda.'
    return 'Exemplo de preenchimento'
