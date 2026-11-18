"""Export all portable Padroniza data to a single integrity-checked JSON file."""
from __future__ import annotations

import base64
import hashlib
from collections.abc import Iterable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.constants import APPLICATION, ORGANIZATION
from app.core.json_io import atomic_write_json


PORTABLE_JSON_FORMAT = "padroniza-portable-json"
PORTABLE_JSON_VERSION = 1

MAX_PORTABLE_FILES = 25_000
MAX_PORTABLE_TOTAL_BYTES = 1 * 1024 * 1024 * 1024
MAX_PORTABLE_FILE_BYTES = 256 * 1024 * 1024


class PortableJsonError(RuntimeError):
    """Raised when a portable export would exceed its safety contract."""


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (bytes, bytearray, memoryview)) or value.__class__.__name__ == "QByteArray":
        raw = bytes(value)
        return {
            "encoding": "base64",
            "data": base64.b64encode(raw).decode("ascii"),
        }
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        try:
            return isoformat()
        except (TypeError, ValueError):
            pass
    return str(value)


def _read_settings() -> dict[str, Any]:
    from PySide6.QtCore import QSettings

    store = QSettings(ORGANIZATION, APPLICATION)
    return {key: store.value(key) for key in store.allKeys()}


def _write_portable_json(
    project_root: Path,
    destination: Path,
    *,
    source_folders: Iterable[Path],
    settings: Mapping[str, Any],
    includes: list[str],
    excludes: list[str],
    scope_details: Mapping[str, Any] | None = None,
) -> Path:
    project_root = Path(project_root).resolve()
    destination = Path(destination).resolve()
    if destination.suffix.lower() != ".json":
        destination = destination.with_suffix(".json")

    candidates: list[tuple[Path, str, int]] = []
    total_bytes = 0
    for source_folder in source_folders:
        folder = Path(source_folder).resolve()
        if not folder.exists():
            continue
        try:
            folder.relative_to(project_root)
        except ValueError as exc:
            raise PortableJsonError(f"A pasta '{folder}' está fora do projeto.") from exc
        folder_root = folder
        for path in sorted(folder.rglob("*"), key=lambda item: item.as_posix().lower()):
            if not path.is_file() or path.resolve() == destination:
                continue
            resolved = path.resolve()
            try:
                resolved.relative_to(folder_root)
            except ValueError as exc:
                raise PortableJsonError(f"O arquivo '{path}' aponta para fora do projeto.") from exc
            size = resolved.stat().st_size
            if size > MAX_PORTABLE_FILE_BYTES:
                raise PortableJsonError(f"O arquivo '{path.name}' excede o limite por arquivo.")
            total_bytes += size
            if total_bytes > MAX_PORTABLE_TOTAL_BYTES:
                raise PortableJsonError("O conteúdo excede o limite total do JSON portátil.")
            candidates.append((resolved, resolved.relative_to(project_root).as_posix(), size))
            if len(candidates) > MAX_PORTABLE_FILES:
                raise PortableJsonError("O projeto contém arquivos demais para o JSON portátil.")

    files: list[dict[str, Any]] = []
    for path, relative_path, expected_size in candidates:
        raw = path.read_bytes()
        if len(raw) != expected_size:
            raise PortableJsonError(f"O arquivo '{relative_path}' mudou durante a exportação.")
        files.append(
            {
                "path": relative_path,
                "size": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "encoding": "base64",
                "data": base64.b64encode(raw).decode("ascii"),
            }
        )

    scope = {
        "includes": list(includes),
        "excludes": list(excludes),
    }
    if scope_details:
        scope.update(_json_safe(scope_details))
    payload = {
        "format": PORTABLE_JSON_FORMAT,
        "format_version": PORTABLE_JSON_VERSION,
        "application": "Padroniza",
        "created_at": datetime.now().astimezone().replace(microsecond=0).isoformat(),
        "scope": scope,
        "summary": {
            "file_count": len(files),
            "uncompressed_bytes": total_bytes,
        },
        "settings": _json_safe(dict(settings)),
        "files": files,
    }
    atomic_write_json(destination, payload)
    return destination


def export_templates_portable_json(
    project_root: Path,
    destination: Path,
    template_ids: Iterable[str],
) -> Path:
    """Export only explicitly selected Padroniza model folders."""
    project_root = Path(project_root).resolve()
    templates_root = (project_root / "templates").resolve()
    selected_ids = sorted({str(template_id).strip() for template_id in template_ids if str(template_id).strip()})
    if not selected_ids:
        raise PortableJsonError("Selecione ao menos um modelo para exportar.")

    source_folders: list[Path] = []
    for template_id in selected_ids:
        folder = (templates_root / template_id).resolve()
        try:
            relative = folder.relative_to(templates_root)
        except ValueError as exc:
            raise PortableJsonError(f"Identificador de modelo inválido: {template_id}") from exc
        if len(relative.parts) != 1 or not folder.is_dir() or not (folder / "template.json").is_file():
            raise PortableJsonError(f"Modelo não encontrado: {template_id}")
        source_folders.append(folder)

    return _write_portable_json(
        project_root,
        destination,
        source_folders=source_folders,
        settings={},
        includes=["templates"],
        excludes=["data", "settings", "output", "backups"],
        scope_details={"template_ids": selected_ids},
    )


def export_all_portable_json(
    project_root: Path,
    destination: Path,
    *,
    settings: Mapping[str, Any] | None = None,
) -> Path:
    """Export templates, data and settings without generated output or backups."""
    project_root = Path(project_root).resolve()
    settings_export = _read_settings() if settings is None else dict(settings)
    return _write_portable_json(
        project_root,
        destination,
        source_folders=(project_root / "templates", project_root / "data"),
        settings=settings_export,
        includes=["templates", "data", "settings"],
        excludes=["output", "backups"],
    )
