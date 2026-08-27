from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from app.document.semantic_ai.catalog import BUILTIN_CONCEPTS
from app.document.semantic_ai.models import SemanticConcept, SemanticMemory, SemanticPrediction
from app.document.semantic_ai.vectorizer import cosine_similarity, embed_text, normalize_semantic_text


SEMANTIC_MODEL_VERSION = 1


@dataclass(frozen=True)
class _Prototype:
    concept: SemanticConcept
    vector: tuple[float, ...]


class LocalSemanticEngine:
    """Tiny, private, CPU-only semantic classifier/similarity engine.

    This intentionally avoids heavyweight LLM/PyTorch dependencies. It uses a
    multilingual-friendly hashed word/character representation, curated
    Portuguese administrative prototypes, and locally learned reviewed
    examples. The result is evidence; it never mutates a document.
    """

    def __init__(self, memory: dict[str, Any] | None = None) -> None:
        self.memory = SemanticMemory.from_value(memory)
        self._prototypes = tuple(
            _Prototype(concept, self._concept_vector(concept))
            for concept in BUILTIN_CONCEPTS
        )

    def analyze_candidate(
        self,
        candidate: dict[str, Any],
        *,
        nearby_text: str = "",
        family_fingerprint: str = "",
    ) -> SemanticPrediction:
        label = str(candidate.get("label", "") or "")
        section = str(candidate.get("section", "") or "")
        preview = str(candidate.get("preview", "") or "")
        text = " | ".join(value for value in (label, section, nearby_text, preview) if value)
        concept, similarity = self._best_concept(text)
        learned_similarity, learned = self._best_learned_match(
            text,
            family_fingerprint=family_fingerprint,
            candidate=candidate,
        )

        original_type = str(candidate.get("type", "text") or "text")
        suggested_type = concept.field_type if concept and similarity >= 0.31 else original_type
        type_confidence = max(0.55, min(0.98, similarity + 0.36)) if concept else 0.55
        label_confidence = max(0.50, min(0.99, similarity + 0.34)) if concept else 0.50
        suggested_label = concept.label if concept and similarity >= 0.30 else label

        structural_fillable = float(candidate.get("confidence", 0.0) or 0.0)
        prior = concept.fillable_prior if concept else 0.55
        fillable = 0.55 * structural_fillable + 0.45 * prior
        reasons: list[str] = []
        forces_review = False

        if concept and similarity >= 0.30:
            reasons.append(
                f"Semântica local corresponde a '{concept.label}' ({similarity:.0%})."
            )
        if learned is not None:
            accepted = bool(learned.get("accepted", False))
            if accepted:
                fillable = max(fillable, 0.72 + 0.25 * learned_similarity)
                reasons.append("Uma revisão anterior desta família de modelo aprovou conteúdo semelhante.")
            else:
                fillable = min(fillable, 0.45)
                forces_review = True
                reasons.append("Uma revisão anterior desta família manteve conteúdo semelhante como texto fixo.")

        if concept and original_type != suggested_type and similarity >= 0.58:
            forces_review = True
            reasons.append(
                f"O tipo estrutural '{original_type}' diverge do tipo semântico '{suggested_type}'."
            )

        return SemanticPrediction(
            fillable_probability=max(0.0, min(fillable, 1.0)),
            suggested_type=suggested_type,
            type_confidence=type_confidence,
            suggested_label=suggested_label,
            label_confidence=label_confidence,
            concept_id=concept.concept_id if concept else "",
            concept_confidence=max(0.0, min(similarity, 1.0)),
            learned_similarity=max(0.0, min(learned_similarity, 1.0)),
            forces_review=forces_review,
            reasons=tuple(reasons),
            model_version=SEMANTIC_MODEL_VERSION,
        )

    def concept(self, concept_id: str) -> SemanticConcept | None:
        target = str(concept_id or "")
        for prototype in self._prototypes:
            if prototype.concept.concept_id == target:
                return prototype.concept
        return None

    def best_concept_for_text(self, text: str) -> tuple[SemanticConcept | None, float]:
        return self._best_concept(text)

    def _best_concept(self, text: str) -> tuple[SemanticConcept | None, float]:
        vector = embed_text(text)
        best: SemanticConcept | None = None
        best_score = 0.0
        normalized = normalize_semantic_text(text)
        for prototype in self._prototypes:
            score = cosine_similarity(vector, prototype.vector)
            # Exact aliases/prototype phrases are very strong evidence and help
            # short Portuguese labels where generic vector similarity is noisy.
            for phrase in (*prototype.concept.examples, *prototype.concept.aliases):
                normalized_phrase = normalize_semantic_text(phrase)
                if normalized_phrase and normalized_phrase in normalized:
                    score = max(score, 0.94 if len(normalized_phrase) >= 7 else 0.82)
            if score > best_score:
                best = prototype.concept
                best_score = score
        return best, max(0.0, min(best_score, 1.0))

    def _best_learned_match(
        self,
        text: str,
        *,
        family_fingerprint: str,
        candidate: dict[str, Any],
    ) -> tuple[float, dict[str, Any] | None]:
        vector = embed_text(text)
        best_score = 0.0
        best: dict[str, Any] | None = None
        candidate_location = str(candidate.get("location_signature", "") or "")
        for review in self.memory.reviews:
            review_family = str(review.get("family_fingerprint", "") or "")
            if family_fingerprint and review_family and review_family != family_fingerprint:
                continue
            if candidate_location and str(review.get("location_signature", "")) == candidate_location:
                score = 1.0
            else:
                example = " | ".join(
                    str(review.get(key, "") or "")
                    for key in ("label", "section", "semantic_context")
                )
                score = cosine_similarity(vector, embed_text(example)) if example.strip(" |") else 0.0
            if score > best_score:
                best_score = score
                best = review
        return best_score, best

    @staticmethod
    def _concept_vector(concept: SemanticConcept) -> tuple[float, ...]:
        return embed_text(" | ".join((concept.label, *concept.examples, *concept.aliases)))
