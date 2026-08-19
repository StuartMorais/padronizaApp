"""Core document-field models shared across UI, scanning and persistence."""

from app.domain.fields import FieldDefinition, as_field, as_fields
from app.domain.field_types import FieldType, FieldTypeSpec, normalize_field_type

__all__ = [
    "FieldDefinition",
    "FieldType",
    "FieldTypeSpec",
    "as_field",
    "as_fields",
    "normalize_field_type",
]
