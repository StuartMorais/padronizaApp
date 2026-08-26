from __future__ import annotations

import json
import os
import tempfile
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.json_io import atomic_write_json
from app.core.schema import decode_store, encode_store


ISO_FORMAT = "%Y-%m-%dT%H:%M:%S"


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


class JsonFileStore:
    """Small atomic JSON store used by the offline application."""

    def __init__(self, path: Path, default: Any, *, kind: str | None = None) -> None:
        self.path = Path(path)
        self.default = default
        resolved_kind = str(kind or self.path.stem).strip()
        if not resolved_kind:
            raise ValueError("JsonFileStore requires a non-empty data kind.")
        self.kind = resolved_kind

    def read(self) -> Any:
        if not self.path.exists():
            return deepcopy(self.default)

        try:
            with self.path.open("r", encoding="utf-8-sig") as handle:
                raw_value = json.load(handle)
            decoded = decode_store(raw_value, kind=self.kind, default=self.default)
        except (OSError, json.JSONDecodeError):
            return deepcopy(self.default)

        if decoded.migrated:
            try:
                self.write(decoded.data)
            except OSError:
                # Reading old data must still work on a temporarily read-only disk.
                pass
        return decoded.data

    def write(self, value: Any) -> None:
        atomic_write_json(self.path, encode_store(self.kind, value))


