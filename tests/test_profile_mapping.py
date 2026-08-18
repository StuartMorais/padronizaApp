from app.profile_mapping import build_profile_payload, resolve_profile_values


def test_profile_payload_keeps_all_fields_even_when_profile_keys_exist() -> None:
    fields = [
        {
            "id": "company.cnpj",
            "label": "CNPJ",
            "profile_key": "company.cnpj",
        },
        {
            "id": "process.object",
            "label": "Objeto",
        },
        {
            "id": "delivery.immediate",
            "label": "Entrega imediata",
        },
        {
            "id": "items",
            "label": "Itens",
            "type": "table",
        },
    ]
    values = {
        "company.cnpj": "12.345.678/0001-90",
        "process.object": "Aquisição de equipamentos",
        "delivery.immediate": True,
        "items": [{"description": "Notebook", "quantity": 2}],
    }

    payload = build_profile_payload(fields, values)

    assert payload["company.cnpj"] == "12.345.678/0001-90"
    assert payload["process.object"] == "Aquisição de equipamentos"
    assert payload["delivery.immediate"] is True
    assert payload["items"] == [{"description": "Notebook", "quantity": 2}]


def test_profile_payload_adds_portable_alias_without_losing_exact_id() -> None:
    fields = [
        {
            "id": "supplier.registration.cnpj",
            "profile_key": "company.cnpj",
        },
        {
            "id": "supplier.name",
        },
    ]
    values = {
        "supplier.registration.cnpj": "12.345.678/0001-90",
        "supplier.name": "Empresa Exemplo Ltda.",
    }

    payload = build_profile_payload(fields, values)

    assert payload["supplier.registration.cnpj"] == "12.345.678/0001-90"
    assert payload["company.cnpj"] == "12.345.678/0001-90"
    assert payload["supplier.name"] == "Empresa Exemplo Ltda."


def test_exact_field_id_wins_over_profile_alias_when_applying() -> None:
    fields = [
        {
            "id": "supplier.registration.cnpj",
            "profile_key": "company.cnpj",
        }
    ]
    profile = {
        "supplier.registration.cnpj": "EXACT",
        "company.cnpj": "ALIAS",
    }

    mapped = resolve_profile_values(fields, profile)

    assert mapped == {"supplier.registration.cnpj": "EXACT"}


def test_legacy_profile_with_only_profile_key_still_applies() -> None:
    fields = [
        {
            "id": "supplier.registration.cnpj",
            "profile_key": "company.cnpj",
        }
    ]
    legacy_profile = {"company.cnpj": "12.345.678/0001-90"}

    mapped = resolve_profile_values(fields, legacy_profile)

    assert mapped == {"supplier.registration.cnpj": "12.345.678/0001-90"}


def test_profile_alias_collision_does_not_overwrite_exact_field_value() -> None:
    fields = [
        {"id": "company.cnpj"},
        {
            "id": "supplier.registration.cnpj",
            "profile_key": "company.cnpj",
        },
    ]
    values = {
        "company.cnpj": "EXACT COMPANY",
        "supplier.registration.cnpj": "SUPPLIER ALIAS SOURCE",
    }

    payload = build_profile_payload(fields, values)

    assert payload["company.cnpj"] == "EXACT COMPANY"
    assert payload["supplier.registration.cnpj"] == "SUPPLIER ALIAS SOURCE"


def test_profile_payload_copies_nested_values() -> None:
    fields = [{"id": "items"}]
    values = {"items": [{"description": "Notebook"}]}

    payload = build_profile_payload(fields, values)
    values["items"][0]["description"] = "Changed"

    assert payload["items"] == [{"description": "Notebook"}]


def test_auto_detected_field_can_apply_by_stable_label_identity() -> None:
    source_fields = [
        {
            "id": "auto.nome_completo",
            "label": "Nome completo",
            "type": "text",
            "section": "1. Solicitante",
            "detection_source": "automatic",
        }
    ]
    payload = build_profile_payload(
        source_fields,
        {"auto.nome_completo": "Maria de Souza"},
    )

    target_fields = [
        {
            "id": "pdf_field_018",
            "label": "Nome completo",
            "type": "text",
            "section": "Solicitante",
            "detection_source": "native_pdf",
        }
    ]

    assert resolve_profile_values(target_fields, payload) == {
        "pdf_field_018": "Maria de Souza"
    }


