from __future__ import annotations

import html
from pathlib import Path
from typing import Any


def export_checklist_pdf(template: dict[str, Any], output_path: str | Path) -> Path:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ImportError as error:
        raise RuntimeError("Instale reportlab para exportar PDF.") from error

    path = Path(output_path)

    if path.suffix.lower() != ".pdf":
        path = path.with_suffix(".pdf")

    path.parent.mkdir(parents=True, exist_ok=True)

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "ChecklistTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=15,
        alignment=1,
        spaceAfter=4,
    )

    subtitle_style = ParagraphStyle(
        "ChecklistSubtitle",
        parent=styles["Normal"],
        fontSize=9,
        leading=11,
        textColor=colors.HexColor("#374151"),
        spaceAfter=4,
    )

    section_style = ParagraphStyle(
        "ChecklistSection",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=12,
        textColor=colors.HexColor("#111827"),
        backColor=colors.HexColor("#E5E7EB"),
        borderColor=colors.HexColor("#9CA3AF"),
        borderWidth=0.5,
        borderPadding=5,
        spaceBefore=9,
        spaceAfter=0,
    )

    cell_style = ParagraphStyle(
        "ChecklistCell",
        parent=styles["Normal"],
        fontSize=7.4,
        leading=9,
    )

    small_style = ParagraphStyle(
        "ChecklistSmall",
        parent=styles["Normal"],
        fontSize=7,
        leading=8.5,
        textColor=colors.HexColor("#374151"),
    )

    document = SimpleDocTemplate(
        str(path),
        pagesize=landscape(A4),
        rightMargin=10 * mm,
        leftMargin=10 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
    )

    story: list[Any] = []

    sections = template.get("sections") if isinstance(template.get("sections"), list) else []
    total_items = sum(
        len(section.get("items", []))
        for section in sections
        if isinstance(section, dict)
    )

    story.append(Paragraph("FOLHA DE VERIFICAÇÃO DE DOCUMENTOS", title_style))
    story.append(Paragraph(escape_pdf_text(template.get("title") or "Checklist"), subtitle_style))
    story.append(Paragraph(escape_pdf_text(template.get("subtitle") or "Sem subtítulo"), subtitle_style))
    story.append(Paragraph(f"<b>Base legal:</b> {escape_pdf_text(template.get('baseLegal') or 'Não informada')}", small_style))
    story.append(Paragraph(f"<b>Conteúdo:</b> {len(sections)} seção(ões), {total_items} item(ns)", small_style))

    description = str(template.get("description") or "").strip()

    if description:
        story.append(Paragraph(f"<b>Descrição:</b> {escape_pdf_text(description)}", small_style))

    story.append(Spacer(1, 5 * mm))

    if not sections:
        story.append(Paragraph("Nenhuma seção cadastrada.", cell_style))
    else:
        for section in sections:
            if not isinstance(section, dict):
                continue

            section_title = f"{section.get('number', '')}. {section.get('title', '')}".strip()
            story.append(Paragraph(escape_pdf_text(section_title), section_style))

            items = section.get("items") if isinstance(section.get("items"), list) else []

            if not items:
                story.append(Paragraph("Nenhum item cadastrado nesta seção.", cell_style))
                continue

            table_data = [
                [
                    p("Item", cell_style),
                    p("Documento / Informações constantes do processo", cell_style),
                    p("Normativo", cell_style),
                    p("S / N / NA", cell_style),
                    p("Folha", cell_style),
                    p("Observação", cell_style),
                    p("Painel inferior", cell_style),
                ]
            ]

            for item in items:
                if not isinstance(item, dict):
                    continue

                table_data.append(
                    [
                        p(item.get("number"), cell_style),
                        p(item.get("documento"), cell_style),
                        p(item.get("normativo"), cell_style),
                        p(item.get("situacao") or "N/A", cell_style),
                        p(item.get("folha"), cell_style),
                        p(item.get("observacao"), cell_style),
                        rich_p(build_panel_text(item), cell_style),
                    ]
                )

            table = Table(
                table_data,
                repeatRows=1,
                colWidths=[
                    14 * mm,
                    78 * mm,
                    49 * mm,
                    22 * mm,
                    20 * mm,
                    40 * mm,
                    54 * mm,
                ],
            )

            table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#D9DDE3")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#111827")),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#9CA3AF")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 3),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                        ("TOPPADDING", (0, 0), (-1, -1), 3),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ]
                )
            )

            story.append(table)
            story.append(Spacer(1, 3 * mm))

    document.build(story)

    return path


def build_panel_text(item: dict[str, Any]) -> str:
    parts: list[str] = []

    description = str(item.get("description") or "").strip()

    if description:
        parts.append(f"<b>Descrição:</b><br/>{escape_pdf_text(description)}")

    required_documents = normalize_text_list(item.get("requiredDocuments"))

    if required_documents:
        parts.append(
            "<b>Documentos mínimos:</b><br/>"
            + "<br/>".join(f"• {escape_pdf_text(value)}" for value in required_documents)
        )

    notes = normalize_text_list(item.get("notes"))

    if notes:
        parts.append(
            "<b>Observações:</b><br/>"
            + "<br/>".join(f"• {escape_pdf_text(value)}" for value in notes)
        )

    if not parts:
        return "Nenhuma informação cadastrada."

    return "<br/><br/>".join(parts)


def normalize_text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []

    return [str(item).strip() for item in value if str(item).strip()]


def p(value: Any, style: Any) -> Any:
    try:
        from reportlab.platypus import Paragraph
    except ImportError as error:
        raise RuntimeError("Instale reportlab para exportar PDF.") from error

    return Paragraph(escape_pdf_text(value), style)


def rich_p(value: Any, style: Any) -> Any:
    try:
        from reportlab.platypus import Paragraph
    except ImportError as error:
        raise RuntimeError("Instale reportlab para exportar PDF.") from error

    return Paragraph(str(value or ""), style)


def escape_pdf_text(value: Any) -> str:
    return html.escape(str(value or "")).replace("\n", "<br/>")
