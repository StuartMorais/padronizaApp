from pathlib import Path

import fitz
from docx import Document

from app.template_source import (
    TemplateSourceError,
    prepare_template_source,
)


def test_docx_source_is_used_directly(tmp_path: Path) -> None:
    source = tmp_path / 'modelo.docx'
    Document().save(source)

    prepared = prepare_template_source(source, tmp_path / 'work')

    assert prepared.original_path == source.resolve()
    assert prepared.docx_path == source.resolve()
    assert prepared.converted_from_pdf is False
    assert prepared.warnings == ()


def test_pdf_source_is_reconstructed_to_docx(tmp_path: Path) -> None:
    source = tmp_path / 'modelo.pdf'
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 90), 'Nome: ____________________')
    page.insert_text((72, 120), 'Data: __/__/____')
    pdf.save(source)
    pdf.close()

    prepared = prepare_template_source(source, tmp_path / 'work')

    assert prepared.original_path == source.resolve()
    assert prepared.converted_from_pdf is True
    assert prepared.docx_path.suffix == '.docx'
    assert prepared.docx_path.exists()
    assert prepared.docx_path.stat().st_size > 0


def test_template_source_rejects_other_extensions(tmp_path: Path) -> None:
    source = tmp_path / 'modelo.txt'
    source.write_text('x', encoding='utf-8')

    try:
        prepare_template_source(source, tmp_path / 'work')
    except TemplateSourceError as exc:
        assert 'DOCX ou PDF' in str(exc)
    else:
        raise AssertionError('expected TemplateSourceError')



def test_pdf_acroForm_fields_become_regular_template_tags(tmp_path: Path) -> None:
    from reportlab.pdfgen import canvas
    from app.smart_template import smart_fields_from_docx

    source = tmp_path / 'formulario.pdf'
    pdf = canvas.Canvas(str(source))
    pdf.drawString(72, 760, 'Nome:')
    pdf.acroForm.textfield(name='pessoa_nome', x=115, y=748, width=180, height=20)
    pdf.drawString(72, 720, 'Tipo:')
    pdf.acroForm.choice(
        name='tipo',
        value='Selecione...',
        options=['Selecione...', 'Interno', 'Externo'],
        x=115,
        y=708,
        width=140,
        height=20,
    )
    pdf.save()

    prepared = prepare_template_source(source, tmp_path / 'work')
    fields = smart_fields_from_docx(prepared.docx_path, [])
    by_id = {field['id']: field for field in fields}

    assert prepared.native_pdf_fields == 2
    assert 'pessoa_nome' in by_id
    assert by_id['tipo']['type'] == 'dropdown'
    assert by_id['tipo']['options'] == ['Interno', 'Externo']


def test_reconstructed_pdf_candidates_can_be_applied_when_lines_share_one_paragraph(tmp_path: Path) -> None:
    from app.automatic_field_detector import apply_docx_field_candidates, detect_docx_field_candidates

    source = tmp_path / 'inspecao.pdf'
    pdf = fitz.open()
    page = pdf.new_page()
    # Closely stacked lines encourage the PDF->DOCX converter to reconstruct
    # them as a single paragraph with manual line breaks, matching real forms.
    page.insert_text((72, 90), 'Placa: ABC1D23')
    page.insert_text((72, 101), 'Data: __/__/____')
    page.insert_text((72, 112), 'Horário: __:__')
    pdf.save(source)
    pdf.close()

    prepared = prepare_template_source(source, tmp_path / 'work')
    candidates = detect_docx_field_candidates(prepared.docx_path)
    selected = [item for item in candidates if item.get('source') == 'inline_placeholder']

    assert any(item.get('label') == 'Data' for item in selected)
    assert any(item.get('label') == 'Horário' for item in selected)

    output = tmp_path / 'prepared-fields.docx'
    apply_docx_field_candidates(prepared.docx_path, output, selected)
    assert output.exists()


def test_native_pdf_fields_keep_visible_labels_and_editable_dates(tmp_path: Path) -> None:
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    from app.smart_template import smart_fields_from_docx

    source = tmp_path / 'auditorio.pdf'
    pdf = canvas.Canvas(str(source), pagesize=A4)
    form = pdf.acroForm

    # Section 2-like row: internal PDF names deliberately differ from the
    # labels printed for humans on the page.
    pdf.drawString(52, 620, 'Nome do evento:')
    form.textfield(name='evento_nome', x=137, y=608, width=405, height=17)
    pdf.drawString(52, 590, 'Data:')
    form.textfield(name='evento_data', x=87, y=578, width=90, height=17)
    pdf.drawString(202, 590, 'Horário inicial:')
    form.textfield(name='evento_hora_inicio', x=282, y=578, width=65, height=17)
    pdf.drawString(372, 590, 'Horário final:')
    form.textfield(name='evento_hora_fim', x=442, y=578, width=100, height=17)

    # Section 5-like controls.
    form.checkbox(name='aceite_termo', x=52, y=520, size=12)
    pdf.drawString(72, 523, 'Li e concordo com o termo acima.')
    pdf.drawString(52, 490, 'Responsável pela autorização:')
    form.textfield(name='autorizador_nome', x=197, y=478, width=220, height=17)
    pdf.drawString(432, 490, 'Data:')
    form.textfield(name='autorizacao_data', x=462, y=478, width=80, height=17)
    pdf.save()

    prepared = prepare_template_source(source, tmp_path / 'work')
    hints = {item['id']: item for item in prepared.native_pdf_field_hints}

    assert hints['evento_nome']['label'] == 'Nome do evento'
    assert hints['evento_nome']['layout'] == 'full_width'
    assert hints['evento_data']['label'] == 'Data'
    assert hints['evento_data']['type'] == 'date'
    assert hints['evento_data']['automatic'] is False
    assert hints['evento_hora_inicio']['label'] == 'Horário inicial'
    assert hints['evento_hora_fim']['label'] == 'Horário final'
    assert hints['aceite_termo']['label'] == 'Li e concordo com o termo acima.'
    assert hints['autorizador_nome']['label'] == 'Responsável pela autorização'
    assert hints['autorizacao_data']['label'] == 'Data'
    assert hints['autorizacao_data']['automatic'] is False

    # Seeding smart scanning with source hints mirrors the template editor's
    # behavior and guarantees that native dates remain user-editable.
    fields = smart_fields_from_docx(prepared.docx_path, list(prepared.native_pdf_field_hints))
    by_id = {field['id']: field for field in fields}
    assert by_id['evento_data']['automatic'] is False
    assert by_id['autorizacao_data']['automatic'] is False
    assert by_id['aceite_termo']['label'] == 'Li e concordo com o termo acima.'
    assert by_id['autorizador_nome']['label'] == 'Responsável pela autorização'
