from __future__ import annotations

from typing import Any, Iterable


DETECTION_PIPELINE_VERSION = 6
AUTO_APPLY_READY_CONFIDENCE = 0.85
AUTO_APPLY_RECOMMENDED_CONFIDENCE = 0.92
AUTO_APPLY_DIMENSION_MINIMUMS = {
    "structure": 0.70,
    "fillable": 0.65,
    "label": 0.45,
    "type": 0.50,
}

# These heuristics intentionally infer author intent from prose/formatting. They
# are useful discoveries, but should never be preselected in an untagged scan.
REVIEW_ONLY_SOURCES = {
    "instruction",
    "prefilled_text",
    "consistency_repair",
    "colored_prompt",
    "colored_choice_block",
    "colored_visual_field",
    "instruction_placeholder",
    "generic_labeled_value",
    "generic_choice",
    "visual_field",
    "visual_choice",
    "semantic_inline",
    "semantic_prose",
    "repeatable_list",
}


def apply_review_first_policy(
    candidates: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Separate broad discovery from conservative automatic application.

    Strong masks, cells, checkbox groups and structural tables can remain
    preselected.  Heuristics that reinterpret prose or formatting stay visible
    but unchecked so an untagged scan cannot silently rewrite ambiguous text.
    """

    prepared: list[dict[str, Any]] = []
    for raw in candidates:
        candidate = dict(raw)
        reasons: list[str] = []
        confidence = float(candidate.get("confidence", 0.0) or 0.0)
        priority = str(candidate.get("review_priority", ""))
        source = str(candidate.get("source", ""))
        dimensions = dict(candidate.get("confidence_dimensions", {}) or {})

        if bool(candidate.get("requires_configuration", False)):
            reasons.append("Requer configuração manual antes de ser aplicado.")
        if priority == "required":
            reasons.append("A análise estrutural exige revisão antes da aplicação.")
        if source in REVIEW_ONLY_SOURCES:
            reasons.append(
                "Este campo foi inferido a partir do conteúdo do documento e exige confirmação humana."
            )
        if bool(candidate.get("semantic_forces_review", False)):
            reasons.append("A análise semântica encontrou uma divergência que precisa de confirmação.")

        minimum_confidence = (
            AUTO_APPLY_RECOMMENDED_CONFIDENCE
            if priority == "recommended"
            else AUTO_APPLY_READY_CONFIDENCE
        )
        if confidence < minimum_confidence:
            reasons.append(
                f"Confiança {confidence:.0%} abaixo do limite de aplicação "
                f"de {minimum_confidence:.0%}."
            )

        for dimension, minimum in AUTO_APPLY_DIMENSION_MINIMUMS.items():
            value = float(dimensions.get(dimension, 0.0) or 0.0)
            if value < minimum:
                reasons.append(
                    f"Evidência de {dimension} insuficiente ({value:.0%} < {minimum:.0%})."
                )

        invariant_issues = candidate.get("scanner_invariant_issues", []) or []
        if any(
            isinstance(issue, dict) and str(issue.get("severity", "")) == "error"
            for issue in invariant_issues
        ):
            reasons.append("Existe uma violação estrutural que exige revisão.")

        # A location previously approved by the author in the same template
        # family is the only semantic source allowed to become preselected.
        # It is deterministic memory, not a fresh AI guess.
        if source == "learned_mapping" and not bool(candidate.get("requires_configuration", False)):
            reasons = [reason for reason in reasons if "Confiança" not in reason and "Evidência" not in reason]

        eligible = not reasons
        candidate["pipeline_version"] = DETECTION_PIPELINE_VERSION
        candidate["selection_policy_version"] = 2
        candidate["auto_apply_eligible"] = eligible
        candidate["auto_apply_reasons"] = reasons
        candidate["selected"] = eligible
        prepared.append(candidate)
    return prepared
