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
