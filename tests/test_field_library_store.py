from __future__ import annotations

import json
from pathlib import Path

from app.repositories.field_library import DEFAULT_GROUPS, FieldLibraryStore
from app.repositories.local_data import JsonFileStore


def test_json_file_store_infers_kind_from_filename(tmp_path: Path) -> None:
    store = JsonFileStore(tmp_path / "sample_data.json", [])

    store.write([{"value": 1}])

    payload = json.loads((tmp_path / "sample_data.json").read_text(encoding="utf-8"))
    assert payload["kind"] == "sample_data"
    assert store.read() == [{"value": 1}]


def test_field_library_store_opens_and_persists_custom_groups(tmp_path: Path) -> None:
    library = FieldLibraryStore(tmp_path)

    groups = library.list_groups()
    assert len(groups) == len(DEFAULT_GROUPS)

    group_id = library.save_group(
        name="Dados de teste",
        description="Grupo criado pelo teste",
        fields=[{"id": "test.name", "label": "Nome", "type": "text"}],
    )

    reopened = FieldLibraryStore(tmp_path)
    saved = next(group for group in reopened.list_groups() if group["id"] == group_id)
    assert saved["name"] == "Dados de teste"
    assert saved["fields"][0]["id"] == "test.name"

    payload = json.loads((tmp_path / "field_library.json").read_text(encoding="utf-8"))
    assert payload["kind"] == "field_library"
    assert payload["schema_version"] >= 1
