from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

LOCAL_DATA_SCHEMA_VERSION = 1
TEMPLATE_SCHEMA_VERSION = 2
SETTINGS_SCHEMA_VERSION = 1
BACKUP_SCHEMA_VERSION = 1


class SchemaVersionError(ValueError):
    """Raised when data was written by a newer incompatible Padroniza version."""


@dataclass(frozen=True)
class DecodedStore:
    data: Any
    migrated: bool
    version: int


def encode_store(kind: str, data: Any) -> dict[str, Any]:
    return {
        "schema_version": LOCAL_DATA_SCHEMA_VERSION,
        "kind": str(kind),
        "data": deepcopy(data),
    }


def decode_store(value: Any, *, kind: str, default: Any) -> DecodedStore:
    """Decode local JSON while transparently accepting pre-versioned files."""

    if isinstance(value, dict) and "schema_version" in value and "data" in value:
        try:
            version = int(value.get("schema_version", 0) or 0)
        except (TypeError, ValueError) as exc:
            raise SchemaVersionError(f"Versão de dados inválida em {kind}.") from exc
        if version > LOCAL_DATA_SCHEMA_VERSION:
            raise SchemaVersionError(
                f"Os dados de '{kind}' foram criados por uma versão mais nova do Padroniza "
                f"(schema {version}; suportado: {LOCAL_DATA_SCHEMA_VERSION})."
            )
        stored_kind = str(value.get("kind", kind)).strip()
        if stored_kind and stored_kind != kind:
            raise SchemaVersionError(
                f"O arquivo de dados '{kind}' contém dados do tipo '{stored_kind}'."
            )
        data = deepcopy(value.get("data", default))
        # Future migrations are chained here: v1 -> v2 -> v3.
        return DecodedStore(data=data, migrated=version < LOCAL_DATA_SCHEMA_VERSION, version=version)

    # Legacy v0: files were raw lists/dicts without an envelope.
    return DecodedStore(data=deepcopy(value), migrated=True, version=0)


def migrate_qsettings(settings: Any) -> int:
    """Apply ordered QSettings migrations and return the resulting version."""

    try:
        current = int(settings.value("schema/version", 0) or 0)
    except (TypeError, ValueError):
        current = 0
    if current > SETTINGS_SCHEMA_VERSION:
        raise SchemaVersionError(
            "As configurações foram criadas por uma versão mais nova do Padroniza."
        )

    # v0 -> v1 only establishes explicit versioning; existing keys are already
    # compatible and therefore remain untouched.
    if current < 1:
        current = 1
        settings.setValue("schema/version", current)
        settings.sync()
    return current
