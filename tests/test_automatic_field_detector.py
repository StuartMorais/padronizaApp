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




def test_detected_date_mask_stays_editable(tmp_path: Path) -> None:
    document = Document()
    table = document.add_table(rows=1, cols=3)
    table.cell(0, 0).text = "Unidade visitada: XXXXXXXXXXXX"
    table.cell(0, 1).text = "Data: __/__/____"
    table.cell(0, 2).text = "Horário: __:__"
    source = _save(document, tmp_path / "editable-date.docx")

    candidates = detect_docx_field_candidates(source)
    date_candidate = next(item for item in candidates if item["label"] == "Data")
    assert date_candidate["type"] == "date"

    definitions = candidate_field_definitions([date_candidate])
    assert len(definitions) == 1
    assert definitions[0]["type"] == "date"
    assert definitions[0]["automatic"] is False

    output = tmp_path / "editable-date-prepared.docx"
    apply_docx_field_candidates(source, output, [date_candidate])
    fields = smart_fields_from_docx(output, definitions)
    date_field = next(field for field in fields if field["id"] == date_candidate["field_id"])
    assert date_field["automatic"] is False

def test_detects_full_masks_sample_email_phone_and_inline_dropdown(tmp_path: Path) -> None:
    document = Document()
    table = document.add_table(rows=4, cols=2)
    table.cell(0, 0).text = "CNPJ: __.___.___/____-__"
    table.cell(0, 1).text = "CPF: ___.___.___-__"
    table.cell(1, 0).text = "E-mail principal: contato@empresa.com.br"
    table.cell(1, 1).text = "Telefone: (00) 00000-0000"
    table.cell(2, 0).text = "UF: __"
    table.cell(2, 1).text = "CEP: __.___-___"
    table.cell(3, 0).text = "Tipo de fornecedor: Escolher uma opção"
    table.cell(3, 1).text = "País: Brasil"
    source = _save(document, tmp_path / "masks.docx")

    candidates = detect_docx_field_candidates(source)
    by_label = {item["label"]: item for item in candidates}

    assert by_label["CNPJ"]["preview"] == "__.___.___/____-__"
    assert by_label["CNPJ"]["type"] == "cnpj"
    assert by_label["CPF"]["preview"] == "___.___.___-__"
    assert by_label["CPF"]["type"] == "cpf"
    assert by_label["E-mail principal"]["type"] == "email"
    assert by_label["E-mail principal"]["preview"] == "contato@empresa.com.br"
    assert by_label["Telefone"]["type"] == "phone"
    assert by_label["Telefone"]["preview"] == "(00) 00000-0000"
    assert by_label["UF"]["preview"] == "__"
    assert by_label["CEP"]["type"] == "cep"
    assert by_label["Tipo de fornecedor"]["source"] == "dropdown_prompt"
    assert by_label["Tipo de fornecedor"]["requires_configuration"] is True
    assert by_label["País"]["source"] == "sample_value"
    assert by_label["País"]["preview"] == "Brasil"
    assert by_label["País"]["placeholder"] == "Brasil"
    assert by_label["País"]["selected"] is True

    accepted = [
        item
        for item in candidates
        if item["label"] != "Tipo de fornecedor"
    ]
    output = tmp_path / "masks-prepared.docx"
    apply_docx_field_candidates(source, output, accepted)
    text = "\n".join(
        cell.text
        for table in Document(str(output)).tables
        for row in table.rows
        for cell in row.cells
    )
    assert "CNPJ: {{" in text
    assert "__.___.___/____-__" not in text
    assert "contato@empresa.com.br" not in text
    assert "(00) 00000-0000" not in text
    assert "País: {{" in text
    assert "País: Brasil" not in text

    fields = smart_fields_from_docx(output, candidate_field_definitions(accepted))
    country = next(field for field in fields if field["label"] == "País")
    assert country["placeholder"] == "Brasil"


