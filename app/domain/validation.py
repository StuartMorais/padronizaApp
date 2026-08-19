from __future__ import annotations

import re
from typing import Any

from app.domain.field_handlers import field_handler
from app.domain.field_metadata import dropdown_option_values, normalize_repeatable_columns
from app.domain.field_types import SUPPORTED_FIELD_TYPES, normalize_field_type


def infer_field_type(
    field_id: str,
    configured_type: str = "text",
) -> str:
    raw_configured = str(configured_type or "text").strip().casefold()
    configured = normalize_field_type(raw_configured)
    if raw_configured not in {"text", ""}:
        return configured

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
    """Return a short user-facing format hint from the field registry."""
    field_id = str(field.get("id", ""))
    field_type = infer_field_type(field_id, str(field.get("type", "text")))
    custom = str(field.get("validation_hint", "") or field.get("format_hint", "")).strip()
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
    return field_handler(field_type).hint


def format_input(field_type: str, value: Any) -> str:
    return field_handler(infer_field_type("", field_type)).format(value)


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

    specific_error = field_handler(field_type).validate(field, text)
    if specific_error:
        return specific_error

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

    if field_type == "dropdown":
        values = dropdown_option_values(field.get("options", []))
        return values[0] if values else ""
    handler_sample = field_handler(field_type).sample
    if handler_sample not in (None, "Exemplo de preenchimento"):
        return handler_sample
    if "process" in field_id or "processo" in field_id or "edital" in field_id:
        return "123/2026"
    if "company" in field_id or "empresa" in field_id or "name" in field_id or "nome" in field_id:
        return 'Empresa Exemplo Ltda.'
    return 'Exemplo de preenchimento'


def sample_values_for_fields(fields: list[dict[str, Any]]) -> dict[str, Any]:
    """Build deterministic sample values suitable for template test generation.

    Exclusive checkbox groups intentionally mark only the first option, while
    independent checkboxes may all be checked. This mirrors the generated form
    more closely than calling ``sample_value`` independently for every field.
    """

    values: dict[str, Any] = {}
    exclusive_groups: dict[str, list[str]] = {}
    for field in fields:
        field_id = str(field.get("id", "")).strip()
        if not field_id:
            continue
        field_type = infer_field_type(field_id, str(field.get("type", "text")))
        if field_type == "checkbox":
            group = str(field.get("group", "")).strip()
            single = str(field.get("selection", "")).casefold() in {
                "single", "exclusive", "radio"
            } or bool(field.get("choice_required"))
            if group and single:
                exclusive_groups.setdefault(group, []).append(field_id)
                values[field_id] = False
                continue
        values[field_id] = sample_value(field)

    for field_ids in exclusive_groups.values():
        if field_ids:
            values[field_ids[0]] = True
    return values
