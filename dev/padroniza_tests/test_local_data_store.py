from __future__ import annotations

from pathlib import Path

from app.repositories.local_data import LocalDataStore


def test_local_store_round_trip_for_profiles_drafts_recent_audit_and_sequences(tmp_path: Path) -> None:
    store = LocalDataStore(tmp_path / "data")

    profile_id = store.save_profile(
        name="Empresa Exemplo",
        category="Empresa",
        values={"company.name": "Empresa Exemplo Ltda."},
    )
    assert store.get_profile(profile_id)["name"] == "Empresa Exemplo"
    assert len(store.list_profiles()) == 1

    store.save_draft("modelo-1", {"campo": "valor"})
    assert store.load_draft("modelo-1")["values"] == {"campo": "valor"}
    store.delete_draft("modelo-1")
    assert store.load_draft("modelo-1") is None

    recent_id = store.add_recent({"filename": "teste.docx", "template_id": "modelo-1"})
    assert store.get_recent(recent_id)["filename"] == "teste.docx"
    assert store.list_recent()[0]["id"] == recent_id
    assert store.delete_recent(recent_id)
    assert store.list_recent() == []

    assert store.peek_sequence("modelo-1", 2026) == 1
    assert store.next_sequence("modelo-1", 2026) == 1
    assert store.peek_sequence("modelo-1", 2026) == 2

    audit = store.list_audit()
    assert any(item["action"] == "profile_saved" for item in audit)

    assert store.delete_profile(profile_id)
    assert store.get_profile(profile_id) is None
    assert any(item["action"] == "profile_deleted" for item in store.list_audit())


def test_local_store_clear_recent_and_profile_id_collision(tmp_path: Path) -> None:
    store = LocalDataStore(tmp_path / "data")
    first = store.save_profile(name="Mesmo Nome", values={})
    second = store.save_profile(name="Mesmo Nome", values={})
    assert first != second

    store.add_recent({"filename": "a.docx"})
    store.add_recent({"filename": "b.docx"})
    assert len(store.list_recent()) == 2
    store.clear_recent()
    assert store.list_recent() == []