def test_native_pdf_internal_name_can_match_auto_field_by_visible_label() -> None:
    source_fields = [
        {
            "id": "acro_contact_7",
            "label": "E-mail",
            "type": "email",
            "section": "Contato",
            "detection_source": "native_pdf",
        }
    ]
    payload = build_profile_payload(
        source_fields,
        {"acro_contact_7": "maria@orgao.gov.br"},
    )
    target_fields = [
        {
            "id": "auto.email",
            "label": "E-mail",
            "type": "email",
            "section": "Dados do solicitante",
            "detection_source": "automatic",
        }
    ]

    assert resolve_profile_values(target_fields, payload) == {
        "auto.email": "maria@orgao.gov.br"
    }


def test_profile_identity_does_not_guess_between_duplicate_visible_labels() -> None:
    source_fields = [
        {
            "id": "source.email",
            "label": "E-mail",
            "type": "email",
            "section": "Solicitante",
        }
    ]
    payload = build_profile_payload(source_fields, {"source.email": "a@b.com"})
    target_fields = [
        {
            "id": "requester.email",
            "label": "E-mail",
            "type": "email",
            "section": "Solicitante",
        },
        {
            "id": "supplier.email",
            "label": "E-mail",
            "type": "email",
            "section": "Fornecedor",
        },
    ]

    # The source section gives one target a stronger score, so the resolver can
    # safely choose it instead of filling both E-mail fields.
    assert resolve_profile_values(target_fields, payload) == {
        "requester.email": "a@b.com"
    }


def test_profile_identity_skips_true_ambiguity_between_same_label_and_section() -> None:
    source_fields = [
        {
            "id": "source.responsavel",
            "label": "Responsável",
            "type": "text",
            "section": "Autorização",
        }
    ]
    payload = build_profile_payload(source_fields, {"source.responsavel": "Maria"})
    target_fields = [
        {
            "id": "target.one",
            "label": "Responsável",
            "type": "text",
            "section": "Autorização",
        },
        {
            "id": "target.two",
            "label": "Responsável",
            "type": "text",
            "section": "Autorização",
        },
    ]

    assert resolve_profile_values(target_fields, payload) == {}


def test_legacy_auto_profile_can_match_unique_label_suffix_without_metadata() -> None:
    legacy_profile = {
        "auto.nome_completo": "Carlos Almeida",
    }
    fields = [
        {
            "id": "native_person_name_12",
            "label": "Nome completo",
            "type": "text",
        }
    ]

    assert resolve_profile_values(fields, legacy_profile) == {
        "native_person_name_12": "Carlos Almeida"
    }


def test_legacy_profile_does_not_match_generic_data_label() -> None:
    legacy_profile = {"auto.data": "01/02/2026"}
    fields = [{"id": "pdf_date_7", "label": "Data", "type": "date"}]

    assert resolve_profile_values(fields, legacy_profile) == {}


def test_profile_identity_metadata_is_deep_copied_from_fields() -> None:
    fields = [
        {
            "id": "auto.telefone",
            "label": "Telefone",
            "type": "phone",
            "section": "Contato",
        }
    ]
    payload = build_profile_payload(fields, {"auto.telefone": "(83) 99999-9999"})
    fields[0]["label"] = "Alterado"

    metadata = payload["@padroniza/profile_identity/v2"]
    assert metadata["fields"][0]["label"] == "Telefone"


def test_context_resolver_profile_identity_can_match_different_technical_ids() -> None:
    fields_source = [
        {
            "id": "auto_word.prioridade",
            "label": "Prioridade",
            "type": "dropdown",
            "section": "2. Dados da demanda",
            "profile_identity": "dados_da_demanda.prioridade:dropdown",
        }
    ]
    profile = build_profile_payload(fields_source, {"auto_word.prioridade": "Alta"})

    target = [
        {
            "id": "pdf_priority_internal_47",
            "label": "Prioridade operacional",
            "type": "dropdown",
            "section": "2. Dados da demanda",
            "profile_identity": "dados_da_demanda.prioridade:dropdown",
        }
    ]
    assert resolve_profile_values(target, profile) == {"pdf_priority_internal_47": "Alta"}