def test_detects_inline_and_vertical_checkbox_groups_with_correct_semantics(tmp_path: Path) -> None:
    document = Document()
    table = document.add_table(rows=1, cols=1)
    table.cell(0, 0).text = (
        "Natureza do atendimento: ☐ Material   ☐ Serviço   ☐ Material e serviço"
    )

    declarations = document.add_table(rows=3, cols=1)
    declarations.cell(0, 0).text = "☐ Declaro que as informações são verdadeiras."
    declarations.cell(1, 0).text = "☐ Autorizo o uso administrativo dos dados."
    paragraph = declarations.cell(2, 0).paragraphs[0]
    paragraph.add_run("Observação do cadastro: ").bold = True
    instruction = paragraph.add_run("Preencher somente se houver informação complementar.")
    instruction.font.color.rgb = RGBColor(255, 0, 0)
    source = _save(document, tmp_path / "checkboxes.docx")

    candidates = detect_docx_field_candidates(source)
    checkbox_groups = [item for item in candidates if item["source"] == "checkbox_choice"]
    assert len(checkbox_groups) == 2

    nature = next(item for item in checkbox_groups if item["label"] == "Natureza do atendimento")
    assert nature["selection"] == "single"
    assert nature["location"]["kind"] == "checkbox_group_inline"
    assert [field["label"] for field in nature["fields"]] == [
        "Material",
        "Serviço",
        "Material e serviço",
    ]
    assert all(field.get("layout") == "choice" for field in nature["fields"])

    declaration = next(item for item in checkbox_groups if item["selection"] == "multiple")
    assert declaration["location"]["kind"] == "checkbox_group"
    assert len(declaration["fields"]) == 2
    assert all(field.get("selection") == "multiple" for field in declaration["fields"])
    assert all(not field.get("choice_required", False) for field in declaration["fields"])

    observation = next(item for item in candidates if item["label"] == "Observação do cadastro")
    assert observation["type"] == "multiline"
    assert observation["source"] == "instruction"

    accepted = [nature, declaration, observation]
    output = tmp_path / "checkboxes-prepared.docx"
    apply_docx_field_candidates(source, output, accepted)
    fields = smart_fields_from_docx(output, candidate_field_definitions(accepted))
    by_id = {field["id"]: field for field in fields}
    assert len([field for field in fields if field.get("selection") == "single"]) == 3
    assert len([field for field in fields if field.get("selection") == "multiple"]) == 2
    assert by_id[observation["field_id"]]["type"] == "multiline"


def test_detects_bare_label_field_without_duplicating_adjacent_empty_cell(tmp_path: Path) -> None:
    document = Document()
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Responsável legal:"
    table.cell(0, 1).text = "CPF: ___.___.___-__"
    table.cell(1, 0).text = "Endereço completo:"
    table.cell(1, 1).text = ""
    source = _save(document, tmp_path / "bare-label.docx")

    candidates = detect_docx_field_candidates(source)
    labels = [item["label"] for item in candidates]
    assert labels.count("Responsável legal") == 1
    assert labels.count("Endereço completo") == 1

    responsible = next(item for item in candidates if item["label"] == "Responsável legal")
    address = next(item for item in candidates if item["label"] == "Endereço completo")
    assert responsible["location"]["kind"] == "append_tag"
    assert address["location"]["kind"] == "empty_cell"
    assert address["selected"] is True
    assert address["confidence"] >= 0.80

    output = tmp_path / "bare-label-prepared.docx"
    apply_docx_field_candidates(source, output, [responsible, address])
    result = Document(str(output))
    assert "Responsável legal: {{" in result.tables[0].cell(0, 0).text
    assert result.tables[0].cell(1, 0).text == "Endereço completo:"
    assert "{{" in result.tables[0].cell(1, 1).text


def test_table_context_uses_row_and_column_labels_for_unlabeled_fill_area(tmp_path: Path) -> None:
    document = Document()
    table = document.add_table(rows=2, cols=3)
    table.cell(0, 0).text = "Item verificado"
    table.cell(0, 1).text = "Situação"
    table.cell(0, 2).text = "Observação curta"
    table.cell(1, 0).text = "Documentação disponível"
    table.cell(1, 1).text = "☐ Conforme   ☐ Não conforme   ☐ Não se aplica"
    table.cell(1, 2).text = "________________"
    source = _save(document, tmp_path / "questionnaire.docx")

    candidates = detect_docx_field_candidates(source)
    observation = next(
        item
        for item in candidates
        if item.get("source") == "inline_placeholder"
        and "Observação curta" in item.get("label", "")
    )

    assert observation["label"] == "Documentação disponível — Observação curta"
    assert observation["field_id"] == "auto.documentacao_disponivel_observacao_curta"
    assert observation["selected"] is True
    assert not observation["field_id"].startswith("auto.campo_")


