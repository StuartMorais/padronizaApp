from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.document.semantic_ai.anchors import build_source_anchor, source_context
from app.document.semantic_ai.engine import LocalSemanticEngine, SEMANTIC_MODEL_VERSION
from app.document.semantic_ai.models import EvidenceAuthority


_VISUAL_CODES = {
    "formatting_prompt",
    "colored_choice",
    "red_text",
    "underline",
    "visual_spacing",
}
_SEMANTIC_CODES = {
    "label_agreement",
    "label_repaired",
    "label_disagreement",
    "type_support",
    "poor_label",
    "section_only",
}


def enrich_candidates_with_semantic_ai(
    candidates: list[dict[str, Any]],
    records: list[Any],
    *,
    engine: LocalSemanticEngine,
    family_fingerprint: str,
) -> list[dict[str, Any]]:
    by_ordinal = {int(getattr(record, "ordinal", -1)): record for record in records}
    enriched: list[dict[str, Any]] = []
    for raw in candidates:
        candidate = deepcopy(raw)
        context = source_context(candidate, records)
        nearby = " ".join(
            part for part in (
                str(context.get("before", "")),
                str(context.get("target", "")),
                str(context.get("after", "")),
            ) if part
        )
        if not nearby:
            record = by_ordinal.get(_first_ordinal(candidate))
            nearby = str(getattr(record, "text", "") or "") if record is not None else ""
        prediction = engine.analyze_candidate(
            candidate,
            nearby_text=nearby,
            family_fingerprint=family_fingerprint,
        )
        candidate["semantic_prediction"] = prediction.as_dict()
        candidate["semantic_model_version"] = SEMANTIC_MODEL_VERSION
        candidate["semantic_fillable_probability"] = prediction.fillable_probability
        candidate["semantic_concept_confidence"] = prediction.concept_confidence
        candidate["semantic_learned_similarity"] = prediction.learned_similarity
        candidate["family_fingerprint"] = family_fingerprint
        if prediction.concept_id and not candidate.get("semantic_concept_id"):
            candidate["semantic_concept_id"] = prediction.concept_id
        if prediction.suggested_label:
            candidate["semantic_ai_label_suggestion"] = prediction.suggested_label
        if prediction.suggested_type:
            candidate["semantic_ai_type_suggestion"] = prediction.suggested_type
        if context:
            candidate["source_context"] = context
        candidate["source_anchor"] = build_source_anchor(
            candidate,
            records,
            family_fingerprint=family_fingerprint,
        )

        evidence = [dict(item) for item in candidate.get("evidence", []) or [] if isinstance(item, dict)]
        for item in evidence:
            item.setdefault("authority", _authority_for_existing(item, candidate).value)
        for reason in prediction.reasons:
            evidence.append(
                {
                    "code": "semantic_ai",
                    "weight": round((prediction.concept_confidence - 0.5) * 0.12, 3),
                    "description": reason,
                    "authority": EvidenceAuthority.SEMANTIC.value,
                }
            )
        candidate["evidence"] = evidence

        dimensions = dict(candidate.get("confidence_dimensions", {}) or {})
        structural_fillable = float(dimensions.get("fillable", candidate.get("confidence", 0.0)) or 0.0)
        if bool(candidate.get("semantic_discovery", False)):
            # Semantic-discovery candidates have no traditional blank, so their
            # fillability dimension necessarily comes from semantic evidence.
            dimensions["fillable"] = round(prediction.fillable_probability, 3)
        elif prediction.fillable_probability + 0.16 < structural_fillable:
            # AI may conservatively reduce confidence / escalate review. It may
            # not silently promote an ordinary candidate into auto-apply.
            dimensions["fillable"] = round(
                max(0.0, min(structural_fillable, prediction.fillable_probability + 0.08)),
                3,
            )
            candidate["semantic_forces_review"] = True
        # Strong structural/specialized detections remain authoritative. A
        # lightweight semantic model must not veto a real checkbox, date mask,
        # explicit choice, table structure, or native control merely because
        # vocabulary happens to resemble another concept. Semantic disagreement
        # escalates only weak/ambiguous structural candidates.
        source = str(candidate.get("source", ""))
        weak_semantic_sources = {
            "instruction",
            "prefilled_text",
            "consistency_repair",
            "colored_prompt",
            "terminal_prompt",
            "semantic_inline",
            "semantic_prose",
            "repeatable_list",
        }
        structure_strength = float(dimensions.get("structure", 0.0) or 0.0)
        if prediction.forces_review and (
            bool(candidate.get("semantic_discovery", False))
            or source in weak_semantic_sources
            or structure_strength < 0.78
        ):
            candidate["semantic_forces_review"] = True
        candidate["confidence_dimensions"] = dimensions

        review_reasons = [str(value) for value in candidate.get("review_reasons", []) or [] if str(value).strip()]
        if candidate.get("semantic_forces_review"):
            message = "A análise semântica encontrou uma divergência que precisa de confirmação humana."
            if message not in review_reasons:
                review_reasons.append(message)
        candidate["review_reasons"] = review_reasons
        enriched.append(candidate)
    return enriched


def _authority_for_existing(item: dict[str, Any], candidate: dict[str, Any]) -> EvidenceAuthority:
    code = str(item.get("code", ""))
    if code in _VISUAL_CODES:
        return EvidenceAuthority.VISUAL_HINT
    if code in _SEMANTIC_CODES:
        return EvidenceAuthority.SEMANTIC
    source = str(candidate.get("source", ""))
    if source in {"semantic_inline", "semantic_prose", "repeatable_list", "learned_mapping"}:
        return EvidenceAuthority.SEMANTIC
    return EvidenceAuthority.STRUCTURAL


def _first_ordinal(candidate: dict[str, Any]) -> int:
    location = dict(candidate.get("location", {}) or {})
    if "paragraph" in location:
        try:
            return int(location["paragraph"])
        except (TypeError, ValueError):
            return -1
    values = list(location.get("paragraphs", []) or [])
    if not values and str(location.get("kind", "")) == "text_spans":
        values = [span.get("paragraph") for span in location.get("spans", []) or [] if isinstance(span, dict)]
    try:
        return min(int(value) for value in values)
    except (TypeError, ValueError):
        return -1
