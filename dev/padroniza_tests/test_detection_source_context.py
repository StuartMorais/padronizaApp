from __future__ import annotations

from types import SimpleNamespace

from app.document.semantic_ai.anchors import source_context


def _record(ordinal: int, text: str):
    return SimpleNamespace(ordinal=ordinal, text=text)


def test_source_context_uses_full_paragraph_for_paragraph_candidates() -> None:
    candidate = {"location": {"kind": "paragraph", "paragraph": 4}}
    context = source_context(candidate, [_record(4, "Processo: SDH-PRC-2026/03089")])
    assert context == {
        "before": "",
        "target": "Processo: SDH-PRC-2026/03089",
        "after": "",
    }


def test_source_context_keeps_all_lines_of_repeatable_list() -> None:
    candidate = {
        "location": {"kind": "paragraph_list", "paragraphs": [7, 8, 9]}
    }
    context = source_context(
        candidate,
        [
            _record(7, "• Cadernos;"),
            _record(8, "• Canetas hidrográficas;"),
            _record(9, "• Pilhas."),
        ],
    )
    assert context["target"] == "• Cadernos;\n• Canetas hidrográficas;\n• Pilhas."
