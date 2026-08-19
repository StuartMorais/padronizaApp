from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from app.domain.field_formats import (
    EMAIL_PATTERN,
    decimal_from_localized,
    digits_only,
    format_cep,
    format_cnpj,
    format_cpf,
    format_currency,
    format_percentage,
    format_phone,
    validate_cnpj,
    validate_cpf,
)
from app.domain.field_metadata import dropdown_option_values
from app.domain.field_types import FieldType, normalize_field_type

Formatter = Callable[[Any], str]
SpecificValidator = Callable[[dict[str, Any], str], str | None]


def _identity(value: Any) -> str:
    return str(value or "")


def _integer(value: Any) -> str:
    return digits_only(value)


def _valid(_: dict[str, Any], __: str) -> str | None:
    return None


def _cnpj(field: dict[str, Any], text: str) -> str | None:
    return None if validate_cnpj(text) else f"{_label(field)} contém um CNPJ inválido."


def _cpf(field: dict[str, Any], text: str) -> str | None:
    return None if validate_cpf(text) else f"{_label(field)} contém um CPF inválido."


def _cep(field: dict[str, Any], text: str) -> str | None:
    return None if len(digits_only(text)) == 8 else f"{_label(field)} deve conter 8 dígitos de CEP."


def _phone(field: dict[str, Any], text: str) -> str | None:
    if len(digits_only(text)) in {10, 11}:
        return None
    return f"{_label(field)} deve conter DDD e um telefone brasileiro válido."


def _email(field: dict[str, Any], text: str) -> str | None:
    return None if EMAIL_PATTERN.fullmatch(text) else f"{_label(field)} contém um endereço de e-mail inválido."


def _integer_validator(field: dict[str, Any], text: str) -> str | None:
    stripped = text.strip()
    if stripped.lstrip("+-").isdigit():
        return None
    return f"{_label(field)} deve ser um número inteiro."


def _numeric(field: dict[str, Any], text: str) -> str | None:
    try:
        decimal_from_localized(text)
    except InvalidOperation:
        return f"{_label(field)} deve conter um número válido."
    return None


def _percentage(field: dict[str, Any], text: str) -> str | None:
    error = _numeric(field, text)
    if error:
        return error
    numeric_value = decimal_from_localized(text)
    minimum = Decimal(str(field.get("min", 0)))
    maximum = Decimal(str(field.get("max", 100)))
    if numeric_value < minimum or numeric_value > maximum:
        return f"{_label(field)} deve estar entre {minimum}% e {maximum}%."
    return None


def _dropdown(field: dict[str, Any], text: str) -> str | None:
    options = dropdown_option_values(field.get("options", []))
    if not options:
        return f"{_label(field)} não possui opções configuradas."
    if text and text not in options:
        return f"{_label(field)} contém uma opção que não existe mais no modelo."
    return None


def _label(field: dict[str, Any]) -> str:
    return str(field.get("label") or field.get("id") or "Campo")


@dataclass(frozen=True)
class FieldHandler:
    field_type: FieldType
    widget_kind: str = "line"
    placeholder: str = ""
    hint: str = ""
    sample: Any = "Exemplo de preenchimento"
    full_width: bool = False
    formatter: Formatter = _identity
    validator: SpecificValidator = _valid

    def format(self, value: Any) -> str:
        return self.formatter(value)

    def validate(self, field: dict[str, Any], text: str) -> str | None:
        return self.validator(field, text)


FIELD_HANDLERS: dict[str, FieldHandler] = {
    FieldType.TEXT.value: FieldHandler(FieldType.TEXT),
    FieldType.MULTILINE.value: FieldHandler(
        FieldType.MULTILINE,
        widget_kind="multiline",
        sample="Observações de exemplo para validação do documento.",
        full_width=True,
    ),
    FieldType.DATE.value: FieldHandler(
        FieldType.DATE,
        widget_kind="date",
        hint="Formato exibido: dia/mês/ano.",
        sample="19/08/2026",
    ),
    FieldType.CHECKBOX.value: FieldHandler(
        FieldType.CHECKBOX,
        widget_kind="checkbox",
        sample=True,
    ),
    FieldType.DROPDOWN.value: FieldHandler(
        FieldType.DROPDOWN,
        widget_kind="dropdown",
        validator=_dropdown,
    ),
    FieldType.CURRENCY.value: FieldHandler(
        FieldType.CURRENCY,
        placeholder="R$ 0,00",
        hint="Digite os centavos normalmente. Exemplo: R$ 1.250,00",
        sample="R$ 125.430,50",
        formatter=format_currency,
        validator=_numeric,
    ),
    FieldType.INTEGER.value: FieldHandler(
        FieldType.INTEGER,
        hint="Use somente números inteiros.",
        sample="10",
        formatter=_integer,
        validator=_integer_validator,
    ),
    FieldType.DECIMAL.value: FieldHandler(
        FieldType.DECIMAL,
        hint="Use vírgula ou ponto para as casas decimais.",
        sample="15,50",
        validator=_numeric,
    ),
    FieldType.PERCENTAGE.value: FieldHandler(
        FieldType.PERCENTAGE,
        placeholder="0,00%",
        hint="Informe uma porcentagem entre 0% e 100%.",
        sample="12,50%",
        formatter=format_percentage,
        validator=_percentage,
    ),
    FieldType.CNPJ.value: FieldHandler(
        FieldType.CNPJ,
        placeholder="00.000.000/0000-00",
        hint="Formato esperado: 00.000.000/0000-00",
        sample="12.345.678/0001-95",
        formatter=format_cnpj,
        validator=_cnpj,
    ),
    FieldType.CPF.value: FieldHandler(
        FieldType.CPF,
        placeholder="000.000.000-00",
        hint="Formato esperado: 000.000.000-00",
        sample="529.982.247-25",
        formatter=format_cpf,
        validator=_cpf,
    ),
    FieldType.CEP.value: FieldHandler(
        FieldType.CEP,
        placeholder="00000-000",
        hint="Formato esperado: 00000-000",
        sample="70040-010",
        formatter=format_cep,
        validator=_cep,
    ),
    FieldType.PHONE.value: FieldHandler(
        FieldType.PHONE,
        placeholder="(00) 00000-0000",
        hint="Informe DDD e número. Exemplo: (83) 99999-9999",
        sample="(61) 99876-5432",
        formatter=format_phone,
        validator=_phone,
    ),
    FieldType.EMAIL.value: FieldHandler(
        FieldType.EMAIL,
        placeholder="nome@exemplo.com",
        hint="Exemplo: nome@orgao.gov.br",
        sample="contato@empresa.com.br",
        validator=_email,
    ),
    FieldType.REPEATABLE_TABLE.value: FieldHandler(
        FieldType.REPEATABLE_TABLE,
        widget_kind="repeatable_table",
        full_width=True,
    ),
}


def field_handler(field_type: object) -> FieldHandler:
    return FIELD_HANDLERS[normalize_field_type(field_type)]
