from __future__ import annotations

from pathlib import Path

from app.document.conversion.service import DocumentConverter
from app.repositories.field_library import FieldLibraryStore
from app.repositories.local_data import JsonFileStore, LocalDataStore
from app.repositories.templates import TemplateRepository
from app.services.generation import GenerationService
from app.services.output_planner import OutputPlanner


def _storage_tree(root: Path) -> None:
    for folder in ("templates", "data", "backups", "output"):
        (root / folder).mkdir(parents=True, exist_ok=True)


def test_repository_and_service_constructors_share_one_storage_contract(tmp_path: Path) -> None:
    """Construct every non-GUI repository/service used by the application.

    This intentionally catches signature drift between collaborating classes.
    The field-library ``kind`` regression that previously only appeared after
    clicking "Novo modelo" would fail here as well as in the GUI smoke suite.
    """

    _storage_tree(tmp_path)

    local_store = LocalDataStore(tmp_path / "data")
    field_library = FieldLibraryStore(tmp_path / "data")
    repository = TemplateRepository(tmp_path / "templates")
    planner = OutputPlanner(local_store)
    converter = DocumentConverter(backends=[])
    generation = GenerationService(
        local_store,
        output_planner=planner,
        converter=converter,
    )

    assert local_store.data_dir == tmp_path / "data"
    assert field_library.path == tmp_path / "data" / "field_library.json"
    assert repository.templates_dir == tmp_path / "templates"
    assert generation.output_planner is planner
    assert generation.converter is converter


def test_json_file_store_has_a_safe_default_kind(tmp_path: Path) -> None:
    store = JsonFileStore(tmp_path / "feature_state.json", {})
    assert store.kind == "feature_state"
    store.write({"enabled": True})
    assert store.read() == {"enabled": True}
