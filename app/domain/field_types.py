from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable


class FieldType(str, Enum):
    """Canonical field types understood by the application."""

    TEXT = "text"
    MULTILINE = "multiline"
    DATE = "date"
    CHECKBOX = "checkbox"
    DROPDOWN = "dropdown"
    CURRENCY = "currency"
    INTEGER = "integer"
    DECIMAL = "decimal"
    PERCENTAGE = "percentage"
    CNPJ = "cnpj"
    CPF = "cpf"
    CEP = "cep"
    PHONE = "phone"
    EMAIL = "email"
    REPEATABLE_TABLE = "repeatable_table"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class FieldTypeSpec:
    field_type: FieldType
    aliases: tuple[str, ...] = ()
    requires_options: bool = False
    is_collection: bool = False


_FIELD_TYPE_SPECS = (
    FieldTypeSpec(FieldType.TEXT, ("string", "input", "lineedit")),
    FieldTypeSpec(FieldType.MULTILINE, ("textarea", "longtext", "long_text", "paragraph")),
    FieldTypeSpec(FieldType.DATE, ("datetime",)),
    FieldTypeSpec(FieldType.CHECKBOX, ("bool", "boolean", "check")),
    FieldTypeSpec(FieldType.DROPDOWN, ("select", "choice", "choices", "combobox", "combo"), requires_options=True),
    FieldTypeSpec(FieldType.CURRENCY, ("money",)),
    FieldTypeSpec(FieldType.INTEGER),
    FieldTypeSpec(FieldType.DECIMAL, ("number",)),
    FieldTypeSpec(FieldType.PERCENTAGE, ("percent",)),
    FieldTypeSpec(FieldType.CNPJ),
    FieldTypeSpec(FieldType.CPF),
    FieldTypeSpec(FieldType.CEP),
    FieldTypeSpec(FieldType.PHONE),
    FieldTypeSpec(FieldType.EMAIL),
    FieldTypeSpec(
        FieldType.REPEATABLE_TABLE,
        ("table", "repeating_table", "repeatable"),
        is_collection=True,
    ),
)

FIELD_TYPE_ORDER = tuple(spec.field_type.value for spec in _FIELD_TYPE_SPECS)
SUPPORTED_FIELD_TYPES = frozenset(FIELD_TYPE_ORDER)
FIELD_TYPE_ALIASES = {
    alias: spec.field_type.value
    for spec in _FIELD_TYPE_SPECS
    for alias in spec.aliases
}
FIELD_TYPE_SPECS = {spec.field_type.value: spec for spec in _FIELD_TYPE_SPECS}


def normalize_field_type(value: object, *, default: str = FieldType.TEXT.value) -> str:
    """Return a supported canonical field type string.

    Keeping the serialized representation as a plain string preserves backwards
    compatibility with existing template JSON while the rest of the code gains
    one authoritative type registry.
    """

    raw = str(value or "").strip().casefold()
    canonical = FIELD_TYPE_ALIASES.get(raw, raw)
    if canonical in SUPPORTED_FIELD_TYPES:
        return canonical
    fallback = FIELD_TYPE_ALIASES.get(str(default).casefold(), str(default).casefold())
    return fallback if fallback in SUPPORTED_FIELD_TYPES else FieldType.TEXT.value


def supports_options(field_type: object) -> bool:
    spec = FIELD_TYPE_SPECS.get(normalize_field_type(field_type))
    return bool(spec and spec.requires_options)


def supported_field_types() -> Iterable[str]:
    return FIELD_TYPE_ORDER
