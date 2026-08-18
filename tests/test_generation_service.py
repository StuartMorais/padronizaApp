from __future__ import annotations

from pathlib import Path

import pytest

from app.docx_engine import DocumentGenerationError
from app.local_data import LocalDataStore
from app.output_planner import OutputPlanner
from app.services.generation_service import GenerationService
from app.template_loader import TemplatePackage


def _package(tmp_path: Path) -> TemplatePackage:
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
        output_filename="{{sequence}}.docx",
        config={
            "output": {"filename_pattern": "{{sequence}}.docx"},
            "numbering": {
                "enabled": True,
                "key": "documents",
                "padding": 4,
            },
        },
    )


def test_failed_docx_generation_does_not_consume_sequence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = LocalDataStore(tmp_path / "data")
    planner = OutputPlanner(store)
    service = GenerationService(store, planner)
    package = _package(tmp_path)

    def fail_generation(*args, **kwargs):
        raise DocumentGenerationError("boom")

    monkeypatch.setattr(
        "app.services.generation_service.generate_docx",
        fail_generation,
    )

    with pytest.raises(DocumentGenerationError):
        service.generate_docx(package, {}, tmp_path / "result.docx")

    assert store.peek_sequence("documents") == 1
    assert store.list_recent() == []


def test_successful_docx_generation_consumes_sequence_and_records_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = LocalDataStore(tmp_path / "data")
    planner = OutputPlanner(store)
    service = GenerationService(store, planner)
    package = _package(tmp_path)
    output_path = tmp_path / "0001.docx"

    def fake_generation(template_path, destination, values):
        Path(destination).write_bytes(b"generated")

    monkeypatch.setattr(
        "app.services.generation_service.generate_docx",
        fake_generation,
    )

    result = service.generate_docx(
        package,
        {"processo.numero": "123/2026"},
        output_path,
        profile_id="company-a",
        profile_name="Empresa A",
    )

    assert result.output_path == output_path
    assert result.format == "docx"
    assert store.peek_sequence("documents") == 2
    recent = store.list_recent()
    assert len(recent) == 1
    assert recent[0]["process_number"] == "123/2026"
    assert recent[0]["profile_id"] == "company-a"


def test_failed_pdf_conversion_does_not_consume_sequence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.pdf_converter import PdfConversionError

    store = LocalDataStore(tmp_path / "data")
    planner = OutputPlanner(store)
    service = GenerationService(store, planner)
    package = _package(tmp_path)

    def fake_generation(template_path, destination, values):
        Path(destination).write_bytes(b"generated")

    def fail_conversion(source, destination):
        raise PdfConversionError("conversion failed")

    monkeypatch.setattr(
        "app.services.generation_service.generate_docx",
        fake_generation,
    )
    monkeypatch.setattr(
        "app.services.generation_service.convert_docx_to_pdf",
        fail_conversion,
    )

    with pytest.raises(PdfConversionError):
        service.generate_pdf(package, {}, tmp_path / "result.pdf")

    assert store.peek_sequence("documents") == 1
    assert store.list_recent() == []
