from __future__ import annotations

import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from docx import Document
from docx.enum.section import WD_SECTION

from app.document.conversion.pdf import convert_docx_to_pdf
from app.document.letterhead import apply_letterhead, default_letterhead_path
from app.repositories.local_data import LocalDataStore
from app.repositories.templates import TemplateRepository
from app.services.generation import GenerationService
from app.services.templates import TemplatePackage


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def _source(path: Path) -> Path:
    document = Document()
    document.add_paragraph("Conteúdo de teste")
    document.save(path)
    return path


def _package(source: Path, *, enabled: bool) -> TemplatePackage:
    return TemplatePackage(
        template_id="modelo",
        name="Modelo",
        description="",
        category="",
        version="1.0",
        source_path=source,
        fields=[],
        output_filename="saida.docx",
        config={
            "output": {"filename_pattern": "saida.docx"},
            "numbering": {"enabled": False},
            "letterhead": {"enabled": enabled, "source": "bundled_default"},
        },
    )


def test_bundled_official_letterhead_is_shipped() -> None:
    path = default_letterhead_path()
    assert path.is_file()
    assert path.name == "Timbrado.docx"


def test_letterhead_replaces_headers_and_footers_for_every_section(tmp_path: Path) -> None:
    target = tmp_path / "multi-section.docx"
    document = Document()
    document.add_paragraph("Página um")
    document.add_section(WD_SECTION.NEW_PAGE)
    document.add_paragraph("Página dois")
    document.save(target)

    apply_letterhead(target)

    with zipfile.ZipFile(target) as archive:
        names = set(archive.namelist())
        assert "word/padronizaLetterheadHeader.xml" in names
        assert "word/padronizaLetterheadFooter.xml" in names
        assert any(name.startswith("word/media/padroniza-letterhead-") for name in names)

        document_root = ET.fromstring(archive.read("word/document.xml"))
        rels_root = ET.fromstring(archive.read("word/_rels/document.xml.rels"))
        relation_targets = {
            child.get("Id"): child.get("Target")
            for child in rels_root.findall(f"{{{REL_NS}}}Relationship")
        }
        sections = list(document_root.iter(f"{{{W_NS}}}sectPr"))
        assert len(sections) == 2
        for section in sections:
            headers = section.findall(f"{{{W_NS}}}headerReference")
            footers = section.findall(f"{{{W_NS}}}footerReference")
            assert {node.get(f"{{{W_NS}}}type") for node in headers} == {"default", "even", "first"}
            assert {node.get(f"{{{W_NS}}}type") for node in footers} == {"default", "even", "first"}
            assert {relation_targets[node.get(f"{{{R_NS}}}id")] for node in headers} == {
                "padronizaLetterheadHeader.xml"
            }
            assert {relation_targets[node.get(f"{{{R_NS}}}id")] for node in footers} == {
                "padronizaLetterheadFooter.xml"
            }

    loaded = Document(target)
    footer_text = "\n".join(paragraph.text for paragraph in loaded.sections[0].footer.paragraphs)
    assert "Secretaria de Estado do Desenvolvimento Humano" in footer_text
    assert "João Pessoa/PB" in footer_text


def test_template_repository_persists_letterhead_choice(tmp_path: Path) -> None:
    repository = TemplateRepository(tmp_path / "templates")
    source = _source(tmp_path / "source.docx")
    template_id = repository.create_template(
        name="Modelo timbrado",
        source_docx=source,
        fields=[],
        letterhead={"enabled": True},
    )
    assert repository.read_config(template_id)["letterhead"] == {
        "enabled": True,
        "source": "bundled_default",
    }

    repository.update_template(
        template_id=template_id,
        name="Modelo timbrado",
        fields=[],
        letterhead={"enabled": False},
    )
    assert repository.read_config(template_id)["letterhead"]["enabled"] is False


def test_generation_service_applies_letterhead_to_docx(tmp_path: Path) -> None:
    source = _source(tmp_path / "source.docx")
    service = GenerationService(LocalDataStore(tmp_path / "data"))
    output = tmp_path / "saida.docx"
    service.generate_docx(_package(source, enabled=True), {}, output)

    with zipfile.ZipFile(output) as archive:
        assert "word/padronizaLetterheadHeader.xml" in archive.namelist()
        assert "word/padronizaLetterheadFooter.xml" in archive.namelist()


def test_pdf_generation_converts_the_letterheaded_docx(tmp_path: Path) -> None:
    source = _source(tmp_path / "source.docx")

    class InspectingConverter:
        def __init__(self) -> None:
            self.saw_letterhead = False

        def available_backend(self) -> str:
            return "fake"

        def last_backend(self) -> str:
            return "fake"

        def docx_to_pdf(self, source_path, destination, **_kwargs):
            with zipfile.ZipFile(source_path) as archive:
                self.saw_letterhead = "word/padronizaLetterheadHeader.xml" in archive.namelist()
            Path(destination).write_bytes(b"%PDF-1.4\n%%EOF")
            return Path(destination)

    converter = InspectingConverter()
    service = GenerationService(LocalDataStore(tmp_path / "data"), converter=converter)
    service.generate_pdf(_package(source, enabled=True), {}, tmp_path / "saida.pdf")
    assert converter.saw_letterhead is True


def test_integrated_pdf_converter_renders_letterhead_graphics_on_each_page(tmp_path: Path) -> None:
    fitz = pytest.importorskip("fitz")
    target = tmp_path / "two-pages.docx"
    document = Document()
    document.add_paragraph("Primeira página")
    document.add_page_break()
    document.add_paragraph("Segunda página")
    document.save(target)
    apply_letterhead(target)

    pdf_path = tmp_path / "two-pages.pdf"
    warnings: list[str] = []
    convert_docx_to_pdf(target, pdf_path, warnings=warnings)
    assert not [warning for warning in warnings if "decoração" in warning.casefold()]

    pdf = fitz.open(pdf_path)
    try:
        assert pdf.page_count == 2
        for page in pdf:
            # Official logo + red right-side artwork are real image XObjects.
            assert len(page.get_images(full=True)) >= 2
            text = page.get_text()
            assert "Secretaria de Estado do Desenvolvimento Humano" in text
            assert "João Pessoa/PB" in text
    finally:
        pdf.close()