def test_instruction_uses_label_from_previous_paragraph_in_same_cell(tmp_path: Path) -> None:
    document = Document()
    table = document.add_table(rows=2, cols=1)
    table.cell(0, 0).text = "Descrição das constatações:"
    instruction_one = table.cell(0, 0).add_paragraph(
        "Descrever os fatos observados e as evidências encontradas."
    )
    instruction_one.runs[0].font.color.rgb = RGBColor(255, 0, 0)
    table.cell(1, 0).text = "Providência recomendada:"
    instruction_two = table.cell(1, 0).add_paragraph(
        "Informar a ação necessária para regularização."
    )
    instruction_two.runs[0].font.color.rgb = RGBColor(255, 0, 0)
    source = _save(document, tmp_path / "same-cell-label.docx")

    candidates = detect_docx_field_candidates(source)
    labels = [item["label"] for item in candidates if item.get("source") == "instruction"]

    assert "Descrição das constatações" in labels
    assert "Providência recomendada" in labels
    assert not any("Descrição das constatações: Descrever" in label for label in labels)


def test_detects_numbered_occurrence_table_as_repeatable_and_suppresses_anonymous_fields(tmp_path: Path) -> None:
    document = Document()
    title = document.add_table(rows=1, cols=1)
    title.cell(0, 0).text = "4. Ocorrências / pendências"

    table = document.add_table(rows=4, cols=4)
    for index, header in enumerate(("Nº", "Descrição", "Prazo", "Responsável")):
        table.cell(0, index).text = header
    table.cell(1, 0).text = "01"
    table.cell(1, 1).text = "________________________________"
    table.cell(1, 2).text = "__/__/____"
    table.cell(1, 3).text = "____________"
    table.cell(2, 0).text = "02"
    table.cell(3, 0).text = "03"
    source = _save(document, tmp_path / "occurrences.docx")

    candidates = detect_docx_field_candidates(source)
    repeatable = next(item for item in candidates if item.get("source") == "repeatable_table")

    assert repeatable["type"] == "repeatable_table"
    assert repeatable["field_id"] == "auto.ocorrencias_pendencias"
    assert repeatable["section"] == "4. Ocorrências / pendências"
    assert repeatable["selected"] is True
    assert [(column["id"], column["type"]) for column in repeatable["columns"]] == [
        ("item", "auto_number"),
        ("descricao", "multiline"),
        ("prazo", "date"),
        ("responsavel", "text"),
    ]
    assert not any(item["field_id"].startswith("auto.campo_") for item in candidates)

    output = tmp_path / "occurrences-prepared.docx"
    apply_docx_field_candidates(source, output, [repeatable])
    prepared = Document(str(output))
    prepared_table = prepared.tables[1]
    assert len(prepared_table.rows) == 2
    assert "{{repeat:auto.ocorrencias_pendencias}}" in prepared_table.cell(1, 0).text
    assert "{{row.number}}" in prepared_table.cell(1, 0).text
    assert "{{auto.ocorrencias_pendencias.descricao}}" in prepared_table.cell(1, 1).text
    assert "{{date:auto.ocorrencias_pendencias.prazo}}" in prepared_table.cell(1, 2).text
    assert "{{auto.ocorrencias_pendencias.responsavel}}" in prepared_table.cell(1, 3).text

    fields = smart_fields_from_docx(output, candidate_field_definitions([repeatable]))
    field = next(item for item in fields if item["id"] == "auto.ocorrencias_pendencias")
    assert field["type"] == "repeatable_table"
    assert field["section"] == "4. Ocorrências / pendências"
    assert [column["id"] for column in field["columns"]] == [
        "item",
        "descricao",
        "prazo",
        "responsavel",
    ]


