from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from app.services.backup import (
    BackupError,
    _restore_data_folders_transactionally,
    restore_backup,
)


def _write(folder: Path, relative: str, text: str) -> None:
    path = folder / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_transactional_restore_rolls_back_all_folders_on_swap_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    extracted = tmp_path / "extracted"
    project.mkdir()
    extracted.mkdir()
    _write(project, "templates/current.txt", "old-template")
    _write(project, "data/current.txt", "old-data")
    _write(extracted, "templates/current.txt", "new-template")
    _write(extracted, "data/current.txt", "new-data")

    original_replace = Path.replace

    def failing_replace(self: Path, target: Path):
        if self.name == "incoming-data":
            raise OSError("simulated disk failure")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", failing_replace)

    with pytest.raises(BackupError):
        _restore_data_folders_transactionally(
            project,
            extracted,
            ("templates", "data"),
        )

    assert (project / "templates/current.txt").read_text(encoding="utf-8") == "old-template"
    assert (project / "data/current.txt").read_text(encoding="utf-8") == "old-data"


def test_invalid_settings_cancel_restore_before_live_data_changes(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _write(project, "templates/current.txt", "old-template")
    _write(project, "data/current.txt", "old-data")

    backup = tmp_path / "backup.zip"
    with zipfile.ZipFile(backup, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("backup_info.json", json.dumps({"format": 2}))
        archive.writestr("settings.json", "{not valid json")
        archive.writestr("templates/current.txt", "new-template")
        archive.writestr("data/current.txt", "new-data")

    with pytest.raises(BackupError, match="configurações"):
        restore_backup(project, backup)

    assert (project / "templates/current.txt").read_text(encoding="utf-8") == "old-template"
    assert (project / "data/current.txt").read_text(encoding="utf-8") == "old-data"


def test_future_backup_schema_is_rejected_before_restore(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _write(project, "data/current.txt", "old-data")

    backup = tmp_path / "future.zip"
    with zipfile.ZipFile(backup, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "backup_info.json",
            json.dumps({"format": 2, "schema_version": 999}),
        )
        archive.writestr("settings.json", "{}")
        archive.writestr("data/current.txt", "new-data")

    with pytest.raises(BackupError, match="versão mais nova"):
        restore_backup(project, backup)

    assert (project / "data/current.txt").read_text(encoding="utf-8") == "old-data"
