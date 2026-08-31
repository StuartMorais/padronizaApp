from __future__ import annotations

from app.document.detection.presentation import (
    candidate_display_label,
    candidate_document_excerpt,
)


def test_review_display_keeps_specific_human_label() -> None:
    candidate = {
        "field_id": "procurement.items",
        "label": "Materiais / itens",
        "preview": ["Cadernos", "Canetas hidrográficas", "Pilhas"],
    }
    assert candidate_display_label(candidate) == "Materiais / itens"
    assert candidate_document_excerpt(candidate) == "Cadernos; Canetas hidrográficas; Pilhas"


def test_review_display_does_not_expose_python_list_repr() -> None:
    candidate = {
        "field_id": "procurement.items",
        "label": "Materiais / itens",
        "preview": "['Cadernos', 'Canetas hidrográficas', 'Pilhas']",
    }
    excerpt = candidate_document_excerpt(candidate)
    assert excerpt == "Cadernos; Canetas hidrográficas; Pilhas"
    assert "[" not in excerpt
    assert "'" not in excerpt


def test_generic_detection_uses_nearby_document_label() -> None:
    candidate = {
        "field_id": "auto.responsavel_fiscalizacao",
        "label": "Texto editável",
        "preview": "Maria da Silva",
        "source_context": {
            "before": "Responsável pela fiscalização: ",
            "target": "Maria da Silva",
            "after": "",
        },
    }
    assert candidate_display_label(candidate) == "Responsável pela fiscalização"
    assert candidate_document_excerpt(candidate) == "Maria da Silva"


def test_technical_id_is_last_resort_not_primary_review_name() -> None:
    candidate = {
        "field_id": "auto.unidade_requisitante",
        "label": "auto.unidade_requisitante",
        "preview": "SEAD/PB",
    }
    assert candidate_display_label(candidate) == "Unidade requisitante"
    assert candidate_document_excerpt(candidate) == "SEAD/PB"
