from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.shared import RGBColor

from app.automatic_field_detector import (
    apply_docx_field_candidates,
    candidate_field_definitions,
    detect_docx_field_candidates,
)
from app.smart_template import smart_fields_from_docx


def _save(document: Document, path: Path) -> Path:
    document.save(str(path))
    return path


def test_detects_inline_placeholders_and_converts_them_to_tags(tmp_path: Path) -> None:
    document = Document()
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Responsável pela demanda: XXXXXXXX"
    table.cell(0, 1).text = "Matrícula: XXXXXXXX"
    table.cell(1, 0).text = "E-mail: xxxxxxxx@xxxxxxxxxxx"
    table.cell(1, 1).text = "Telefone: (83) XXXX-XXXX"
    source = _save(document, tmp_path / "source.docx")

    candidates = detect_docx_field_candidates(source)
    selected = [item for item in candidates if item["source"] == "inline_placeholder"]

    assert len(selected) == 4
    assert {item["type"] for item in selected} >= {"email", "phone", "text"}

    output = tmp_path / "prepared.docx"
    apply_docx_field_candidates(source, output, selected)
    fields = smart_fields_from_docx(output, candidate_field_definitions(selected))

    by_label = {field["label"]: field for field in fields}
    assert by_label["E-mail"]["type"] == "email"
    assert by_label["Telefone"]["type"] == "phone"
    assert len(fields) == 4


def test_detects_red_instruction_as_multiline_field(tmp_path: Path) -> None:
    document = Document()
    table = document.add_table(rows=2, cols=1)
    table.cell(0, 0).text = "2. Descrição da Demanda"
    paragraph = table.cell(1, 0).paragraphs[0]
    run = paragraph.add_run(
        "Informar a descrição sucinta do objeto da compra ou serviço, "
        "incluindo todas as informações necessárias."
    )
    run.font.color.rgb = RGBColor(255, 0, 0)
    source = _save(document, tmp_path / "instruction.docx")

    candidates = detect_docx_field_candidates(source)
    instruction = next(item for item in candidates if item["source"] == "instruction")

    assert instruction["type"] == "multiline"
    assert instruction["selected"] is True
    assert "Descrição" in instruction["label"]


def test_detects_ou_block_as_long_single_choice(tmp_path: Path) -> None:
    document = Document()
    table = document.add_table(rows=2, cols=1)
    table.cell(0, 0).text = "9.1 Justificativa em caso de ausência no PCA"
    cell = table.cell(1, 0)
    cell.text = "Não se aplica"
    for value in (
        "OU",
        "Está dispensada em razão do valor estimado não ser superior ao limite legal.",
        "OU",
        "Justifica-se por demandas supervenientes surgidas após o planejamento.",
        "OU",
        "Será verificado posteriormente pelo setor administrativo.",
    ):
        cell.add_paragraph(value)
    source = _save(document, tmp_path / "choice.docx")

    candidates = detect_docx_field_candidates(source)
    choice = next(item for item in candidates if item["source"] == "long_choice")

    assert choice["type"] == "dropdown"
    assert choice["layout"] == "choice"
    assert len(choice["options"]) == 4
    assert choice["confidence"] >= 0.9

    output = tmp_path / "choice-prepared.docx"
    apply_docx_field_candidates(source, output, [choice])
    fields = smart_fields_from_docx(output, candidate_field_definitions([choice]))

    assert len(fields) == 1
    assert fields[0]["type"] == "dropdown"
    assert fields[0]["layout"] == "choice"
    assert len(fields[0]["options"]) == 4

    generated_template = Document(str(output))
    all_text = "\n".join(
        paragraph.text
        for table in generated_template.tables
        for row in table.rows
        for cell in row.cells
        for paragraph in cell.paragraphs
    )
    assert "{{single_choice:" in all_text
    assert "\nOU\n" not in all_text


def test_existing_tags_are_authoritative_and_not_suggested_again(tmp_path: Path) -> None:
    document = Document()
    document.add_paragraph("Nome: {{responsavel.nome}}")
    document.add_paragraph("Matrícula: XXXXXXXX")
    source = _save(document, tmp_path / "tagged.docx")

    candidates = detect_docx_field_candidates(source)

    assert all(item["field_id"] != "responsavel.nome" for item in candidates)
    assert len(candidates) == 1
    assert candidates[0]["label"] == "Matrícula"


def test_generic_dropdown_prompt_requires_manual_options(tmp_path: Path) -> None:
    document = Document()
    table = document.add_table(rows=2, cols=1)
    table.cell(0, 0).text = "7. Grau de Prioridade"
    table.cell(1, 0).text = "Escolher um item."
    source = _save(document, tmp_path / "dropdown.docx")

    candidates = detect_docx_field_candidates(source)
    prompt = next(item for item in candidates if item["source"] == "dropdown_prompt")

    assert prompt["type"] == "dropdown"
    assert prompt["selected"] is False
    assert prompt["requires_configuration"] is True
    assert prompt.get("options", []) == []


def test_automatic_tag_insertion_preserves_surrounding_run_formatting(tmp_path: Path) -> None:
    document = Document()
    paragraph = document.add_paragraph()
    label_run = paragraph.add_run("Responsável: ")
    label_run.bold = True
    label_run.font.color.rgb = RGBColor(0, 64, 192)
    placeholder_run = paragraph.add_run("XXXXXXXX")
    placeholder_run.italic = True
    placeholder_run.font.color.rgb = RGBColor(255, 0, 0)
    suffix_run = paragraph.add_run(" / conferido")
    suffix_run.underline = True
    source = _save(document, tmp_path / "formatted.docx")

    candidate = next(
        item
        for item in detect_docx_field_candidates(source)
        if item["source"] == "inline_placeholder"
    )
    output = tmp_path / "formatted-prepared.docx"
    apply_docx_field_candidates(source, output, [candidate])

    result = Document(str(output))
    runs = [run for run in result.paragraphs[0].runs if run.text]
    assert runs[0].text == "Responsável: "
    assert runs[0].bold is True
    assert runs[0].font.color.rgb == RGBColor(0, 64, 192)
    assert "{{" in runs[1].text
    assert runs[1].italic is True
    assert runs[1].font.color.rgb == RGBColor(255, 0, 0)
    assert runs[2].text == " / conferido"
    assert runs[2].underline is True
