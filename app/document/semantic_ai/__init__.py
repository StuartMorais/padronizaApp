"""Local semantic assistance for Padroniza's review-first scanner.

The semantic layer never edits DOCX/PDF structures directly. It produces
semantic evidence and additional review candidates that are applied later by
Padroniza's deterministic document engine only after human approval.
"""

from app.document.semantic_ai.engine import LocalSemanticEngine, SEMANTIC_MODEL_VERSION
from app.document.semantic_ai.models import EvidenceAuthority, SemanticPrediction

__all__ = [
    "EvidenceAuthority",
    "LocalSemanticEngine",
    "SEMANTIC_MODEL_VERSION",
    "SemanticPrediction",
]