class LocalDataStore:
    """
    Stores profiles, recent document metadata, drafts, audit entries, and
    numbering counters entirely inside the project data directory.
    """

    MAX_RECENT = 250
    MAX_AUDIT = 2000

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self._profiles = JsonFileStore(self.data_dir / "profiles.json", [], kind="profiles")
        self._recent = JsonFileStore(self.data_dir / "recent_documents.json", [], kind="recent_documents")
        self._drafts = JsonFileStore(self.data_dir / "drafts.json", {}, kind="drafts")
        self._audit = JsonFileStore(self.data_dir / "audit_history.json", [], kind="audit_history")
        self._sequences = JsonFileStore(self.data_dir / "sequences.json", {}, kind="sequences")

    # Profiles -----------------------------------------------------------------
    def list_profiles(self) -> list[dict[str, Any]]:
        value = self._profiles.read()
        if not isinstance(value, list):
            return []

        profiles = [item for item in value if isinstance(item, dict)]
        profiles.sort(key=lambda item: str(item.get("name", "")).casefold())
        return profiles

    def get_profile(self, profile_id: str) -> dict[str, Any] | None:
        for profile in self.list_profiles():
            if str(profile.get("id", "")) == str(profile_id):
                return profile
        return None

    def save_profile(
        self,
        *,
        name: str,
        values: dict[str, Any],
        category: str = "Empresa",
        profile_id: str | None = None,
    ) -> str:
        name = str(name).strip()
        if not name:
            raise ValueError('O nome do perfil não pode ficar vazio.')

        profiles = self.list_profiles()
        resolved_id = str(profile_id or self._slug(name)).strip() or "profile"

        if profile_id is None:
            base_id = resolved_id
            counter = 2
            existing_ids = {str(item.get("id", "")) for item in profiles}
            while resolved_id in existing_ids:
                resolved_id = f"{base_id}-{counter}"
                counter += 1

        record = {
            "id": resolved_id,
            "name": name,
            "category": str(category).strip() or "Empresa",
            "values": deepcopy(values),
            "updated_at": now_iso(),
        }

        replaced = False
        for index, profile in enumerate(profiles):
            if str(profile.get("id", "")) == resolved_id:
                profiles[index] = record
                replaced = True
                break

        if not replaced:
            profiles.append(record)

        self._profiles.write(profiles)
        self.add_audit("profile_saved", name, {"profile_id": resolved_id})
        return resolved_id

    def delete_profile(self, profile_id: str) -> bool:
        profiles = self.list_profiles()
        retained = [
            profile
            for profile in profiles
            if str(profile.get("id", "")) != str(profile_id)
        ]
        changed = len(retained) != len(profiles)
        if changed:
            self._profiles.write(retained)
            self.add_audit("profile_deleted", str(profile_id), {})
        return changed

    # Recent documents ---------------------------------------------------------
    def list_recent(self) -> list[dict[str, Any]]:
        value = self._recent.read()
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]

    def add_recent(self, record: dict[str, Any]) -> str:
        recent = self.list_recent()
        document_id = str(record.get("id", "")).strip()
        if not document_id:
            document_id = datetime.now().strftime("%Y%m%d%H%M%S%f")

        saved = deepcopy(record)
        saved["id"] = document_id
        saved.setdefault("created_at", now_iso())

        recent = [item for item in recent if str(item.get("id", "")) != document_id]
        recent.insert(0, saved)
        self._recent.write(recent[: self.MAX_RECENT])
        return document_id

    def get_recent(self, document_id: str) -> dict[str, Any] | None:
        for item in self.list_recent():
            if str(item.get("id", "")) == str(document_id):
                return item
        return None

    def delete_recent(self, document_id: str) -> bool:
        recent = self.list_recent()
        retained = [
            item
            for item in recent
            if str(item.get("id", "")) != str(document_id)
        ]
        changed = len(retained) != len(recent)
        if changed:
            self._recent.write(retained)
        return changed

    def clear_recent(self) -> None:
        self._recent.write([])

    def commit_generated_document(
        self,
        record: dict[str, Any],
        *,
        audit_action: str,
        audit_description: str,
        audit_details: dict[str, Any],
        sequence_key: str | None = None,
        sequence_year: int | None = None,
        expected_sequence: int | None = None,
    ) -> str:
        """Commit history, audit and numbering as one rollback-capable unit.

        Generation publishes an artifact only together with these metadata
        changes.  Staging all JSON payloads first prevents a late history/audit
        write from consuming numbering while leaving the stores inconsistent.
        """

        recent = self.list_recent()
        document_id = str(record.get("id", "")).strip()
        if not document_id:
            document_id = datetime.now().strftime("%Y%m%d%H%M%S%f")
        saved = deepcopy(record)
        saved["id"] = document_id
        saved.setdefault("created_at", now_iso())
        recent = [item for item in recent if str(item.get("id", "")) != document_id]
        recent.insert(0, saved)
        recent = recent[: self.MAX_RECENT]

        audit = self._audit.read()
        if not isinstance(audit, list):
            audit = []
        audit.insert(
            0,
            {
                "timestamp": now_iso(),
                "action": str(audit_action),
                "description": str(audit_description),
                "details": deepcopy(audit_details),
            },
        )
        audit = audit[: self.MAX_AUDIT]

        changes: list[tuple[JsonFileStore, Any]] = [
            (self._recent, recent),
            (self._audit, audit),
        ]
        if sequence_key:
            year = int(sequence_year or datetime.now().year)
            resolved_key = f"{str(sequence_key).strip()}:{year}"
            sequences = self._sequences.read()
            if not isinstance(sequences, dict):
                sequences = {}
            current = int(sequences.get(resolved_key, 0) or 0)
            next_value = current + 1
            if expected_sequence is not None and next_value != int(expected_sequence):
                raise RuntimeError(
                    "A numeração mudou enquanto o documento era gerado. "
                    "Gere novamente para evitar número duplicado."
                )
            sequences[resolved_key] = next_value
            changes.append((self._sequences, sequences))

        self._write_stores_transactionally(changes)
        return document_id

    def _write_stores_transactionally(
        self,
        changes: list[tuple[JsonFileStore, Any]],
    ) -> None:
        """Stage and publish several local JSON stores with rollback."""

        self.data_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=".padroniza-data-transaction-",
            dir=str(self.data_dir),
        ) as temporary:
            stage_root = Path(temporary)
            prepared: list[tuple[Path, Path]] = []
            for index, (store, value) in enumerate(changes):
                staged = stage_root / f"staged-{index}-{store.path.name}"
                atomic_write_json(staged, encode_store(store.kind, value))
                prepared.append((staged, store.path))

            activated: list[tuple[Path, Path | None]] = []
            try:
                for index, (staged, destination) in enumerate(prepared):
                    previous = stage_root / f"previous-{index}-{destination.name}"
                    had_previous = destination.exists()
                    if had_previous:
                        os.replace(destination, previous)
                    try:
                        os.replace(staged, destination)
                    except Exception:
                        if had_previous and previous.exists() and not destination.exists():
                            os.replace(previous, destination)
                        raise
                    activated.append((destination, previous if had_previous else None))
            except Exception:
                for destination, previous in reversed(activated):
                    try:
                        destination.unlink(missing_ok=True)
                        if previous is not None and previous.exists():
                            os.replace(previous, destination)
                    except OSError:
                        pass
                raise

    # Drafts -------------------------------------------------------------------
    def save_draft(self, template_id: str, values: dict[str, Any]) -> None:
        template_id = str(template_id).strip()
        if not template_id:
            return

        drafts = self._drafts.read()
        if not isinstance(drafts, dict):
            drafts = {}

        drafts[template_id] = {
            "values": deepcopy(values),
            "updated_at": now_iso(),
        }
        self._drafts.write(drafts)

    def load_draft(self, template_id: str) -> dict[str, Any] | None:
        drafts = self._drafts.read()
        if not isinstance(drafts, dict):
            return None

        value = drafts.get(str(template_id))
        return value if isinstance(value, dict) else None

    def delete_draft(self, template_id: str) -> None:
        drafts = self._drafts.read()
        if not isinstance(drafts, dict):
            return

        if str(template_id) in drafts:
            drafts.pop(str(template_id), None)
            self._drafts.write(drafts)

    # Audit --------------------------------------------------------------------
    def add_audit(
        self,
        action: str,
        description: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        entries = self._audit.read()
        if not isinstance(entries, list):
            entries = []

        entries.insert(
            0,
            {
                "timestamp": now_iso(),
                "action": str(action),
                "description": str(description),
                "details": deepcopy(details or {}),
            },
        )
        self._audit.write(entries[: self.MAX_AUDIT])

    def list_audit(self, limit: int | None = None) -> list[dict[str, Any]]:
        entries = self._audit.read()
        if not isinstance(entries, list):
            return []
        cleaned = [item for item in entries if isinstance(item, dict)]
        return cleaned if limit is None else cleaned[: max(0, limit)]

    # Numbering ----------------------------------------------------------------
    def next_sequence(self, key: str, year: int | None = None) -> int:
        year = int(year or datetime.now().year)
        resolved_key = f"{str(key).strip()}:{year}"

        sequences = self._sequences.read()
        if not isinstance(sequences, dict):
            sequences = {}

        current = int(sequences.get(resolved_key, 0) or 0)
        next_value = current + 1
        sequences[resolved_key] = next_value
        self._sequences.write(sequences)
        return next_value

    def peek_sequence(self, key: str, year: int | None = None) -> int:
        year = int(year or datetime.now().year)
        resolved_key = f"{str(key).strip()}:{year}"
        sequences = self._sequences.read()
        if not isinstance(sequences, dict):
            return 1
        return int(sequences.get(resolved_key, 0) or 0) + 1

    @staticmethod
    def _slug(value: str) -> str:
        import re
        import unicodedata

        normalized = unicodedata.normalize("NFKD", value)
        ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
        return re.sub(r"[^a-zA-Z0-9]+", "-", ascii_value).strip("-").lower()
