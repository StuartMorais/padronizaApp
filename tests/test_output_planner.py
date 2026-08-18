from __future__ import annotations

from pathlib import Path

from app.local_data import LocalDataStore
from app.output_planner import OutputPlanner
from app.template_loader import TemplatePackage


def _package(tmp_path: Path, *, numbering: bool = True) -> TemplatePackage:
    source = tmp_path / "source.docx"
    source.write_bytes(b"placeholder")
    return TemplatePackage(
        template_id="test-template",
        name="Modelo Teste",
        description="",
        category="",
        version="1.0",
        source_path=source,
        fields=[],
        output_filename="{{sequence}} - {{cliente}}.docx",
        config={
            "output": {
                "filename_pattern": "{{sequence}} - {{cliente}}.docx",
                "folder_pattern": "{{cliente}}/{{year}}",
            },
            "numbering": {
                "enabled": numbering,
                "key": "documents",
                "padding": 4,
            },
        },
    )


def test_plan_peeks_without_consuming_sequence(tmp_path: Path) -> None:
    store = LocalDataStore(tmp_path / "data")
    planner = OutputPlanner(store)
    package = _package(tmp_path)

    first = planner.plan(
        package,
        {"cliente": "ACME/Brasil"},
        output_root=tmp_path / "output",
    )
    second = planner.plan(
        package,
        {"cliente": "ACME/Brasil"},
        output_root=tmp_path / "output",
    )

    assert first.sequence == 1
    assert second.sequence == 1
    assert first.path.name == "0001 - ACME-Brasil.docx"
    assert store.peek_sequence("documents") == 1


def test_commit_sequence_advances_only_when_called(tmp_path: Path) -> None:
    store = LocalDataStore(tmp_path / "data")
    planner = OutputPlanner(store)
    package = _package(tmp_path)

    assert planner.peek_sequence(package) == 1
    assert planner.commit_sequence(package) == 1
    assert planner.peek_sequence(package) == 2


def test_numbering_can_be_disabled(tmp_path: Path) -> None:
    store = LocalDataStore(tmp_path / "data")
    planner = OutputPlanner(store)
    package = _package(tmp_path, numbering=False)

    assert planner.peek_sequence(package) is None
    assert planner.commit_sequence(package) is None
