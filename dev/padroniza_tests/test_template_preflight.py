from __future__ import annotations

import pytest
from docx import Document

from app.repositories.templates import TemplatePreflightError, TemplateRepository


def test_repository_rejects_blocking_malformed_template(tmp_path):
    source = tmp_path / "bad.docx"
    doc = Document()
    doc.add_paragraph("Campo {{company.name")
    doc.save(source)
    repository = TemplateRepository(tmp_path / "templates")

    with pytest.raises(TemplatePreflightError):
        repository.create_template(
            name="Modelo inválido",
            source_docx=source,
            fields=[{"id": "company.name", "label": "Nome", "type": "text"}],
        )

    assert repository.list_templates() == []
