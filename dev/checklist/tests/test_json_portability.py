import json
from pathlib import Path

from checklist_app.storage import (
    CHECKLIST_JSON_SCHEMA,
    export_checklist_json,
    import_checklists_json,
    normalize_template,
)


def sample_checklist():
    return normalize_template(
        {
            "id": "checklist-demo",
            "title": "Checklist Demo",
            "subtitle": "Lei 14.133/21",
            "baseLegal": "Lei 14.133/21",
            "sections": [
                {
                    "number": "1",
                    "title": "FORMALIDADES",
                    "items": [
                        {
                            "number": "1.1",
                            "documento": "Documento de Formalização de Demanda",
                            "normativo": "Art. 12",
                            "situacao": "Sim",
                            "folha": "12",
                            "observacao": "Conferido",
                        }
                    ],
                }
            ],
        }
    )


def test_portable_json_round_trip(tmp_path: Path):
    source = sample_checklist()
    path = export_checklist_json(source, tmp_path / "demo.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema"] == CHECKLIST_JSON_SCHEMA
    imported = import_checklists_json(path)
    assert len(imported) == 1
    assert imported[0]["title"] == "Checklist Demo"
    assert imported[0]["sections"][0]["items"][0]["situacao"] == "Sim"
    assert imported[0]["sections"][0]["items"][0]["folha"] == "12"


def test_import_collision_creates_copy(tmp_path: Path):
    source = sample_checklist()
    path = export_checklist_json(source, tmp_path / "demo.json")
    imported = import_checklists_json(path, existing_ids={"checklist-demo"})
    assert imported[0]["id"] != "checklist-demo"
    assert imported[0]["title"].endswith("(importado)")


def test_import_accepts_legacy_raw_list(tmp_path: Path):
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps([sample_checklist()], ensure_ascii=False), encoding="utf-8")
    imported = import_checklists_json(path)
    assert len(imported) == 1
    assert imported[0]["sections"][0]["items"][0]["documento"].startswith("Documento")


def test_import_rejects_unrelated_json(tmp_path: Path):
    path = tmp_path / "bad.json"
    path.write_text('{"hello": "world"}', encoding="utf-8")
    try:
        import_checklists_json(path)
    except ValueError as exc:
        assert "não parece conter" in str(exc)
    else:
        raise AssertionError("Unrelated JSON should be rejected")
