from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

from app.repositories.local_data import JsonFileStore, now_iso


SEMANTIC_MEMORY_SCHEMA_VERSION = 1
MAX_SEMANTIC_REVIEWS = 4000


class SemanticLearningStore:
    """Local-only review memory for semantic/template-family assistance.

    The store intentionally keeps compact semantic context and anchors rather
    than complete document contents. It is never sent to a network service.
    """

    def __init__(self, data_dir: Path) -> None:
        self.path = Path(data_dir) / "semantic_learning.json"
        self.store = JsonFileStore(
            self.path,
            {"semantic_schema_version": SEMANTIC_MEMORY_SCHEMA_VERSION, "reviews": []},
            kind="semantic_learning",
        )

    def snapshot(self) -> dict[str, Any]:
        value = self.store.read()
        if not isinstance(value, dict):
            return {"semantic_schema_version": SEMANTIC_MEMORY_SCHEMA_VERSION, "reviews": []}
        reviews = [
            dict(item)
            for item in value.get("reviews", []) or []
            if isinstance(item, dict)
        ]
        return {
            "semantic_schema_version": SEMANTIC_MEMORY_SCHEMA_VERSION,
            "reviews": reviews,
        }

    def record_reviews(
        self,
        reviews: Iterable[dict[str, Any]],
        *,
        family_fingerprint: str,
        document_fingerprint: str,
    ) -> None:
        memory = self.snapshot()
        existing = [dict(item) for item in memory.get("reviews", []) or []]
        index: dict[tuple[str, str, str], int] = {}
        for position, item in enumerate(existing):
            key = (
                str(item.get("family_fingerprint", "")),
                str(item.get("location_signature", "")),
                str(item.get("field_id", "")),
            )
            index[key] = position

        for raw in reviews:
            if not isinstance(raw, dict):
                continue
            field_id = str(raw.get("field_id", "") or "").strip()
            location_signature = str(raw.get("location_signature", "") or "").strip()
            if not field_id or not location_signature:
                continue
            record = {
                "family_fingerprint": str(family_fingerprint or raw.get("family_fingerprint", "")),
                "document_fingerprint": str(document_fingerprint or raw.get("document_fingerprint", "")),
                "location_signature": location_signature,
                "field_id": field_id,
                "label": str(raw.get("label", "") or "").strip(),
                "type": str(raw.get("type", "text") or "text"),
                "concept_id": str(raw.get("semantic_concept_id", "") or ""),
                "dynamic_scope": str(raw.get("dynamic_scope", "") or ""),
                "section": str(raw.get("section", "") or ""),
                "semantic_context": _compact_context(raw),
                "accepted": bool(raw.get("accepted_by_user", False)),
                "source_anchor": deepcopy(raw.get("source_anchor", {}) or {}),
                "list_style": str(raw.get("list_style", "") or ""),
                "list_punctuation": str(raw.get("list_punctuation", "") or ""),
                "minimum_items": int(raw.get("minimum_items", 0) or 0),
                "reviewed_at": now_iso(),
                "review_count": 1,
            }
            key = (
                record["family_fingerprint"],
                record["location_signature"],
                record["field_id"],
            )
            position = index.get(key)
            if position is None:
                index[key] = len(existing)
                existing.append(record)
            else:
                previous = existing[position]
                record["review_count"] = int(previous.get("review_count", 1) or 1) + 1
                existing[position] = record

        existing.sort(key=lambda item: str(item.get("reviewed_at", "")), reverse=True)
        memory["reviews"] = existing[:MAX_SEMANTIC_REVIEWS]
        memory["semantic_schema_version"] = SEMANTIC_MEMORY_SCHEMA_VERSION
        self.store.write(memory)


def _compact_context(candidate: dict[str, Any]) -> str:
    context = dict(candidate.get("source_context", {}) or {})
    parts = [
        str(candidate.get("label", "") or ""),
        str(candidate.get("section", "") or ""),
        str(context.get("before", "") or "")[-120:],
        str(context.get("after", "") or "")[:120],
    ]
    return " | ".join(part.strip() for part in parts if part.strip())[:520]
