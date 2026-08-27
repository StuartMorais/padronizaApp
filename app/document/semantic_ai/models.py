from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EvidenceAuthority(str, Enum):
    """Authority tier for scanner evidence.

    Higher-authority evidence is allowed to constrain lower-authority evidence.
    Semantic evidence can explain/refine structure, but cannot override an
    authoritative Word/PDF/Padroniza field representation.
    """

    AUTHORITATIVE = "authoritative"
    STRUCTURAL = "structural"
    SEMANTIC = "semantic"
    VISUAL_HINT = "visual_hint"


@dataclass(frozen=True)
class SemanticConcept:
    concept_id: str
    label: str
    field_type: str
    examples: tuple[str, ...]
    fillable_prior: float = 0.75
    preferred_scope: str = "inline"
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class SemanticPrediction:
    fillable_probability: float
    suggested_type: str
    type_confidence: float
    suggested_label: str
    label_confidence: float
    concept_id: str = ""
    concept_confidence: float = 0.0
    learned_similarity: float = 0.0
    forces_review: bool = False
    reasons: tuple[str, ...] = ()
    model_version: int = 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "fillable_probability": round(float(self.fillable_probability), 4),
            "suggested_type": str(self.suggested_type),
            "type_confidence": round(float(self.type_confidence), 4),
            "suggested_label": str(self.suggested_label),
            "label_confidence": round(float(self.label_confidence), 4),
            "concept_id": str(self.concept_id),
            "concept_confidence": round(float(self.concept_confidence), 4),
            "learned_similarity": round(float(self.learned_similarity), 4),
            "forces_review": bool(self.forces_review),
            "reasons": list(self.reasons),
            "model_version": int(self.model_version),
        }


@dataclass
class SemanticMemory:
    """Serializable review-memory snapshot consumed by the document layer."""

    reviews: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_value(cls, value: Any) -> "SemanticMemory":
        if not isinstance(value, dict):
            return cls()
        reviews = [
            dict(item)
            for item in value.get("reviews", []) or []
            if isinstance(item, dict)
        ]
        return cls(reviews=reviews)
