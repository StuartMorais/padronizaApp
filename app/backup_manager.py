from __future__ import annotations

import json
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSettings

from app.runtime_settings import APPLICATION, ORGANIZATION


class BackupError(RuntimeError):
    pass


def create_backup(
    project_root: Path,
    destination: Path,
    *,
    reason: str = "manual",
) -> Path:
    project_root = Path(
        project_root
    ).resolve()
    destination = Path(
        destination
    ).resolve()
    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if destination.suffix.lower() != ".zip":
        destination = (
            destination.with_suffix(
                ".zip"
            )
        )

    settings = QSettings(
        ORGANIZATION,
        APPLICATION,
    )
    settings_export = {
        key: settings.value(key)
        for key in settings.allKeys()
    }

    metadata = {
        "created_at": datetime.now()
        .replace(microsecond=0)
        .isoformat(),
        "application": APPLICATION,
        "format": 2,
        "reason": str(reason),
    }

    with tempfile.TemporaryDirectory(
        prefix="padroniza-backup-"
    ) as temporary:
        temporary_root = Path(temporary)
        settings_path = (
            temporary_root
            / "settings.json"
        )
        settings_path.write_text(
            json.dumps(
                settings_export,
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

        with zipfile.ZipFile(
            destination,
            "w",
            zipfile.ZIP_DEFLATED,
        ) as archive:
            archive.writestr(
                "backup_info.json",
                json.dumps(
                    metadata,
                    ensure_ascii=False,
                    indent=2,
                ),
            )
            archive.write(
                settings_path,
                "settings.json",
            )

            for folder_name in (
                "templates",
                "data",
            ):
                folder = (
                    project_root
                    / folder_name
                )
                if not folder.exists():
                    continue

                for path in folder.rglob(
                    "*"
                ):
                    if (
                        path.is_file()
                        and path.resolve()
                        != destination
                    ):
                        archive.write(
                            path,
                            path.relative_to(
                                project_root
                            ),
                        )

    return destination


def inspect_backup(
    backup_path: Path,
) -> dict[str, Any]:
    backup_path = Path(
        backup_path
    ).resolve()

    if not backup_path.exists():
        raise BackupError(
            "O arquivo de backup "
            f"não existe: {backup_path}"
        )

    try:
        with zipfile.ZipFile(
            backup_path,
            "r",
        ) as archive:
            names = archive.namelist()
            if (
                "backup_info.json"
                not in names
            ):
                raise BackupError(
                    "O ZIP selecionado não "
                    "é um backup do Padroniza."
                )

            try:
                metadata = json.loads(
                    archive.read(
                        "backup_info.json"
                    ).decode("utf-8")
                )
            except RuntimeError as exc:
                raise BackupError(
                    "Não foi possível ler "
                    "o conteúdo deste backup."
                ) from exc
            except (
                UnicodeDecodeError,
                json.JSONDecodeError,
            ) as exc:
                raise BackupError(
                    "Os metadados do "
                    "backup são inválidos."
                ) from exc

            entries = [
                {
                    "name": item.filename,
                    "size": item.file_size,
                }
                for item in archive.infolist()
                if not item.is_dir()
            ]
            return {
                "metadata": metadata,
                "entries": entries,
            }
    except (
        zipfile.BadZipFile,
        OSError,
    ) as exc:
        raise BackupError(
            "O backup selecionado "
            f"é inválido: {exc}"
        ) from exc


def restore_backup(
    project_root: Path,
    backup_path: Path,
) -> None:
    project_root = Path(
        project_root
    ).resolve()
    backup_path = Path(
        backup_path
    ).resolve()

    if not backup_path.exists():
        raise BackupError(
            "O arquivo de backup "
            f"não existe: {backup_path}"
        )

    with tempfile.TemporaryDirectory(
        prefix="padroniza-restore-"
    ) as temporary:
        temporary_root = Path(temporary)

        try:
            with zipfile.ZipFile(
                backup_path,
                "r",
            ) as archive:
                _safe_extract(
                    archive,
                    temporary_root,
                )
        except RuntimeError as exc:
            raise BackupError(
                "Não foi possível extrair "
                "o conteúdo deste backup."
            ) from exc
        except (
            zipfile.BadZipFile,
            OSError,
        ) as exc:
            raise BackupError(
                "O backup selecionado "
                f"é inválido: {exc}"
            ) from exc

        if not (
            temporary_root
            / "backup_info.json"
        ).exists():
            raise BackupError(
                "O ZIP selecionado não "
                "é um backup do Padroniza."
            )

        for folder_name in (
            "templates",
            "data",
        ):
            incoming = (
                temporary_root
                / folder_name
            )
            if not incoming.exists():
                continue

            destination = (
                project_root
                / folder_name
            )
            backup_existing = (
                project_root
                / (
                    f".{folder_name}"
                    "-before-restore"
                )
            )

            if backup_existing.exists():
                shutil.rmtree(
                    backup_existing
                )

            if destination.exists():
                destination.replace(
                    backup_existing
                )

            shutil.copytree(
                incoming,
                destination,
            )

            if backup_existing.exists():
                shutil.rmtree(
                    backup_existing
                )

        settings_path = (
            temporary_root
            / "settings.json"
        )
        if settings_path.exists():
            try:
                settings_data = json.loads(
                    settings_path.read_text(
                        encoding="utf-8"
                    )
                )
            except json.JSONDecodeError:
                settings_data = {}

            if isinstance(
                settings_data,
                dict,
            ):
                settings = QSettings(
                    ORGANIZATION,
                    APPLICATION,
                )
                settings.clear()
                for key, value in (
                    settings_data.items()
                ):
                    settings.setValue(
                        str(key),
                        value,
                    )
                settings.sync()


def create_scheduled_backup(
    project_root: Path,
    backup_dir: Path,
    *,
    retention: int = 7,
    reason: str = "scheduled",
) -> Path:
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    timestamp = datetime.now().strftime(
        "%Y-%m-%d_%H-%M-%S"
    )
    path = create_backup(
        project_root,
        backup_dir
        / (
            f"padroniza-{reason}-"
            f"{timestamp}.zip"
        ),
        reason=reason,
    )
    cleanup_backups(
        backup_dir,
        retention=retention,
    )
    return path


def cleanup_backups(
    backup_dir: Path,
    *,
    retention: int,
) -> None:
    retention = max(
        1,
        int(retention),
    )
    backup_dir = Path(backup_dir)

    backups = sorted(
        {
            *backup_dir.glob(
                "padroniza-*.zip"
            ),
            *backup_dir.glob(
                "docgen-*.zip"
            ),
        },
        key=lambda path: (
            path.stat().st_mtime
        ),
        reverse=True,
    )

    for path in backups[retention:]:
        path.unlink(
            missing_ok=True
        )


def _safe_extract(
    archive: zipfile.ZipFile,
    destination: Path,
) -> None:
    destination = (
        destination.resolve()
    )

    for member in archive.infolist():
        target = (
            destination
            / member.filename
        ).resolve()

        try:
            target.relative_to(
                destination
            )
        except ValueError as exc:
            raise BackupError(
                "O ZIP contém um "
                "caminho inseguro."
            ) from exc

    archive.extractall(
        destination
    )
