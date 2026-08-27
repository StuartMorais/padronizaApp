from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable

from app.domain.field_ids import VALID_FIELD_ID
from app.domain.field_metadata import (
    DYNAMIC_SCOPES,
    dropdown_option_values,
    normalize_repeatable_columns,
    raw_dropdown_option_values,
    raw_repeatable_column_ids,
    repeatable_list_errors,
    source_anchor_errors,
)


@dataclass(frozen=True)
class FieldConfigurationIssue:
    row: int
    field_id: str
    severity: str
    code: str
    message: str


def field_configuration_issues(
    fields: Iterable[dict[str, Any]],
) -> list[FieldConfigurationIssue]:
    """Return fast, source-independent issues for the template field editor.

    This intentionally avoids opening/scanning the DOCX so it can run on every
    editor change without making typing feel slow. Full source-aware validation
    remains the responsibility of ``diagnose_template`` / template preflight.
    """

    values = [dict(field) for field in fields if isinstance(field, dict)]
    ids = [str(field.get("id", "")).strip() for field in values]
    id_counts = Counter(field_id for field_id in ids if field_id)
    known_ids = {field_id for field_id in ids if field_id}
    issues: list[FieldConfigurationIssue] = []

    def add(
        row: int,
        severity: str,
        code: str,
        message: str,
        *,
        field_id: str | None = None,
    ) -> None:
        issues.append(
            FieldConfigurationIssue(
                row=row,
                field_id=ids[row] if field_id is None else field_id,
                severity=severity,
                code=code,
                message=message,
            )
        )

    for row, field in enumerate(values):
        field_id = ids[row]
        label = str(field.get("label", "")).strip()
        field_type = str(field.get("type", "text") or "text").strip().casefold()

        if not field_id:
            add(row, "error", "field.id_missing", "Informe um ID para o campo.")
        elif not VALID_FIELD_ID.fullmatch(field_id):
            add(
                row,
                "error",
                "field.id_invalid",
                "O ID deve começar com uma letra e usar apenas letras, números, ponto, hífen ou sublinhado.",
            )
        elif id_counts[field_id] > 1:
            add(row, "error", "field.id_duplicate", "Este ID está repetido no modelo.")

        if not label:
            add(row, "error", "field.label_missing", "Informe um rótulo legível para o campo.")

        if field_type == "dropdown":
            options = dropdown_option_values(field.get("options", []))
            raw_options = raw_dropdown_option_values(field.get("options", []))
            if len(options) < 2:
                add(
                    row,
                    "error",
                    "dropdown.options_missing",
                    "A lista suspensa precisa de pelo menos duas opções.",
                )
            duplicates = sorted(
                {value for value in raw_options if raw_options.count(value) > 1}
            )
            if duplicates:
                add(
                    row,
                    "warning",
                    "dropdown.options_duplicate",
                    "Há opções repetidas: " + ", ".join(duplicates),
                )

        if field_type == "repeatable_table":
            columns = normalize_repeatable_columns(field.get("columns", []))
            raw_column_ids = raw_repeatable_column_ids(field.get("columns", []))
            if not columns:
                add(
                    row,
                    "error",
                    "table.columns_missing",
                    "Configure pelo menos uma coluna para a tabela repetível.",
                )
            else:
                duplicates = sorted(
                    {
                        column_id
                        for column_id in raw_column_ids
                        if raw_column_ids.count(column_id) > 1
                    }
                )
                if duplicates:
                    add(
                        row,
                        "error",
                        "table.columns_duplicate",
                        "IDs de coluna repetidos: " + ", ".join(duplicates),
                    )

        if field_type == "repeatable_list":
            for message in repeatable_list_errors(field):
                add(row, "error", "list.invalid", message.capitalize() + ".")

        dynamic_scope = str(field.get("dynamic_scope", "") or "").casefold()
        if dynamic_scope and dynamic_scope not in DYNAMIC_SCOPES:
            add(
                row,
                "error",
                "semantic.scope_invalid",
                "O escopo dinâmico do campo é inválido.",
            )
        for message in source_anchor_errors(
            field.get("source_anchor"),
            expected_scope=dynamic_scope,
        ):
            add(
                row,
                "error",
                "semantic.anchor_invalid",
                message.capitalize() + ".",
            )

        condition = field.get("visible_when")
        if condition:
            if not isinstance(condition, dict):
                add(
                    row,
                    "error",
                    "condition.invalid",
                    "A regra de visibilidade está em formato inválido.",
                )
            else:
                dependency = str(condition.get("field", "")).strip()
                if not dependency:
                    add(
                        row,
                        "error",
                        "condition.field_missing",
                        "A regra de visibilidade não informa o campo de origem.",
                    )
                elif dependency not in known_ids:
                    add(
                        row,
                        "error",
                        "condition.field_unknown",
                        f"A regra de visibilidade referencia o campo ausente '{dependency}'.",
                    )
                if not any(key in condition for key in ("equals", "not_equals", "truthy")):
                    add(
                        row,
                        "error",
                        "condition.comparison_missing",
                        "A regra de visibilidade não possui comparação.",
                    )

        detection_source = str(field.get("detection_source", "")).strip().casefold()
        if (
            detection_source in {"automatic", "assisted", "auto_detection"}
            and not bool(field.get("detection_reviewed", False))
        ):
            confidence = _float(field.get("detection_confidence"))
            band = str(field.get("detection_confidence_band", "")).strip().casefold()
            if band == "low" or (confidence is not None and confidence < 0.65):
                add(
                    row,
                    "warning",
                    "detection.low_confidence",
                    "Campo detectado automaticamente com baixa confiança; revise ID, rótulo e tipo.",
                )
            elif band == "medium" or (
                confidence is not None and confidence < 0.85
            ):
                add(
                    row,
                    "warning",
                    "detection.medium_confidence",
                    "Campo detectado automaticamente com confiança média; uma revisão rápida é recomendada.",
                )

    # Visibility rules form a small dependency graph. Detect cycles here so
    # authors get immediate feedback instead of discovering them only during
    # full source preflight.
    unique_rows = {
        field_id: row
        for row, field_id in enumerate(ids)
        if field_id and id_counts[field_id] == 1
    }
    dependencies: dict[str, str] = {}
    for row, field in enumerate(values):
        field_id = ids[row]
        condition = field.get("visible_when")
        if (
            field_id in unique_rows
            and isinstance(condition, dict)
            and str(condition.get("field", "")).strip() in unique_rows
        ):
            dependencies[field_id] = str(condition.get("field", "")).strip()

    cycle_ids: set[str] = set()
    visiting: list[str] = []
    state: dict[str, int] = {}

    def visit(field_id: str) -> None:
        current_state = state.get(field_id, 0)
        if current_state == 2:
            return
        if current_state == 1:
            if field_id in visiting:
                start = visiting.index(field_id)
                cycle_ids.update(visiting[start:])
            return
        state[field_id] = 1
        visiting.append(field_id)
        dependency = dependencies.get(field_id)
        if dependency:
            visit(dependency)
        visiting.pop()
        state[field_id] = 2

    for field_id in dependencies:
        visit(field_id)

    for field_id in sorted(cycle_ids):
        add(
            unique_rows[field_id],
            "error",
            "condition.cycle",
            "Esta regra de visibilidade participa de uma dependência circular.",
            field_id=field_id,
        )

    return issues


def issue_counts(issues: Iterable[FieldConfigurationIssue]) -> dict[str, int]:
    counts = {"error": 0, "warning": 0}
    for issue in issues:
        if issue.severity in counts:
            counts[issue.severity] += 1
    return counts


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
