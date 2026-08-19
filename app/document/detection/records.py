from __future__ import annotations

from docx.document import Document as _Document
from docx.oxml.ns import qn
from docx.table import _Cell, Table
from docx.text.paragraph import Paragraph

from app.document.detection.models import ParagraphRecord as _ParagraphRecord

def _collect_paragraph_records(document: _Document) -> list[_ParagraphRecord]:
    records: list[_ParagraphRecord] = []
    seen_cells: set[int] = set()

    def add_paragraph(
        paragraph: Paragraph,
        *,
        story: str,
        table_index: int | None = None,
        row_index: int | None = None,
        cell_index: int | None = None,
        cell: _Cell | None = None,
        table: Table | None = None,
    ) -> None:
        records.append(
            _ParagraphRecord(
                ordinal=len(records),
                paragraph=paragraph,
                story=story,
                table_index=table_index,
                row_index=row_index,
                cell_index=cell_index,
                cell=cell,
                table=table,
            )
        )

    def walk_table(table: Table, *, story: str, index: int) -> None:
        for row_index, row in enumerate(table.rows):
            for cell_index, cell in enumerate(row.cells):
                cell_key = id(cell._tc)
                if cell_key in seen_cells:
                    continue
                seen_cells.add(cell_key)
                for paragraph in cell.paragraphs:
                    add_paragraph(
                        paragraph,
                        story=story,
                        table_index=index,
                        row_index=row_index,
                        cell_index=cell_index,
                        cell=cell,
                        table=table,
                    )
                for nested in cell.tables:
                    nonlocal_table_index[0] += 1
                    walk_table(
                        nested,
                        story=story,
                        index=nonlocal_table_index[0],
                    )

    nonlocal_table_index = [-1]
    body = document.element.body
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            add_paragraph(Paragraph(child, document), story="body")
        elif child.tag == qn("w:tbl"):
            nonlocal_table_index[0] += 1
            walk_table(Table(child, document), story="body", index=nonlocal_table_index[0])

    # Headers and footers are included for ordinary placeholder suggestions,
    # but long choice-block detection remains focused on body tables.
    for section_index, section in enumerate(document.sections):
        for story_name, story in (
            (f"header_{section_index}", section.header),
            (f"footer_{section_index}", section.footer),
        ):
            for paragraph in story.paragraphs:
                add_paragraph(paragraph, story=story_name)
            for table in story.tables:
                nonlocal_table_index[0] += 1
                walk_table(table, story=story_name, index=nonlocal_table_index[0])

    return records
