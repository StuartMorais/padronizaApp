from __future__ import annotations

from pathlib import Path

from app.document.conversion.backends import IntegratedBackend
from app.document.conversion.service import DocumentConverter
from app.document.understanding.smart_template import scan_docx_health
from app.domain.validation import sample_value
from app.repositories.local_data import LocalDataStore
from app.services.generation import GenerationService
from app.services.templates import discover_templates


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _values_for(package) -> dict[str, object]:
    values: dict[str, object] = {}
    for field in package.fields:
        field_id = str(field.get("id", "")).strip()
        if field_id:
            values[field_id] = sample_value(field)
    return values


def test_all_bundled_templates_generate_valid_docx_end_to_end(tmp_path):
    packages = discover_templates(PROJECT_ROOT / "templates")
    assert len(packages) >= 4
    service = GenerationService(LocalDataStore(tmp_path / "data"))

    for package in packages:
        output = tmp_path / f"{package.template_id}.docx"
        result = service.generate_docx(package, _values_for(package), output)
        assert result.output_path == output.resolve()
        assert output.stat().st_size > 0
        health = scan_docx_health(output)
        assert health.get("malformed_placeholders", []) == []
        assert health.get("unmatched_open_braces", 0) == 0
        assert health.get("unmatched_close_braces", 0) == 0


def test_bundled_template_generates_real_pdf_with_integrated_fallback(tmp_path):
    package = discover_templates(PROJECT_ROOT / "templates")[0]
    converter = DocumentConverter([IntegratedBackend()])
    service = GenerationService(LocalDataStore(tmp_path / "data-pdf"), converter=converter)
    output = tmp_path / "document.pdf"

    result = service.generate_pdf(package, _values_for(package), output)

    assert output.read_bytes()[:5] == b"%PDF-"
    assert result.format == "pdf"
    assert result.conversion_backend == "Conversor integrado"
    assert result.warnings
