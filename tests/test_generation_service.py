from __future__ import annotations

from pathlib import Path
import zipfile

import pytest
from docx import Document

from app.document.docx.generator import DocumentGenerationError
from app.document.conversion.pdf import PdfConversionError
from app.repositories.local_data import LocalDataStore
from app.services.output_planner import OutputPlanner
from app.services.generation import GenerationService
from app.services.templates import TemplatePackage


def _package(tmp_path: Path) -> TemplatePackage:
    source = tmp_path / "source.docx"
    Document().save(source)
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



def _write_minimal_docx(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<document/>")


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
        "app.services.generation.generate_docx",
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
        _write_minimal_docx(Path(destination))

    monkeypatch.setattr(
        "app.services.generation.generate_docx",
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
    store = LocalDataStore(tmp_path / "data")
    planner = OutputPlanner(store)
    service = GenerationService(store, planner)
    package = _package(tmp_path)

    def fake_generation(template_path, destination, values):
        _write_minimal_docx(Path(destination))

    def fail_conversion(source, destination, **_kwargs):
        raise PdfConversionError("conversion failed")

    monkeypatch.setattr(
        "app.services.generation.generate_docx",
        fake_generation,
    )
    monkeypatch.setattr(
        service.converter,
        "docx_to_pdf",
        fail_conversion,
    )

    with pytest.raises(PdfConversionError):
        service.generate_pdf(package, {}, tmp_path / "result.pdf")

    assert store.peek_sequence("documents") == 1
    assert store.list_recent() == []


def test_docx_generation_does_not_replace_existing_file_when_staging_fails(tmp_path, monkeypatch):
    from app.services import generation as generation_module

    package = _package(tmp_path)
    output = tmp_path / "existing.docx"
    output.write_bytes(b"ORIGINAL")
    store = LocalDataStore(tmp_path / "data-transaction")
    service = GenerationService(store)

    def fail_generate(*_args, **_kwargs):
        raise DocumentGenerationError("boom")

    monkeypatch.setattr(generation_module, "generate_docx", fail_generate)
    with pytest.raises(DocumentGenerationError):
        service.generate_docx(package, {"company.name": "X"}, output)

    assert output.read_bytes() == b"ORIGINAL"


def test_pdf_generation_does_not_replace_existing_file_when_conversion_fails(tmp_path, monkeypatch):
    from app.services import generation as generation_module

    package = _package(tmp_path)
    output = tmp_path / "existing.pdf"
    output.write_bytes(b"%PDF-ORIGINAL")
    store = LocalDataStore(tmp_path / "data-pdf-transaction")

    class FailingConverter:
        def available_backend(self):
            return "fake"
        def docx_to_pdf(self, *_args, **_kwargs):
            raise PdfConversionError("boom")

    service = GenerationService(store, converter=FailingConverter())
    monkeypatch.setattr(
        generation_module,
        "generate_docx",
        lambda _source, destination, _values: _write_minimal_docx(Path(destination)),
    )
    with pytest.raises(PdfConversionError):
        service.generate_pdf(package, {"company.name": "X"}, output)

    assert output.read_bytes() == b"%PDF-ORIGINAL"
