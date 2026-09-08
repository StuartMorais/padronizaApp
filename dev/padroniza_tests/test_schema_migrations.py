from __future__ import annotations

import json

import pytest

from app.core.schema import LOCAL_DATA_SCHEMA_VERSION, SchemaVersionError, decode_store
from app.repositories.local_data import LocalDataStore


def test_legacy_local_data_is_migrated_to_versioned_envelope(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    path = data_dir / "profiles.json"
    path.write_text('[{"id":"a","name":"A","values":{}}]', encoding="utf-8")

    store = LocalDataStore(data_dir)
    assert store.list_profiles()[0]["id"] == "a"

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["schema_version"] == LOCAL_DATA_SCHEMA_VERSION
    assert raw["kind"] == "profiles"
    assert raw["data"][0]["id"] == "a"


def test_newer_local_schema_is_rejected():
    with pytest.raises(SchemaVersionError):
        decode_store(
            {"schema_version": LOCAL_DATA_SCHEMA_VERSION + 1, "kind": "profiles", "data": []},
            kind="profiles",
            default=[],
        )


def test_local_store_does_not_silently_discard_newer_schema(tmp_path):
    data_dir = tmp_path / "data-newer"
    data_dir.mkdir()
    (data_dir / "profiles.json").write_text(
        json.dumps({"schema_version": LOCAL_DATA_SCHEMA_VERSION + 1, "kind": "profiles", "data": []}),
        encoding="utf-8",
    )
    store = LocalDataStore(data_dir)
    with pytest.raises(SchemaVersionError):
        store.list_profiles()
