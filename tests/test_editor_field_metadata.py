from app.field_utils import preserved_editor_field_metadata


def test_preserves_embedded_choice_question_separately_from_section_layout_label():
    original = {
        "id": "auto.ha_impedimento_conhecido.sim",
        "label": "Sim",
        "layout": "form_grid",
        "layout_group_label": "3. Fundamentação complementar",
        "choice_group_label": "Há impedimento conhecido?",
        "choice_required": True,
        "compact_choice": True,
        "detection_source": "automatic",
        "detection_confidence": 0.92,
        "layout_row_header_label": "Pergunta",
        "layout_static_rows": [{"text": "Texto fixo"}],
    }

    kept = preserved_editor_field_metadata(original)

    assert kept["choice_group_label"] == "Há impedimento conhecido?"
    assert kept["choice_required"] is True
    assert kept["compact_choice"] is True
    assert kept["detection_source"] == "automatic"
    assert kept["layout_row_header_label"] == "Pergunta"
    # Layout-group configuration is owned by FieldLayoutEditor and should not
    # be silently frozen by the preservation helper.
    assert "layout_group_label" not in kept
    assert "layout" not in kept


def test_preserved_metadata_is_deep_copied():
    original = {"layout_static_rows": [{"text": "Original"}]}
    kept = preserved_editor_field_metadata(original)
    kept["layout_static_rows"][0]["text"] = "Alterado"
    assert original["layout_static_rows"][0]["text"] == "Original"


def test_assisted_detection_template_flag_uses_saved_field_metadata():
    from app.field_utils import uses_assisted_detection

    assert uses_assisted_detection([
        {"id": "manual", "type": "text"},
        {"id": "auto.nome", "type": "text", "detection_source": "automatic"},
    ]) is True
    assert uses_assisted_detection([
        {"id": "manual", "type": "text"},
    ]) is False
    # Backward compatibility for assisted models saved before detection_source
    # was preserved by repository normalization.
    assert uses_assisted_detection([
        {"id": "auto.campo_antigo", "type": "text"},
    ]) is True


def test_repository_keeps_detection_metadata_when_normalizing(tmp_path):
    from app.template_repository import TemplateRepository

    repository = TemplateRepository(tmp_path / "templates")
    fields = repository._normalize_fields(
        [
            {
                "id": "auto.nome",
                "label": "Nome",
                "type": "text",
                "detection_source": "automatic",
                "detection_confidence": 0.91,
                "choice_group_label": "Pergunta local?",
                "example": "Exemplo",
            }
        ],
        strict=True,
    )

    assert fields[0]["detection_source"] == "automatic"
    assert fields[0]["detection_confidence"] == 0.91
    assert fields[0]["choice_group_label"] == "Pergunta local?"
    assert fields[0]["example"] == "Exemplo"


def test_prefilled_default_value_survives_editor_and_repository_normalization(tmp_path):
    from app.template_repository import TemplateRepository

    original = {
        "id": "auto.justificativa",
        "label": "Justificativa",
        "type": "multiline",
        "default_value": "Texto já existente no documento.",
        "detection_source": "automatic",
    }
    kept = preserved_editor_field_metadata(original)
    assert kept["default_value"] == "Texto já existente no documento."

    repository = TemplateRepository(tmp_path / "templates")
    fields = repository._normalize_fields([original], strict=True)
    assert fields[0]["default_value"] == "Texto já existente no documento."


def test_context_autotagged_word_control_is_treated_as_assisted_detection() -> None:
    from app.field_utils import is_assisted_detection_field

    assert is_assisted_detection_field(
        {
            "id": "prioridade",
            "type": "dropdown",
            "auto_tagged": True,
            "id_source": "context_resolver",
        }
    ) is True


def test_context_resolver_metadata_survives_editor_and_repository(tmp_path) -> None:
    from app.template_repository import TemplateRepository

    original = {
        "id": "prioridade",
        "label": "Prioridade",
        "type": "dropdown",
        "options": ["Normal", "Alta"],
        "auto_tagged": True,
        "id_source": "context_resolver",
        "profile_identity": "dados_da_demanda.prioridade:dropdown",
        "context_resolver_version": 3,
        "context_confidence": 0.98,
        "context_evidence": {
            "label": {
                "value": "Prioridade",
                "source": "same_paragraph_before",
                "confidence": 0.99,
            }
        },
    }

    kept = preserved_editor_field_metadata(original)
    assert kept["auto_tagged"] is True
    assert kept["id_source"] == "context_resolver"
    assert kept["profile_identity"] == "dados_da_demanda.prioridade:dropdown"
    assert kept["context_resolver_version"] == 3

    repository = TemplateRepository(tmp_path / "templates")
    normalized = repository._normalize_fields([original], strict=True)[0]
    assert normalized["auto_tagged"] is True
    assert normalized["profile_identity"] == "dados_da_demanda.prioridade:dropdown"
    assert normalized["context_evidence"]["label"]["source"] == "same_paragraph_before"
