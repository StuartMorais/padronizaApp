from pathlib import Path

import fitz

from app.document.detection.application import apply_docx_field_candidates
from app.document.detection.candidates import candidate_field_definitions
from app.document.detection.detector import detect_docx_field_candidates
from app.document.understanding.smart_template import smart_fields_from_docx
from app.document.source import prepare_template_source


def _build_vehicle_inspection_pdf(path: Path) -> None:
    pdf = fitz.open()
    page = pdf.new_page(width=595.28, height=841.89)

    def text(x: float, y: float, value: str, *, size: float = 8.0) -> None:
        page.insert_text((x, y), value, fontsize=size)

    def section(y: float, value: str) -> None:
        page.draw_rect(fitz.Rect(42, y - 13, 553, y + 7), color=(0, 0, 0), fill=(0.9, 0.9, 0.9))
        text(47, y, value, size=9)

    section(105, "1. Identificação")
    text(47, 135, "Placa: ABC1D23")
    text(262, 135, "Data: __/__/____")
    text(432, 135, "Horário: __:__")
    text(47, 157, "Motorista:")
    page.draw_line((91, 159), (387, 159), color=(0, 0, 0))
    text(397, 157, "Matrícula:")
    page.draw_line((440, 159), (552, 159), color=(0, 0, 0))
    text(47, 179, "Setor responsável: Coordenação de Transportes")

    section(208, "2. Condições verificadas")
    x_edges = [42, 237, 447, 553]
    y_edges = [235, 257, 279, 301, 323]
    for x in x_edges:
        page.draw_line((x, y_edges[0]), (x, y_edges[-1]), color=(0, 0, 0))
    for y in y_edges:
        page.draw_line((x_edges[0], y), (x_edges[-1], y), color=(0, 0, 0))
    text(130, 250, "Item")
    text(330, 250, "Situação")
    text(485, 250, "Observação")
    rows = ["Pneus e estepe", "Iluminação externa", "Documentos do veículo"]
    for index, label in enumerate(rows):
        top = 257 + (index * 22)
        baseline = top + 16
        text(47, baseline, label)
        for box_x, option_x, option in [
            (245, 259, "Conforme"),
            (314, 328, "Não conforme"),
            (394, 408, "N/A"),
        ]:
            page.draw_rect(fitz.Rect(box_x, top + 8, box_x + 9, top + 17), color=(0, 0, 0))
            text(option_x, baseline, option, size=7)
        page.draw_line((455, top + 13), (545, top + 13), color=(0, 0, 0))

    section(340, "3. Ocorrências / providências")
    text(47, 371, "Descrição da ocorrência:")
    page.draw_line((162, 374), (548, 374), color=(1, 0, 0))
    text(47, 396, "Providência recomendada:")
    page.draw_line((162, 399), (548, 399), color=(0, 0, 0))

    section(422, "4. Conclusão")
    for box_x, label_x, label in [
        (49, 63, "Veículo liberado"),
        (182, 196, "Liberado com ressalvas"),
        (362, 376, "Não liberado"),
    ]:
        page.draw_rect(fitz.Rect(box_x, 447, box_x + 9, 456), color=(0, 0, 0))
        text(label_x, 455, label, size=7)
    text(47, 476, "Próxima revisão: __/__/____")
    text(287, 476, "Responsável:")
    page.draw_line((344, 477), (547, 477), color=(0, 0, 0))
    text(47, 508, "Texto fixo: este registro não substitui as inspeções preventivas.", size=7)

    pdf.save(path)
    pdf.close()


def test_pdf_reconstruction_preserves_logical_form_sections(tmp_path: Path) -> None:
    source = tmp_path / "vehicle.pdf"
    _build_vehicle_inspection_pdf(source)

    prepared = prepare_template_source(source, tmp_path / "work")
    candidates = detect_docx_field_candidates(prepared.docx_path)
    by_label = {item.get("label"): item for item in candidates}

    for label in (
        "Placa",
        "Data",
        "Horário",
        "Motorista",
        "Matrícula",
        "Setor responsável",
        "Descrição da ocorrência",
        "Providência recomendada",
        "Próxima revisão",
        "Responsável",
    ):
        assert label in by_label

    matrix_groups = [
        item
        for item in candidates
        if item.get("source") == "checkbox_choice"
        and item.get("label") in {
            "Pneus e estepe",
            "Iluminação externa",
            "Documentos do veículo",
        }
    ]
    assert len(matrix_groups) == 3
    assert all([field["label"] for field in group["fields"]] == ["Conforme", "Não conforme", "N/A"] for group in matrix_groups)

    conclusion = next(
        item
        for item in candidates
        if item.get("source") == "checkbox_choice" and item.get("label") == "Conclusão"
    )
    assert [field["label"] for field in conclusion["fields"]] == [
        "Veículo liberado",
        "Liberado com ressalvas",
        "Não liberado",
    ]

    accepted = [item for item in candidates if item.get("selected")]
    output = tmp_path / "prepared.docx"
    apply_docx_field_candidates(prepared.docx_path, output, accepted)
    fields = smart_fields_from_docx(output, candidate_field_definitions(accepted))
    fields_by_label = {field.get("label"): field for field in fields}

    assert fields_by_label["Placa"]["layout_row"] == fields_by_label["Data"]["layout_row"]
    assert fields_by_label["Data"]["layout_row"] == fields_by_label["Horário"]["layout_row"]
    assert fields_by_label["Motorista"]["layout_row"] == fields_by_label["Matrícula"]["layout_row"]
    assert fields_by_label["Pneus e estepe — Observação"]["type"] == "text"
    assert fields_by_label["Descrição da ocorrência"]["type"] == "multiline"
    assert fields_by_label["Providência recomendada"]["type"] == "multiline"
    assert fields_by_label["Próxima revisão"]["layout_row"] == fields_by_label["Responsável"]["layout_row"]
