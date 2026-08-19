from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Iterable

from app.domain.fields import FieldDefinition
from app.domain.field_metadata import compact_dropdown_options
from app.document.detection.models import CandidateDefinition
from app.document.detection.patterns import _SOURCE_LABELS


def _normalize_space(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def candidate_field_definitions(
    candidates: Iterable[dict[str, Any]],
) -> list[FieldDefinition]:
    """Convert approved candidates to normal editable field definitions."""

    fields: list[FieldDefinition] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        if str(candidate.get("source", "")) == "repeatable_table":
            field_id = str(candidate.get("field_id", "")).strip()
            if not field_id:
                continue
            fields.append(
                FieldDefinition({
                    "id": field_id,
                    "label": str(candidate.get("label", "")).strip() or field_id,
                    "type": "repeatable_table",
                    "columns": [
                        dict(column)
                        for column in candidate.get("columns", []) or []
                        if isinstance(column, dict)
                    ],
                    "minimum_rows": 1,
                    "numbering_padding": 2,
                    "required": True,
                    "label_source": "automatic_detection",
                    "type_source": "automatic_detection",
                    "detection_source": "automatic",
                    "detection_confidence": float(candidate.get("confidence", 0.0)),
                    "detection_confidence_band": str(candidate.get("confidence_band", "")),
                    "detection_evidence": deepcopy(candidate.get("evidence", []) or []),
                    "detection_review_priority": str(candidate.get("review_priority", "")),
                    "detection_review_reasons": deepcopy(candidate.get("review_reasons", []) or []),
                    "detection_needs_review": bool(candidate.get("needs_review", False)),
                    "detection_reviewed": bool(candidate.get("reviewed_by_user", False)),
                    "detector_version": int(candidate.get("detector_version", 1) or 1),
                    "full_width": True,
                })
            )
            if str(candidate.get("section", "")).strip():
                fields[-1]["section"] = str(candidate.get("section", "")).strip()
            continue
        if str(candidate.get("source", "")) == "checkbox_choice":
            for raw_field in candidate.get("fields", []) or []:
                field = dict(raw_field)
                field.setdefault("required", False)
                field.setdefault("label_source", "automatic_detection")
                field.setdefault("type_source", "automatic_detection")
                field["detection_source"] = "automatic"
                field["detection_confidence"] = float(candidate.get("confidence", 0.0))
                field["detection_confidence_band"] = str(candidate.get("confidence_band", ""))
                field["detection_evidence"] = deepcopy(candidate.get("evidence", []) or [])
                field["detection_review_priority"] = str(candidate.get("review_priority", ""))
                field["detection_review_reasons"] = deepcopy(candidate.get("review_reasons", []) or [])
                field["detection_needs_review"] = bool(candidate.get("needs_review", False))
                field["detection_reviewed"] = bool(candidate.get("reviewed_by_user", False))
                field["detector_version"] = int(candidate.get("detector_version", 1) or 1)
                fields.append(FieldDefinition(field))
            continue

        field_id = str(candidate.get("field_id", "")).strip()
        if not field_id:
            continue
        field: dict[str, Any] = {
            "id": field_id,
            "label": str(candidate.get("label", "")).strip(),
            "type": str(candidate.get("type", "text")).strip() or "text",
            "required": str(candidate.get("type", "text")) != "checkbox",
            "label_source": "automatic_detection",
            "type_source": "automatic_detection",
            "detection_source": "automatic",
            "detection_confidence": float(candidate.get("confidence", 0.0)),
            "detection_confidence_band": str(candidate.get("confidence_band", "")),
            "detection_evidence": deepcopy(candidate.get("evidence", []) or []),
            "detection_review_priority": str(candidate.get("review_priority", "")),
            "detection_review_reasons": deepcopy(candidate.get("review_reasons", []) or []),
            "detection_needs_review": bool(candidate.get("needs_review", False)),
            "detection_reviewed": bool(candidate.get("reviewed_by_user", False)),
            "detector_version": int(candidate.get("detector_version", 1) or 1),
        }
        options = compact_dropdown_options(candidate.get("options", []))
        if options:
            field["options"] = options
        placeholder = str(candidate.get("placeholder", "")).strip()
        if placeholder:
            field["placeholder"] = placeholder
        if "default_value" in candidate:
            field["default_value"] = deepcopy(candidate.get("default_value"))
        if str(candidate.get("layout", "")) == "choice":
            group = str(candidate.get("layout_group", f"auto_choice_{field_id}"))
            field.update(
                {
                    "layout": "choice",
                    "layout_group": group,
                    "layout_group_label": field["label"],
                    "group": group,
                    "selection": "single",
                    "choice_required": True,
                    "tag_type": "single_choice",
                }
            )
        # Automatically detected dates represent visible fill areas in the
        # source document (for example ``Data: __/__/____``). They must stay
        # editable instead of being silently replaced with today's date.
        if field["type"] == "date":
            field["automatic"] = False
        if field["type"] == "multiline":
            field["full_width"] = True
        fields.append(FieldDefinition(field))
    return fields


def candidate_source_label(candidate: dict[str, Any]) -> str:
    return _SOURCE_LABELS.get(
        str(candidate.get("source", "")),
        "Sugestão automática",
    )


def _candidate(
    *,
    field_id: str,
    label: str,
    field_type: str,
    confidence: float,
    source: str,
    preview: str,
    location: dict[str, Any],
    options: Iterable[Any] | None = None,
    default_selected: bool | None = None,
    requires_configuration: bool = False,
    layout: str = "",
    layout_group: str = "",
    placeholder: str = "",
    default_value: Any | None = None,
) -> dict[str, Any]:
    confidence = max(0.0, min(float(confidence), 1.0))
    if default_selected is None:
        default_selected = confidence >= 0.80 and not requires_configuration
    result: CandidateDefinition = CandidateDefinition({
        "field_id": field_id,
        "label": _normalize_space(label) or field_id,
        "type": field_type,
        "confidence": confidence,
        "source": source,
        "preview": _normalize_space(preview)[:420],
        "location": dict(location),
        "selected": bool(default_selected),
        "requires_configuration": bool(requires_configuration),
    })
    cleaned_options = compact_dropdown_options(options or [])
    if cleaned_options:
        result["options"] = cleaned_options
    if layout:
        result["layout"] = layout
    if layout_group:
        result["layout_group"] = layout_group
    if str(placeholder).strip():
        result["placeholder"] = str(placeholder).strip()
    if default_value is not None:
        result["default_value"] = deepcopy(default_value)
    return result

