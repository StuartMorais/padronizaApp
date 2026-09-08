from __future__ import annotations

from decimal import Decimal

from app.domain.conditions import condition_matches
from app.domain.field_formats import (
    currency_to_words_pt_br,
    decimal_from_localized,
    digits_only,
    format_cep,
    format_cnpj,
    format_cpf,
    format_currency,
    format_decimal,
    format_percentage,
    format_phone,
    validate_cnpj,
    validate_cpf,
)
from app.domain.validation import format_input, validate_field


def test_condition_matches_supports_string_dict_boolean_and_negative_rules() -> None:
    values = {"tipo": "Integral", "ativo": True, "vazio": ""}

    assert condition_matches(None, values)
    assert condition_matches("tipo=integral", values)
    assert condition_matches({"field": "tipo", "equals": "Integral"}, values)
    assert condition_matches({"field": "tipo", "not_equals": "Parcial"}, values)
    assert condition_matches({"field": "ativo", "equals": "sim"}, values)
    assert condition_matches({"field": "ativo", "truthy": True}, values)
    assert not condition_matches({"field": "vazio", "truthy": True}, values)
    assert condition_matches("regra-sem-igual", values)
    assert condition_matches(42, values)


def test_brazilian_field_formatters_cover_partial_and_complete_values() -> None:
    assert digits_only("CPF 123.456") == "123456"
    assert format_cnpj("12345678000195") == "12.345.678/0001-95"
    assert format_cpf("52998224725") == "529.982.247-25"
    assert format_cep("58000000") == "58000-000"
    assert format_phone("83999998888") == "(83) 99999-8888"
    assert format_currency("125050") == "R$ 1.250,50"
    assert format_decimal("1.234,5") == "1.234,50"
    assert format_percentage("12.50") == "12,50%"
    assert decimal_from_localized("R$ 1.234,50") == Decimal("1234.50")
    assert currency_to_words_pt_br("R$ 17.745,00") == (
        "dezessete mil, setecentos e quarenta e cinco reais"
    )
    assert currency_to_words_pt_br("R$ 20.500,25") == (
        "vinte mil e quinhentos reais e vinte e cinco centavos"
    )


def test_cpf_and_cnpj_validation_and_registry_driven_validation() -> None:
    assert validate_cpf("529.982.247-25")
    assert not validate_cpf("111.111.111-11")
    assert validate_cnpj("12.345.678/0001-95")
    assert not validate_cnpj("11.111.111/1111-11")

    assert validate_field({"id": "cpf", "label": "CPF", "type": "cpf"}, "529.982.247-25") is None
    assert validate_field({"id": "email", "label": "E-mail", "type": "email"}, "invalido") is not None
    assert validate_field(
        {"id": "tipo", "label": "Tipo", "type": "dropdown", "options": ["A", "B"]},
        "C",
    ) is not None
    assert format_input("phone", "83999998888") == "(83) 99999-8888"
