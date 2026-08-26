from __future__ import annotations

import json
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


from app.core.constants import APPLICATION, ORGANIZATION
from app.core.schema import BACKUP_SCHEMA_VERSION


class BackupError(RuntimeError):
    pass


MAX_BACKUP_FILES = 25_000
MAX_BACKUP_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024
MAX_BACKUP_MEMBER_BYTES = 512 * 1024 * 1024


def _settings_store():
    # Import Qt lazily so backup archive validation and filesystem recovery can
    # be tested and reused without requiring the GUI runtime.
    from PySide6.QtCore import QSettings

    return QSettings(ORGANIZATION, APPLICATION)


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

    settings = _settings_store()
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
        "schema_version": BACKUP_SCHEMA_VERSION,
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
            _validate_archive_limits(archive)
            names = archive.namelist()
            if (
                "backup_info.json"
                not in names
            ):
                raise BackupError(
                    "O ZIP selecionado não "
                    "é um backup do Padroniza."
                )

            metadata = _read_backup_metadata(archive)

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
                _validate_archive_limits(archive)
                _read_backup_metadata(archive)
                _safe_extract(
                    archive,
                    temporary_root,
                )
        except BackupError:
            raise
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

        settings_data: dict[str, Any] | None = None
        settings_path = temporary_root / "settings.json"
        if settings_path.exists():
            try:
                parsed_settings = json.loads(settings_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise BackupError(
                    "O arquivo de configurações do backup é inválido. "
                    "A restauração foi cancelada sem alterar os dados atuais."
                ) from exc
            if not isinstance(parsed_settings, dict):
                raise BackupError(
                    "O arquivo de configurações do backup não contém um objeto válido. "
                    "A restauração foi cancelada sem alterar os dados atuais."
                )
            settings_data = parsed_settings

        settings_commit: Callable[[], None] | None = None
        if settings_data is not None:
            resolved_settings = settings_data
            settings_commit = lambda: _apply_settings_transactionally(resolved_settings)

        _restore_data_folders_transactionally(
            project_root,
            temporary_root,
            ("templates", "data"),
            after_activate=settings_commit,
        )


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



def _restore_data_folders_transactionally(
    project_root: Path,
    extracted_root: Path,
    folder_names: tuple[str, ...],
    *,
    after_activate: Callable[[], None] | None = None,
) -> None:
    """Replace restored folders atomically enough to permit rollback.

    Incoming data is copied into a staging directory first. Only fully staged
    folders are swapped into place. If any swap or final settings commit fails,
    every folder already changed in this restore attempt is rolled back to its
    original state before the staging directory is released.
    """

    with tempfile.TemporaryDirectory(
        prefix=".padroniza-restore-stage-",
        dir=str(project_root),
    ) as stage_dir:
        stage_root = Path(stage_dir)
        staged: dict[str, Path] = {}

        for folder_name in folder_names:
            incoming = extracted_root / folder_name
            if not incoming.exists():
                continue
            staged_folder = stage_root / f"incoming-{folder_name}"
            try:
                shutil.copytree(incoming, staged_folder)
            except OSError as exc:
                raise BackupError(
                    f"Não foi possível preparar a restauração da pasta '{folder_name}'. "
                    "Os dados atuais não foram alterados."
                ) from exc
            staged[folder_name] = staged_folder

        activated: list[tuple[Path, Path | None]] = []
        try:
            for folder_name, staged_folder in staged.items():
                destination = project_root / folder_name
                previous = stage_root / f"previous-{folder_name}"
                had_previous = destination.exists()
                if had_previous:
                    destination.replace(previous)
                try:
                    staged_folder.replace(destination)
                except OSError:
                    if had_previous and previous.exists() and not destination.exists():
                        previous.replace(destination)
                    raise
                activated.append((destination, previous if had_previous else None))

            if after_activate is not None:
                after_activate()
        except Exception as exc:
            for destination, previous in reversed(activated):
                try:
                    if destination.exists():
                        shutil.rmtree(destination)
                    if previous is not None and previous.exists():
                        previous.replace(destination)
                except OSError:
                    # Preserve the original exception; any surviving previous
                    # folder remains inside the staging directory until cleanup.
                    pass
            if isinstance(exc, BackupError):
                raise BackupError(
                    f"{exc} As pastas restauradas também foram revertidas."
                ) from exc
            raise BackupError(
                "A restauração não pôde substituir os dados atuais. "
                "As pastas já alteradas foram revertidas."
            ) from exc


def _apply_settings_transactionally(settings_data: dict[str, Any]) -> None:
    settings = _settings_store()
    previous = {key: settings.value(key) for key in settings.allKeys()}
    try:
        _write_settings(settings, settings_data)
    except Exception as exc:
        rollback_error: Exception | None = None
        try:
            _write_settings(settings, previous)
        except Exception as restore_exc:  # pragma: no cover - catastrophic backend failure
            rollback_error = restore_exc
        detail = (
            " Também não foi possível restaurar as configurações anteriores."
            if rollback_error is not None
            else " As configurações anteriores foram restauradas."
        )
        raise BackupError(
            "Não foi possível aplicar as configurações do backup." + detail
        ) from exc


def _write_settings(settings: Any, values: dict[str, Any]) -> None:
    settings.clear()
    for key, value in values.items():
        settings.setValue(str(key), value)
    settings.sync()

    status_method = getattr(settings, "status", None)
    if not callable(status_method):
        return
    status = status_method()
    status_name = str(getattr(status, "name", status))
    status_value = getattr(status, "value", status)
    try:
        numeric_status = int(status_value)
    except (TypeError, ValueError):
        numeric_status = 0 if status_name.casefold() in {"noerror", "status.noerror", "0"} else 1
    if numeric_status != 0:
        raise OSError(f"QSettings retornou status de erro: {status_name}")


def _read_backup_metadata(archive: zipfile.ZipFile) -> dict[str, Any]:
    if "backup_info.json" not in archive.namelist():
        raise BackupError("O ZIP selecionado não é um backup do Padroniza.")
    try:
        metadata = json.loads(archive.read("backup_info.json").decode("utf-8"))
    except RuntimeError as exc:
        raise BackupError("Não foi possível ler o conteúdo deste backup.") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BackupError("Os metadados do backup são inválidos.") from exc
    if not isinstance(metadata, dict):
        raise BackupError("Os metadados do backup não contêm um objeto válido.")
    try:
        schema_version = int(metadata.get("schema_version", 0) or 0)
    except (TypeError, ValueError) as exc:
        raise BackupError("A versão de dados do backup é inválida.") from exc
    if schema_version > BACKUP_SCHEMA_VERSION:
        raise BackupError(
            "Este backup foi criado por uma versão mais nova do Padroniza "
            f"(schema {schema_version}; suportado: {BACKUP_SCHEMA_VERSION}). "
            "Atualize o aplicativo antes de restaurá-lo."
        )
    return metadata

def _validate_archive_limits(archive: zipfile.ZipFile) -> None:
    members = [item for item in archive.infolist() if not item.is_dir()]
    if len(members) > MAX_BACKUP_FILES:
        raise BackupError("O backup contém arquivos demais para ser restaurado com segurança.")

    total_size = sum(max(0, int(item.file_size)) for item in members)
    if total_size > MAX_BACKUP_UNCOMPRESSED_BYTES:
        raise BackupError("O backup é grande demais para ser restaurado com segurança.")

    oversized = next(
        (item for item in members if int(item.file_size) > MAX_BACKUP_MEMBER_BYTES),
        None,
    )
    if oversized is not None:
        raise BackupError(
            f"O arquivo '{oversized.filename}' dentro do backup é grande demais."
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
