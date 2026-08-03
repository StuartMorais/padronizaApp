from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path


APPLICATION_FOLDER = "Padroniza"
STORAGE_VERSION_MARKER = ".storage-v1"


class StorageInitializationError(RuntimeError):
    """Raised when Padroniza cannot prepare a persistent writable folder."""


@dataclass(frozen=True)
class ApplicationPaths:
    """Resolved read-only resources and persistent writable folders."""

    resource_root: Path
    storage_root: Path
    executable_root: Path
    default_output_root: Path
    frozen: bool
    one_file: bool


def resolve_application_paths() -> ApplicationPaths:
    """Resolve paths for source, installer, onedir and one-file builds.

    PyInstaller one-file applications run bundled files from a temporary
    ``_MEI...`` directory. That location must never be used for templates,
    history, backups or generated documents because it is removed when the
    application closes.
    """

    source_root = Path(__file__).resolve().parent.parent
    frozen = bool(getattr(sys, "frozen", False))

    bundle_value = getattr(sys, "_MEIPASS", None)
    resource_root = (
        Path(bundle_value).resolve()
        if bundle_value
        else source_root.resolve()
    )

    executable_root = (
        Path(sys.executable).resolve().parent
        if frozen
        else source_root.resolve()
    )
    one_file = frozen and resource_root != executable_root

    override = os.environ.get("PADRONIZA_DATA_DIR", "").strip()
    if override:
        storage_root = Path(override).expanduser().resolve()
    elif frozen:
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        if local_app_data:
            storage_root = (
                Path(local_app_data).expanduser().resolve()
                / APPLICATION_FOLDER
            )
        else:
            storage_root = Path.home().resolve() / ".padroniza"
    else:
        storage_root = source_root.resolve()

    if frozen:
        default_output_root = _windows_documents_root() / APPLICATION_FOLDER
    else:
        default_output_root = source_root.resolve() / "output"

    return ApplicationPaths(
        resource_root=resource_root,
        storage_root=storage_root,
        executable_root=executable_root,
        default_output_root=default_output_root,
        frozen=frozen,
        one_file=one_file,
    )


def initialize_persistent_storage(paths: ApplicationPaths) -> None:
    """Create writable folders, migrate old local data and seed resources."""

    root = paths.storage_root
    try:
        root.mkdir(parents=True, exist_ok=True)
        for folder_name in (
            "data",
            "templates",
            "backups",
        ):
            (root / folder_name).mkdir(parents=True, exist_ok=True)

        paths.default_output_root.mkdir(parents=True, exist_ok=True)
        _assert_writable(root)
    except OSError as exc:
        raise StorageInitializationError(
            "O Padroniza não conseguiu preparar uma pasta gravável para "
            f"salvar seus dados.\n\nPasta: {root}\n\nDetalhes: {exc}"
        ) from exc

    # Preserve data from older onedir/portable releases that stored writable
    # folders beside Padroniza.exe. Copy only missing files; never overwrite.
    if paths.frozen and paths.executable_root != root:
        _merge_legacy_root(
            paths.executable_root,
            root,
            paths.default_output_root,
        )

    # Bundled templates/examples are read-only seeds. In one-file builds they
    # live inside a temporary extraction directory, so copy them once.
    _merge_directory(
        paths.resource_root / "templates",
        root / "templates",
    )
    _merge_directory(
        paths.resource_root / "examples",
        root / "examples",
    )

    try:
        (root / STORAGE_VERSION_MARKER).write_text(
            "Padroniza persistent storage v1\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise StorageInitializationError(
            "O Padroniza conseguiu criar a pasta de dados, mas não conseguiu "
            f"gravar nela.\n\nPasta: {root}\n\nDetalhes: {exc}"
        ) from exc


def is_transient_pyinstaller_path(path: Path | str) -> bool:
    """Return True for paths inside a PyInstaller one-file _MEI folder."""

    candidate = Path(path).expanduser()
    return any(part.upper().startswith("_MEI") for part in candidate.parts)


def _windows_documents_root() -> Path:
    user_profile = os.environ.get("USERPROFILE", "").strip()
    if user_profile:
        documents = Path(user_profile).expanduser() / "Documents"
        return documents.resolve()
    return (Path.home() / "Documents").resolve()


def _assert_writable(folder: Path) -> None:
    probe = folder / ".padroniza-write-test.tmp"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink()


def _merge_legacy_root(
    source_root: Path,
    destination_root: Path,
    output_root: Path,
) -> None:
    try:
        source_resolved = source_root.resolve()
        destination_resolved = destination_root.resolve()
    except OSError:
        return

    if source_resolved == destination_resolved:
        return

    portable_marker = source_resolved / "portable.flag"
    migrated_marker = destination_resolved / "portable.flag"
    if portable_marker.is_file() and not migrated_marker.exists():
        try:
            shutil.copy2(portable_marker, migrated_marker)
        except OSError:
            pass

    for folder_name in (
        "data",
        "templates",
        "output",
        "backups",
    ):
        source = source_resolved / folder_name
        if folder_name == "output":
            destination = output_root
        else:
            destination = destination_resolved / folder_name
        _merge_directory(source, destination)


def _merge_directory(source: Path, destination: Path) -> None:
    if not source.exists() or not source.is_dir():
        return

    try:
        if source.resolve() == destination.resolve():
            return
    except OSError:
        return

    destination.mkdir(parents=True, exist_ok=True)

    for source_path in source.rglob("*"):
        try:
            relative = source_path.relative_to(source)
        except ValueError:
            continue

        if source_path.name == ".gitkeep":
            continue

        destination_path = destination / relative
        if source_path.is_dir():
            destination_path.mkdir(parents=True, exist_ok=True)
            continue

        if not source_path.is_file() or destination_path.exists():
            continue

        destination_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(source_path, destination_path)
        except OSError:
            # A single inaccessible legacy file must not prevent startup.
            continue
