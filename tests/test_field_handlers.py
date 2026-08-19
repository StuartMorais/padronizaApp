from __future__ import annotations

from app.domain.field_handlers import FIELD_HANDLERS, field_handler
from app.domain.field_types import FieldType, supported_field_types
from app.domain.validation import format_input, validate_field


def test_every_canonical_field_type_has_a_handler():
    assert set(supported_field_types()) == set(FIELD_HANDLERS)
    for field_type in FieldType:
        assert field_handler(field_type).field_type is field_type


def test_dropdown_handler_rejects_values_outside_template_options():
    field = {
        "id": "status",
        "label": "Status",
        "type": "dropdown",
        "options": ["Ativo", "Inativo"],
    }
    assert validate_field(field, "Ativo") is None
    assert "não existe mais" in str(validate_field(field, "Removido"))


def test_registry_formats_common_brazilian_fields():
    assert format_input("cpf", "52998224725") == "529.982.247-25"
    assert format_input("cep", "70040010") == "70040-010"
    assert format_input("phone", "61998765432") == "(61) 99876-5432"
