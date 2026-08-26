from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class NormalizedRecord:
    ordinal: int
    text: str
    story: str
    section: str
    zone: str
    table_index: int | None
    row_index: int | None
    cell_index: int | None
    table_kind: str
    protected: bool


@dataclass(frozen=True)
class NormalizedTable:
    table_index: int
    kind: str
    title: str
    section: str
    columns: int
    data_rows: tuple[int, ...]
    confidence: float
    protected: bool


@dataclass(frozen=True)
class NormalizedDocument:
    source_path: Path
    source_fingerprint: str
    records: tuple[NormalizedRecord, ...]
    tables: tuple[NormalizedTable, ...]


def build_normalized_document(
    source_path: Path,
    records: list[Any],
    structure: Any,
) -> NormalizedDocument:
    """Create a stable physical representation before candidate interpretation."""

    normalized_records: list[NormalizedRecord] = []
    for record in records:
        owner = structure.owner_for(int(record.ordinal))
        normalized_records.append(
            NormalizedRecord(
                ordinal=int(record.ordinal),
                text=str(record.text or ""),
                story=str(record.story or ""),
                section=str(getattr(owner, "section", "") or ""),
                zone=str(getattr(getattr(owner, "zone", None), "value", "") or ""),
                table_index=record.table_index,
                row_index=record.row_index,
                cell_index=record.cell_index,
                table_kind=str(getattr(owner, "table_kind", "") or ""),
                protected=bool(getattr(owner, "protected", False)),
            )
        )

    normalized_tables = tuple(
        NormalizedTable(
            table_index=int(table.table_index),
            kind=str(table.kind),
            title=str(table.structure.title or ""),
            section=str(table.section or ""),
            columns=int(table.structure.total_columns),
            data_rows=tuple(int(value) for value in table.structure.data_rows),
            confidence=float(table.structure.confidence),
            protected=bool(table.protected),
        )
        for table in structure.tables
    )
    path = Path(source_path).resolve()
    return NormalizedDocument(
        source_path=path,
        source_fingerprint=_sha256(path),
        records=tuple(normalized_records),
        tables=normalized_tables,
    )


def location_signature(location: dict[str, Any]) -> str:
    """Return a deterministic signature for a candidate's physical source."""

    normalized = {
        str(key): value
        for key, value in sorted((location or {}).items())
        if key not in {"preview", "text"}
    }
    payload = json.dumps(normalized, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
