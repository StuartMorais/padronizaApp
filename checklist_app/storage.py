from __future__ import annotations

import json
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

APPDATA_DIR = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
DATA_DIR = APPDATA_DIR / "checklist-app" / "data"
DATA_FILE = DATA_DIR / "checklistTemplates.json"
BACKUP_DIR = DATA_DIR / "backups"
MAX_BACKUPS = 20


CHECKLIST_JSON_SCHEMA = "checklist-app.checklist"
CHECKLIST_JSON_VERSION = 1


def export_checklist_json(template: dict[str, Any], destination: str | Path) -> Path:
    """Export one normalized checklist as a portable JSON file.

    The exported envelope is intentionally independent from the application's
    internal checklistTemplates.json library, so users can share/import a
    checklist without replacing their entire local library.
    """
    destination_path = Path(destination)
    if destination_path.suffix.lower() != ".json":
        destination_path = destination_path.with_suffix(".json")
    destination_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "schema": CHECKLIST_JSON_SCHEMA,
        "version": CHECKLIST_JSON_VERSION,
        "exportedAt": datetime.now().isoformat(timespec="seconds"),
        "checklist": normalize_template(template),
    }

    temporary_path = destination_path.with_suffix(destination_path.suffix + ".tmp")
    with temporary_path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
    temporary_path.replace(destination_path)
    return destination_path


def import_checklists_json(source: str | Path, existing_ids: set[str] | None = None) -> list[dict[str, Any]]:
    """Read portable checklist JSON and return normalized checklist objects.

    Accepted inputs:
    - the portable envelope produced by :func:`export_checklist_json`;
    - one raw checklist object;
    - a list of raw checklist objects (useful for old/manual exports).

    ID collisions are imported as copies rather than overwriting local data.
    """
    source_path = Path(source)
    with source_path.open("r", encoding="utf-8-sig") as file:
        payload = json.load(file)

    raw_templates: list[Any]
    if isinstance(payload, dict) and payload.get("schema") == CHECKLIST_JSON_SCHEMA:
        version = int(payload.get("version") or 0)
        if version != CHECKLIST_JSON_VERSION:
            raise ValueError(f"Versão JSON de checklist não suportada: {version}.")
        checklist = payload.get("checklist")
        if not isinstance(checklist, dict):
            raise ValueError("O JSON não contém um checklist válido.")
        raw_templates = [checklist]
    elif isinstance(payload, dict):
        # Backward-friendly import of a single raw checklist object. Require at
        # least one recognizable checklist key so arbitrary JSON is not silently
        # accepted as an empty checklist.
        if not any(key in payload for key in ("title", "sections", "items")):
            raise ValueError("O JSON não parece conter um checklist.")
        raw_templates = [payload]
    elif isinstance(payload, list):
        if not payload or not all(isinstance(item, dict) for item in payload):
            raise ValueError("A lista JSON não contém checklists válidos.")
        raw_templates = payload
    else:
        raise ValueError("Formato JSON de checklist inválido.")

    used_ids = set(existing_ids or set())
    imported: list[dict[str, Any]] = []
    for raw_template in raw_templates:
        template = normalize_template(raw_template)
        original_id = str(template.get("id") or "")
        if not original_id or original_id in used_ids:
            template["id"] = new_id("checklist")
            template["title"] = _copy_title(str(template.get("title") or "Checklist sem nome"), used_ids)
        used_ids.add(str(template["id"]))
        imported.append(template)
    return imported


def _copy_title(title: str, _used_ids: set[str]) -> str:
    # Keep imports understandable without trying to infer all existing titles;
    # the generated checklist ID already guarantees storage uniqueness.
    return f"{title} (importado)"


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4()}"


def load_templates() -> list[dict[str, Any]]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if not DATA_FILE.exists():
        return []

    with DATA_FILE.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, list):
        raise ValueError("O arquivo checklistTemplates.json deve conter uma lista.")

    return [normalize_template(template) for template in data]


def save_templates(templates: list[dict[str, Any]]) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    if DATA_FILE.exists():
        create_backup()

    normalized = [normalize_template(template) for template in templates]

    temporary_file = DATA_FILE.with_suffix(".tmp")

    with temporary_file.open("w", encoding="utf-8") as file:
        json.dump(normalized, file, ensure_ascii=False, indent=2)

    temporary_file.replace(DATA_FILE)
    prune_backups()

    return DATA_FILE


