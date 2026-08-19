from __future__ import annotations

from pathlib import Path

from app.core import paths as paths_module


def test_source_mode_resolves_project_root(monkeypatch) -> None:
    monkeypatch.delenv("PADRONIZA_DATA_DIR", raising=False)
    monkeypatch.delattr(paths_module.sys, "frozen", raising=False)
    monkeypatch.delattr(paths_module.sys, "_MEIPASS", raising=False)

    resolved = paths_module.resolve_application_paths()
    expected_root = Path(paths_module.__file__).resolve().parents[2]

    assert resolved.resource_root == expected_root
    assert resolved.storage_root == expected_root
    assert resolved.executable_root == expected_root
    assert resolved.default_output_root == expected_root / "output"

    # These are the resources that disappeared from the UI when the root
    # accidentally resolved to app/ instead of the project directory.
    assert (resolved.resource_root / "app" / "ui" / "styles" / "light.qss").is_file()
    assert (resolved.resource_root / "templates").is_dir()
