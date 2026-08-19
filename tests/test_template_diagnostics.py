from __future__ import annotations

from pathlib import Path

from docx import Document

from app.document.diagnostics import diagnose_template


def _docx(path: Path, text: str) -> Path:
    doc = Document()
    doc.add_paragraph(text)
    doc.save(path)
    return path


def test_diagnostics_provides_structured_issues_and_locations(tmp_path):
    source = _docx(tmp_path / "template.docx", "Nome: {{company.name}}")
    report = diagnose_template(
        {"fields": [], "output": {"filename_pattern": "{{unknown}}.docx"}},
        source,
    )
    codes = {issue["code"] for issue in report["issues"]}
    assert "field.missing_config" in codes
    assert "output.unknown_token" in codes
    missing = next(issue for issue in report["issues"] if issue["code"] == "field.missing_config")
    assert missing["field_id"] == "company.name"
    assert missing["locations"]
    assert report["safe_fix_available"] is True


def test_diagnostics_detects_condition_cycle(tmp_path):
    source = _docx(tmp_path / "template.docx", "{{a}} {{b}}")
    report = diagnose_template(
        {
            "fields": [
                {"id": "a", "label": "A", "type": "text", "visible_when": {"field": "b", "truthy": True}},
                {"id": "b", "label": "B", "type": "text", "visible_when": {"field": "a", "truthy": True}},
            ]
        },
        source,
    )
    assert report["blocking"] is True
    assert any(issue["code"] == "condition.cycle" for issue in report["issues"])
