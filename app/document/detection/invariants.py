from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.document.detection.structure import DocumentStructure, StoryZone


@dataclass(frozen=True)
class CandidateIssue:
    severity: str
    code: str
    message: str
    field_id: str = ""


def apply_candidate_invariants(
    candidates: list[dict[str, Any]],
    structure: DocumentStructure,
) -> tuple[list[dict[str, Any]], list[CandidateIssue]]:
    """Enforce scanner invariants without hiding ambiguous problems.

    The detector should prefer a reviewable omission/warning to a confidently
    broken form.  Severe candidate inconsistencies are therefore deselected and
    marked for required review instead of being silently written into the DOCX.
    """

    issues: list[CandidateIssue] = []
    seen_ids: dict[str, dict[str, Any]] = {}
    result: list[dict[str, Any]] = []

    for raw in candidates:
        candidate = dict(raw)
        field_id = str(candidate.get("field_id", "")).strip()
        location = dict(candidate.get("location", {}) or {})
        ordinal = _first_ordinal(location)
        owner = structure.owner_for(ordinal) if ordinal >= 0 else None

        if owner is not None and owner.zone is StoryZone.BODY and not str(candidate.get("section", "")).strip():
            if owner.section:
                candidate["section"] = owner.section
            else:
                _mark_review(
                    candidate,
                    "Não foi possível vincular este campo a uma seção estrutural.",
                    required=False,
                )
                issues.append(CandidateIssue("warning", "missing_section", "Campo sem seção estrutural forte.", field_id))

        if field_id:
            previous = seen_ids.get(field_id)
            if previous is not None:
                _mark_review(
                    candidate,
                    f"O ID '{field_id}' também foi produzido por outra sugestão.",
                    required=True,
                )
                _mark_review(
                    previous,
                    f"O ID '{field_id}' também foi produzido por outra sugestão.",
                    required=True,
                )
                issues.append(CandidateIssue("error", "duplicate_id", f"ID automático duplicado: {field_id}", field_id))
            else:
                seen_ids[field_id] = candidate

        if str(candidate.get("source", "")) == "repeatable_table":
            column_ids = [
                str(column.get("id", "")).strip()
                for column in candidate.get("columns", []) or []
                if isinstance(column, dict) and str(column.get("type", "")).casefold() != "auto_number"
            ]
            duplicates = sorted({value for value in column_ids if value and column_ids.count(value) > 1})
            if duplicates:
                _mark_review(
                    candidate,
                    "A tabela repetível possui IDs de coluna duplicados: " + ", ".join(duplicates),
                    required=True,
                )
                issues.append(CandidateIssue("error", "duplicate_table_column", "IDs repetidos na tabela: " + ", ".join(duplicates), field_id))

        if owner is not None and owner.protected and ordinal not in structure.protected_ordinals:
            # Defensive only; current structure extraction already records these
            # ordinals. Keep the invariant explicit for future owner types.
            _mark_review(candidate, "A região possui conteúdo manual protegido.", required=True)
            issues.append(CandidateIssue("error", "protected_region", "Sugestão sobrepõe região protegida.", field_id))

        result.append(candidate)

    return result, issues


def _mark_review(candidate: dict[str, Any], reason: str, *, required: bool) -> None:
    reasons = [str(value) for value in candidate.get("review_reasons", []) or [] if str(value).strip()]
    if reason not in reasons:
        reasons.append(reason)
    candidate["review_reasons"] = reasons
    candidate["needs_review"] = True
    if required:
        candidate["review_priority"] = "required"
        candidate["selected"] = False
        candidate["review_summary"] = "Revisão necessária antes de aplicar."
    elif candidate.get("review_priority") == "ready":
        candidate["review_priority"] = "recommended"
        candidate["review_summary"] = "Revisão rápida recomendada."


def _first_ordinal(location: dict[str, Any]) -> int:
    if "paragraph" in location:
        try:
            return int(location.get("paragraph", -1))
        except (TypeError, ValueError):
            return -1
    values = list(location.get("paragraphs", []) or location.get("owned_paragraphs", []) or [])
    if not values and str(location.get("kind", "")) == "text_spans":
        values = [
            span.get("paragraph")
            for span in location.get("spans", []) or []
            if isinstance(span, dict)
        ]
    try:
        return min(int(value) for value in values)
    except (TypeError, ValueError):
        return -1