def test_questionnaire_choices_stay_embedded_with_observation_column(tmp_path: Path) -> None:
    document = Document()
    title = document.add_table(rows=1, cols=1)
    title.cell(0, 0).text = "2. Condições verificadas"

    table = document.add_table(rows=3, cols=3)
    table.cell(0, 0).text = "Item verificado"
    table.cell(0, 1).text = "Situação"
    table.cell(0, 2).text = "Observação curta"
    table.cell(1, 0).text = "Documentação disponível"
    table.cell(1, 1).text = "☐ Conforme   ☐ Não conforme   ☐ Não se aplica"
    table.cell(1, 2).text = "________________"
    table.cell(2, 0).text = "Condições de segurança"
    table.cell(2, 1).text = "☐ Conforme   ☐ Não conforme   ☐ Não se aplica"
    table.cell(2, 2).text = "________________"
    source = _save(document, tmp_path / "questionnaire-layout.docx")

    candidates = detect_docx_field_candidates(source)
    accepted = [
        item
        for item in candidates
        if item.get("selected", True) and not item.get("requires_configuration", False)
    ]
    output = tmp_path / "questionnaire-layout-prepared.docx"
    apply_docx_field_candidates(source, output, accepted)
    fields = smart_fields_from_docx(output, candidate_field_definitions(accepted))
    by_id = {field["id"]: field for field in fields}

    choice = by_id["auto.documentacao_disponivel.conforme"]
    observation = by_id["auto.documentacao_disponivel_observacao_curta"]

    assert choice["layout"] == "table"
    assert observation["layout"] == "table"
    assert choice["layout_group"] == observation["layout_group"]
    assert choice["layout_row"] == observation["layout_row"] == "row_1"
    assert choice["layout_column"] == "Situação"
    assert observation["layout_column"] == "Observação curta"
    assert choice["layout_row_header_label"] == "Item verificado"
    assert choice["group"].startswith("auto_checkbox_")
    assert choice["selection"] == "single"
    assert choice["compact_choice"] is True
    assert observation["type"] == "text"


def test_inline_yes_no_question_keeps_group_prompt_inside_form_grid(tmp_path: Path) -> None:
    document = Document()
    table = document.add_table(rows=4, cols=1)
    table.cell(0, 0).text = "3. Fundamentação complementar"
    table.cell(1, 0).text = "Justificativa complementar: Preencher quando necessário."
    table.cell(2, 0).text = "Grau de risco: Escolher um item"
    table.cell(3, 0).text = "Há impedimento conhecido? ☐ Sim   ☐ Não"
    source = _save(document, tmp_path / "inline-question.docx")

    candidates = detect_docx_field_candidates(source)
    choice = next(item for item in candidates if item["label"] == "Há impedimento conhecido?")
    assert choice["selection"] == "single"

    output = tmp_path / "inline-question-prepared.docx"
    apply_docx_field_candidates(source, output, [choice])
    fields = smart_fields_from_docx(output, candidate_field_definitions([choice]))

    assert len(fields) == 2
    assert {field["label"] for field in fields} == {"Sim", "Não"}
    assert all(field["layout"] == "form_grid" for field in fields)
    assert all(field["layout_row"] == "row_3" for field in fields)
    assert all(field["choice_group_label"] == "Há impedimento conhecido?" for field in fields)
    assert len({field["group"] for field in fields}) == 1


def test_detects_checkbox_alternatives_split_across_table_cells(tmp_path: Path) -> None:
    document = Document()
    title = document.add_table(rows=1, cols=1)
    title.cell(0, 0).text = "4. Forma de entrega"

    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = (
        "☐ Entrega imediata e integral do material ou serviço\n\n"
        "* Considera-se imediata a entrega em até 30 dias."
    )
    table.cell(0, 1).text = (
        "☐ Entrega parcelada do material ou serviço\n\n"
        "Informar cronograma quando aplicável."
    )
    source = _save(document, tmp_path / "delivery-choice.docx")

    candidates = detect_docx_field_candidates(source)
    choice = next(
        item
        for item in candidates
        if item.get("source") == "checkbox_choice"
        and item.get("label") == "Forma de entrega"
    )

    assert choice["selection"] == "single"
    assert choice["location"]["kind"] == "checkbox_group_multi_cell"
    assert len(choice["fields"]) == 2
    labels = [field["label"] for field in choice["fields"]]
    assert labels[0].startswith("Entrega imediata e integral")
    assert "30 dias" in labels[0]
    assert labels[1].startswith("Entrega parcelada")
    assert "cronograma" in labels[1].casefold()

    output = tmp_path / "delivery-choice-prepared.docx"
    apply_docx_field_candidates(source, output, [choice])
    prepared = Document(str(output))
    left = prepared.tables[1].cell(0, 0).text
    right = prepared.tables[1].cell(0, 1).text
    assert "{{checkbox:" in left
    assert "{{checkbox:" in right
    assert "Considera-se imediata a entrega em até 30 dias." in left
    assert "Informar cronograma quando aplicável." in right

    fields = smart_fields_from_docx(output, candidate_field_definitions([choice]))
    assert len(fields) == 2
    assert all(field.get("selection") == "single" for field in fields)
    assert all(field.get("layout") == "choice" for field in fields)
    assert all(field.get("layout_group_label") == "Forma de entrega" for field in fields)
