from app.section_card_model import (
    build_section_card_models,
    rename_section_fields,
    reorder_section_fields,
)


def _fields():
    return [
        {
            "id": "setor.nome",
            "label": "Setor Requisitante",
            "type": "text",
            "section": "1. Área Requisitante",
            "layout": "form_grid",
            "layout_group": "area",
            "layout_group_label": "Área Requisitante",
        },
        {
            "id": "responsavel.nome",
            "label": "Responsável pela Demanda",
            "type": "text",
            "section": "1. Área Requisitante",
            "layout": "form_grid",
            "layout_group": "area",
            "layout_group_label": "Área Requisitante",
        },
        {
            "id": "descricao.demanda",
            "label": "Descrição da demanda",
            "type": "multiline",
            "section": "2. Descrição da Demanda",
            "layout": "full_width",
        },
        {
            "id": "prioridade",
            "label": "Grau de Prioridade",
            "type": "dropdown",
            "section": "7. Grau de Prioridade",
            "layout": "choice",
            "layout_group": "prioridade",
        },
    ]


def test_build_section_cards_groups_semantic_layouts() -> None:
    cards = build_section_card_models(_fields())

    assert [card["title"] for card in cards] == [
        "1. Área Requisitante",
        "2. Descrição da Demanda",
        "7. Grau de Prioridade",
    ]
    assert cards[0]["field_count"] == 2
    assert cards[0]["entries"][0]["kind"] == "group"
    assert cards[0]["entries"][0]["title"] == "Grade do documento · Área Requisitante"
    assert [field["id"] for field in cards[0]["entries"][0]["fields"]] == [
        "setor.nome",
        "responsavel.nome",
    ]
    assert cards[1]["entries"][0]["field"]["layout_label"] == "Largura total"


def test_reorder_section_moves_whole_block() -> None:
    moved = reorder_section_fields(_fields(), "2. Descrição da Demanda", -1)
    assert [field["id"] for field in moved] == [
        "descricao.demanda",
        "setor.nome",
        "responsavel.nome",
        "prioridade",
    ]


def test_rename_section_changes_only_matching_fields() -> None:
    renamed = rename_section_fields(_fields(), "1. Área Requisitante", "1. Solicitante")
    assert [field["section"] for field in renamed[:2]] == ["1. Solicitante", "1. Solicitante"]
    assert renamed[2]["section"] == "2. Descrição da Demanda"


def test_card_search_text_contains_labels_and_ids() -> None:
    cards = build_section_card_models(_fields())
    assert "responsável pela demanda" in cards[0]["search_text"]
    assert "responsavel.nome" in cards[0]["search_text"]
