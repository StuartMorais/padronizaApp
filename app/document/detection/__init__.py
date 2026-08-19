"""Assisted field detection for untagged DOCX documents."""

from app.document.detection.application import apply_docx_field_candidates
from app.document.detection.candidates import candidate_field_definitions, candidate_source_label
from app.document.detection.detector import detect_docx_field_candidates
from app.document.detection.models import AutomaticDetectionError, CandidateDefinition

__all__ = [
    "AutomaticDetectionError",
    "CandidateDefinition",
    "apply_docx_field_candidates",
    "candidate_field_definitions",
    "candidate_source_label",
    "detect_docx_field_candidates",
]
