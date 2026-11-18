from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

from app.services.portable_json import (
    export_all_portable_json,
    export_templates_portable_json,
)


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def test_portable_json_embeds_files_settings_and_integrity(tmp_path: Path) -> None:
    project = tmp_path / "project"
    docx = b"PK\x03\x04document-bytes"
    data = b'{"draft": true}'
    _write(project / "templates" / "example" / "model.docx", docx)
    _write(project / "data" / "drafts.json", data)
    _write(project / "output" / "generated.docx", b"generated")
    _write(project / "backups" / "old.zip", b"backup")

    destination = export_all_portable_json(
        project,
        tmp_path / "portable",
        settings={"theme": "dark", "geometry": b"window-state"},
    )
    payload = json.loads(destination.read_text(encoding="utf-8"))
    entries = {entry["path"]: entry for entry in payload["files"]}

    assert payload["format"] == "padroniza-portable-json"
    assert payload["format_version"] == 1
    assert payload["summary"] == {
        "file_count": 2,
        "uncompressed_bytes": len(docx) + len(data),
    }
    assert set(entries) == {
        "templates/example/model.docx",
        "data/drafts.json",
    }
    assert base64.b64decode(entries["templates/example/model.docx"]["data"]) == docx
    assert entries["templates/example/model.docx"]["sha256"] == hashlib.sha256(docx).hexdigest()
    assert payload["settings"]["theme"] == "dark"
    assert base64.b64decode(payload["settings"]["geometry"]["data"]) == b"window-state"


def test_portable_json_does_not_include_its_destination(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _write(project / "data" / "value.json", b"{}")
    destination = project / "data" / "portable.json"

    export_all_portable_json(project, destination, settings={})
    payload = json.loads(destination.read_text(encoding="utf-8"))

    assert [entry["path"] for entry in payload["files"]] == ["data/value.json"]


def test_selected_template_export_contains_only_requested_models(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _write(project / "templates" / "first" / "template.json", b"{}")
    _write(project / "templates" / "first" / "template.docx", b"first-docx")
    _write(project / "templates" / "second" / "template.json", b"{}")
    _write(project / "templates" / "second" / "template.docm", b"second-docm")
    _write(project / "templates" / "ignored" / "template.json", b"{}")
    _write(project / "templates" / "ignored" / "template.docx", b"ignored")
    _write(project / "data" / "drafts.json", b"{}")

    destination = export_templates_portable_json(
        project,
        tmp_path / "selected.json",
        ["second", "first"],
    )
    payload = json.loads(destination.read_text(encoding="utf-8"))
    paths = {entry["path"] for entry in payload["files"]}

    assert payload["scope"] == {
        "includes": ["templates"],
        "excludes": ["data", "settings", "output", "backups"],
        "template_ids": ["first", "second"],
    }
    assert payload["settings"] == {}
    assert paths == {
        "templates/first/template.json",
        "templates/first/template.docx",
        "templates/second/template.json",
        "templates/second/template.docm",
    }


def test_padroniza_ui_offers_specific_multiple_and_full_json_exports() -> None:
    root = Path(__file__).resolve().parents[2]
    main_source = (root / "app" / "ui" / "main_window.py").read_text(encoding="utf-8")
    mixin_source = (root / "app" / "ui" / "mixins" / "backup.py").read_text(encoding="utf-8")
    manager_source = (
        root / "app" / "ui" / "template_manager" / "template_manager_dialog.py"
    ).read_text(encoding="utf-8")

    assert "Exportar modelo específico…" in manager_source
    assert "Exportar vários modelos…" in manager_source
    assert "Exportar tudo…" in manager_source
    assert "self.json_export_button" in manager_source
    assert "export_specific_json_requested.connect" in main_source
    assert "export_multiple_json_requested.connect" in main_source
    assert "export_all_json_requested.connect" in main_source
    assert "def _export_specific_template_json(self)" in mixin_source
    assert "def _export_multiple_templates_json(self)" in mixin_source
