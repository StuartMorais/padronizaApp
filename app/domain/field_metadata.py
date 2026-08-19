from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from app.domain.field_types import FIELD_TYPE_ALIASES

EDITOR_PRESERVED_METADATA_KEYS = (
    "tag_type",
    "layout_order",
    "layout_static_rows",
    "layout_row_static_cells",
    "layout_row_header_label",
    "layout_presentation",
    "layout_position_locked",
    "label_source",
    "section_source",
    "type_source",
    "validation_hint",
    "format_hint",
    "placeholder",
    "default_value",
    "example",
    "detection_source",
    "detection_confidence",
    "detection_confidence_band",
    "detection_evidence",
    "detection_review_priority",
    "detection_review_reasons",
    "detection_needs_review",
    "detection_reviewed",
    "detector_version",
    "choice_group_label",
    "compact_choice",
    "choice_required",
    "context_evidence",
    "context_confidence",
    "context_resolver_version",
    "id_source",
    "auto_tagged",
    "profile_identity",
    "context_needs_review",
    "context_review_reason",
)


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
    if bool(field.get("auto_tagged", False)):
        return True
    if str(field.get("id_source", "")).strip().casefold() == "context_resolver":
        return True
    return str(field.get("id", "")).strip().casefold().startswith("auto.")


def uses_assisted_detection(fields: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> bool:
    """Return True when at least one field originated from assisted detection."""

    return any(is_assisted_detection_field(field) for field in fields)


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


def _normalized_dropdown_option_records(value: Any) -> list[dict[str, str]]:
    """Normalize dropdown syntax while intentionally preserving duplicates."""
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
        if not output:
            continue
        result.append({"label": label or output, "value": output})
    return result


def normalize_dropdown_options(value: Any) -> list[dict[str, str]]:
    """Normalize simple or structured dropdown choices.

    A string remains a regular option. A mapping may provide a short visible
    label and a different, potentially long, value inserted into the DOCX.
    The compact text syntax ``Título => texto completo`` is also accepted.
    Runtime consumers receive unique output values; diagnostics can use
    :func:`raw_dropdown_option_values` to detect accidental duplicates first.
    """
    result: list[dict[str, str]] = []
    seen_values: set[str] = set()
    for option in _normalized_dropdown_option_records(value):
        output = option["value"]
        if output in seen_values:
            continue
        seen_values.add(output)
        result.append(option)
    return result


def raw_dropdown_option_values(value: Any) -> list[str]:
    """Return normalized dropdown output values without removing duplicates."""
    return [option["value"] for option in _normalized_dropdown_option_records(value)]


def raw_repeatable_column_ids(value: Any) -> list[str]:
    """Return configured repeatable-column IDs while preserving duplicates."""
    if not isinstance(value, (list, tuple)):
        return []
    return [
        str(column.get("id", "")).strip()
        for column in value
        if isinstance(column, dict) and str(column.get("id", "")).strip()
    ]


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