def create_backup() -> Path | None:
    if not DATA_FILE.exists():
        return None

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    backup_path = BACKUP_DIR / f"checklistTemplates-backup-{timestamp}-python.json"

    shutil.copy2(DATA_FILE, backup_path)

    return backup_path


def prune_backups() -> None:
    if not BACKUP_DIR.exists():
        return

    backups = sorted(
        BACKUP_DIR.glob("checklistTemplates-backup-*.json"),
        key=lambda path: path.name,
        reverse=True,
    )

    for old_backup in backups[MAX_BACKUPS:]:
        old_backup.unlink(missing_ok=True)


def normalize_template(template: Any) -> dict[str, Any]:
    if not isinstance(template, dict):
        template = {}

    normalized = {
        "id": str(template.get("id") or new_id("checklist")),
        "title": str(template.get("title") or "Checklist sem nome"),
        "subtitle": str(template.get("subtitle") or ""),
        "baseLegal": str(template.get("baseLegal") or ""),
        "description": str(template.get("description") or ""),
        "sections": [],
        "sourceMetadata": dict(template.get("sourceMetadata") or {}) if isinstance(template.get("sourceMetadata"), dict) else {},
        "scanReport": dict(template.get("scanReport") or {}) if isinstance(template.get("scanReport"), dict) else {},
        "scanCandidates": [dict(item) for item in template.get("scanCandidates", []) if isinstance(item, dict)] if isinstance(template.get("scanCandidates"), list) else [],
    }

    raw_sections = template.get("sections")

    if isinstance(raw_sections, list):
        normalized["sections"] = [
            normalize_section(section, index + 1)
            for index, section in enumerate(raw_sections)
        ]
    elif isinstance(template.get("items"), list):
        normalized["sections"] = [
            {
                "id": new_id("section"),
                "number": "1",
                "title": "DOCUMENTOS / ITENS",
                "items": [
                    normalize_item(item, index + 1)
                    for index, item in enumerate(template.get("items", []))
                ],
            }
        ]

    return normalized


def normalize_section(section: Any, fallback_number: int) -> dict[str, Any]:
    if not isinstance(section, dict):
        section = {}

    raw_items = section.get("items")

    return {
        "id": str(section.get("id") or new_id("section")),
        "number": str(section.get("number") or fallback_number),
        "title": str(section.get("title") or "SEÇÃO SEM TÍTULO"),
        "items": [
            normalize_item(item, index + 1)
            for index, item in enumerate(raw_items if isinstance(raw_items, list) else [])
        ],
    }


def normalize_item(item: Any, fallback_number: int) -> dict[str, Any]:
    if not isinstance(item, dict):
        item = {}

    return {
        "id": str(item.get("id") or new_id("item")),
        "number": str(item.get("number") or fallback_number),
        "documento": str(item.get("documento") or ""),
        "normativo": str(item.get("normativo") or ""),
        "situacao": str(item.get("situacao") or "") if "situacao" in item else "N/A",
        "folha": str(item.get("folha") or ""),
        "observacao": str(item.get("observacao") or ""),
        "description": str(item.get("description") or ""),
        "requiredDocuments": normalize_text_list(item.get("requiredDocuments")),
        "notes": normalize_text_list(item.get("notes")),
        "scanConfidence": str(item.get("scanConfidence") or ""),
        "scanEvidence": normalize_text_list(item.get("scanEvidence")),
        "scanCandidateId": str(item.get("scanCandidateId") or ""),
        "scanSource": str(item.get("scanSource") or ""),
        "scanPage": int(item.get("scanPage") or 0),
        "scanRect": list(item.get("scanRect") or []) if isinstance(item.get("scanRect"), list) else [],
        "scanConfidenceValue": float(item.get("scanConfidenceValue") or 0.0),
        "scanDimensions": dict(item.get("scanDimensions") or {}) if isinstance(item.get("scanDimensions"), dict) else {},
        "scanReviewed": bool(item.get("scanReviewed", False)),
    }


def normalize_text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []

    return [str(item).strip() for item in value if str(item).strip()]
