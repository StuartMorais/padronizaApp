from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable, Mapping

from app.domain.field_types import FieldType, normalize_field_type


class FieldDefinition(dict[str, Any]):
    """Canonical, dict-compatible field model.

    The application historically stores fields as JSON dictionaries. Subclassing
    ``dict`` lets existing persistence/UI code continue to work while providing
    a single normalized model and typed properties for new code.
    """

    def __init__(self, source: Mapping[str, Any] | None = None, **values: Any) -> None:
        payload: dict[str, Any] = {}
        if source:
            payload.update(deepcopy(dict(source)))
        payload.update(values)
        super().__init__(payload)
        self.normalize()

    def normalize(self) -> "FieldDefinition":
        self["id"] = str(self.get("id", "")).strip()
        self["label"] = str(self.get("label", "")).strip()
        self["type"] = normalize_field_type(self.get("type", FieldType.TEXT.value))
        if "required" in self:
            self["required"] = bool(self.get("required"))
        return self

    @property
    def field_id(self) -> str:
        return str(self.get("id", ""))

    @property
    def field_type(self) -> FieldType:
        return FieldType(normalize_field_type(self.get("type")))

    @property
    def label(self) -> str:
        return str(self.get("label", ""))

    @property
    def required(self) -> bool:
        return bool(self.get("required", False))

    def clone(self) -> "FieldDefinition":
        return FieldDefinition(self)


def as_field(value: Mapping[str, Any] | FieldDefinition) -> FieldDefinition:
    if isinstance(value, FieldDefinition):
        return value
    return FieldDefinition(value)


def as_fields(values: Iterable[Mapping[str, Any]]) -> list[FieldDefinition]:
    return [as_field(value) for value in values]
