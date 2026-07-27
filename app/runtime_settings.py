from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings


PORTABLE_MARKER = "portable.flag"
ORGANIZATION = "Padroniza"
APPLICATION = "Padroniza"
LEGACY_ORGANIZATION = "Local Document Tools"
LEGACY_APPLICATION = "DocGen Pro"


def configure_settings_storage(project_root: Path) -> bool:
    """Configure QSettings before any settings object is created."""

    root = Path(project_root)
    portable = (root / PORTABLE_MARKER).exists()
    if portable:
        settings_dir = root / "data" / "settings"
        settings_dir.mkdir(parents=True, exist_ok=True)
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(
            QSettings.Format.IniFormat,
            QSettings.Scope.UserScope,
            str(settings_dir),
        )
    return portable


def migrate_legacy_settings(project_root: Path) -> bool:
    """Copy settings from the former DocGen Pro identity once.

    Existing Padroniza settings always take precedence. The legacy settings
    are left untouched so an older installation can still be opened safely.
    """

    current = QSettings(ORGANIZATION, APPLICATION)
    if current.allKeys():
        return False

    candidates: list[QSettings] = [
        QSettings(LEGACY_ORGANIZATION, LEGACY_APPLICATION),
    ]

    root = Path(project_root)
    settings_dir = root / "data" / "settings"
    for legacy_file in (
        settings_dir / f"{LEGACY_APPLICATION}.ini",
        settings_dir / LEGACY_ORGANIZATION / f"{LEGACY_APPLICATION}.ini",
    ):
        if legacy_file.exists():
            candidates.append(
                QSettings(str(legacy_file), QSettings.Format.IniFormat)
            )

    source: QSettings | None = None
    for candidate in candidates:
        if candidate.allKeys():
            source = candidate
            break

    if source is None:
        return False

    for key in source.allKeys():
        current.setValue(key, source.value(key))
    current.sync()
    return True


def set_portable_mode(project_root: Path, enabled: bool) -> None:
    """Create/remove the portable marker and migrate current settings."""

    root = Path(project_root)
    marker = root / PORTABLE_MARKER
    settings_dir = root / "data" / "settings"
    portable_file = settings_dir / ORGANIZATION / f"{APPLICATION}.ini"
    portable_file.parent.mkdir(parents=True, exist_ok=True)

    current = QSettings(ORGANIZATION, APPLICATION)
    values = {key: current.value(key) for key in current.allKeys()}

    if enabled:
        target = QSettings(str(portable_file), QSettings.Format.IniFormat)
        target.clear()
        for key, value in values.items():
            target.setValue(key, value)
        target.sync()
        marker.write_text("Padroniza portable mode\n", encoding="utf-8")
        return

    target = QSettings(
        QSettings.Format.NativeFormat,
        QSettings.Scope.UserScope,
        ORGANIZATION,
        APPLICATION,
    )
    target.clear()
    for key, value in values.items():
        target.setValue(key, value)
    target.sync()
    marker.unlink(missing_ok=True)
