from __future__ import annotations

import re
from enum import Enum
from typing import Any

from app.document.detection.models import ParagraphRecord
from app.document.detection.structure import DocumentStructure, StoryZone, is_numbered_section_heading


class ContentRole(str, Enum):
    BLANK = "blank"
    HEADING = "heading"
    INSTRUCTION = "instruction"
    NOTE = "note"
    FIELD_PROMPT = "field_prompt"
    FILL_AREA = "fill_area"
    EXAMPLE = "example"
    FIXED_TEXT = "fixed_text"
    SIGNATURE = "signature"
    HEADER_FOOTER = "header_footer"
    TABLE_TITLE = "table_title"
    TABLE_HEADER = "table_header"
    TABLE_DATA = "table_data"
    TABLE_REFERENCE = "table_reference"
    TAGGED = "tagged"


_FILL_RE = re.compile(
    r"^(?:_+|X{4,}|x{4,}|0{3,}|R\$\s*[_x0.-]+|"
    r"(?:escolher|selecione|selecionar)\s+(?:um|uma)\s+(?:item|op[cç][aã]o)\.?|"
    r"(?:☐|□|☑|☒).*)$",
    re.IGNORECASE,
)
_INSTRUCTION_PREFIX_RE = re.compile(
    r"^(?:notas?\s*:|importante\s*:|observa[cç][aã]o\s*:|aten[cç][aã]o\s*:|"
    r"\d+[.)]\s+(?:deve|utilizar|indicar|informar|considerar|preencher)|"
    r"(?:deve|utilizar|indicar|informe|informar|preencher|considere|considerar)\b)",
    re.IGNORECASE,
)
_EXAMPLE_RE = re.compile(r"\b(?:exemplo|por exemplo|modelo|ex\.)\b", re.IGNORECASE)
_SIGNATURE_RE = re.compile(
    r"\b(?:assinatura|secret[aá]ri[oa]|respons[aá]vel pela formaliza[cç][aã]o|ci[eê]ncia|pbdoc)\b",
    re.IGNORECASE,
)


def classify_record_role(
    record: ParagraphRecord,
    records: list[ParagraphRecord],
    structure: DocumentStructure,
) -> ContentRole:
    owner = structure.owner_for(record.ordinal)
    text = _space(record.text)
    if owner is not None and owner.tagged:
        return ContentRole.TAGGED
    if owner is not None and owner.zone in {StoryZone.HEADER, StoryZone.FOOTER}:
        return ContentRole.HEADER_FOOTER
    if not text:
        return ContentRole.BLANK
    if is_numbered_section_heading(text, paragraph=record.paragraph) and len(text) <= 220:
        return ContentRole.HEADING

    table = structure.table_for(record.table_index)
    if table is not None and record.row_index is not None:
        row = int(record.row_index)
        if row in table.structure.title_rows:
            return ContentRole.TABLE_TITLE
        if table.structure.header_row == row:
            return ContentRole.TABLE_HEADER
        if table.structure.kind.value == "reference":
            return ContentRole.TABLE_REFERENCE
        if row in table.structure.data_rows or row in table.structure.continuation_rows:
            return ContentRole.TABLE_DATA

    if _looks_like_fill(text):
        return ContentRole.FILL_AREA
    if _is_terminal_prompt(record, records, structure):
        return ContentRole.FIELD_PROMPT
    if _EXAMPLE_RE.search(text):
        return ContentRole.EXAMPLE
    if _SIGNATURE_RE.search(text) and len(text) <= 180:
        return ContentRole.SIGNATURE
    if _INSTRUCTION_PREFIX_RE.search(text) or _paragraph_is_instruction_colored(record) or len(text) >= 190:
        return ContentRole.INSTRUCTION
    if text.casefold().startswith(("nota:", "notas:", "importante:", "observação:", "observacao:")):
        return ContentRole.NOTE
    if text.endswith((":", "：")) and len(text) <= 170:
        return ContentRole.FIELD_PROMPT
    return ContentRole.FIXED_TEXT


def terminal_prompt_score(
    record: ParagraphRecord,
    records: list[ParagraphRecord],
    structure: DocumentStructure,
) -> tuple[float, list[str]]:
    """Return confidence that a colon-terminated paragraph is a fill prompt."""

    text = _space(record.text)
    if not text or not text.endswith((":", "：")) or len(text) > 190:
        return 0.0, []
    owner = structure.owner_for(record.ordinal)
    if owner is None or owner.zone is not StoryZone.BODY or owner.protected:
        return 0.0, []
    if is_numbered_section_heading(text, paragraph=record.paragraph):
        return 0.0, []

    preceding = _preceding_same_cell(record, records)
    has_instruction_context = bool(preceding and any(
        classify_record_role(item, records, structure) in {ContentRole.INSTRUCTION, ContentRole.NOTE}
        for item in preceding[-4:]
    ))
    if record.table is not None and record.cell is not None and not has_instruction_context:
        from app.document.detection.word_helpers import _unique_row_cells
        try:
            row = record.table.rows[int(record.row_index)]
            unique = _unique_row_cells(row)
            full_width = len(unique) == 1 and id(unique[0]._tc) == id(record.cell._tc)
            current_index = next((i for i, cell in enumerate(unique) if id(cell._tc) == id(record.cell._tc)), -1)
            has_right_value = current_index >= 0 and any(_space(cell.text) for cell in unique[current_index + 1:])
        except Exception:
            full_width = False
            has_right_value = False
        # A normal ``Label: | value`` grid must be handled by adjacency/fill
        # detectors, not by the terminal-prompt rule.
        if not full_width or has_right_value:
            return 0.0, []

    score = 0.35
    reasons = ["O texto termina com ':' e tem tamanho compatível com um prompt."]
    if owner.section:
        score += 0.14
        reasons.append("O prompt pertence a uma seção numerada identificada.")
    if _is_last_meaningful_in_cell(record, records):
        score += 0.22
        reasons.append("É o último texto significativo da célula do formulário.")
    if has_instruction_context:
        score += 0.14
        reasons.append("Vem após notas/instruções na mesma área.")
    prompt_tokens = (
        "previs", "data", "nome", "matrícula", "matricula", "responsável", "responsavel",
        "descrição", "descricao", "justificativa", "indique", "informe", "setor", "telefone",
        "e-mail", "email", "quantidade", "valor", "cargo", "objeto",
    )
    if any(token in text.casefold() for token in prompt_tokens):
        score += 0.12
        reasons.append("O vocabulário do texto é típico de solicitação de dado.")
    return min(score, 0.97), reasons


def _is_terminal_prompt(
    record: ParagraphRecord,
    records: list[ParagraphRecord],
    structure: DocumentStructure,
) -> bool:
    score, _ = terminal_prompt_score(record, records, structure)
    return score >= 0.65


def _is_last_meaningful_in_cell(record: ParagraphRecord, records: list[ParagraphRecord]) -> bool:
    if record.cell is None:
        # Outside tables, require no meaningful paragraph before the next section.
        for other in records:
            if other.ordinal <= record.ordinal or other.story != record.story:
                continue
            text = _space(other.text)
            if not text:
                continue
            return is_numbered_section_heading(text, paragraph=other.paragraph)
        return True
    key = id(record.cell._tc)
    for other in records:
        if other.ordinal <= record.ordinal or other.cell is None:
            continue
        if id(other.cell._tc) != key:
            continue
        if _space(other.text):
            return False
    return True


def _preceding_same_cell(record: ParagraphRecord, records: list[ParagraphRecord]) -> list[ParagraphRecord]:
    if record.cell is None:
        return []
    key = id(record.cell._tc)
    return [
        item for item in records
        if item.ordinal < record.ordinal and item.cell is not None and id(item.cell._tc) == key and _space(item.text)
    ]


def _looks_like_fill(value: str) -> bool:
    return bool(_FILL_RE.fullmatch(_space(value)))


def _paragraph_is_instruction_colored(record: ParagraphRecord) -> bool:
    for run in record.paragraph.runs:
        color = getattr(getattr(run.font, "color", None), "rgb", None)
        if color is None:
            continue
        try:
            red, green, blue = int(color[0]), int(color[1]), int(color[2])
        except Exception:
            try:
                hex_value = str(color)
                red, green, blue = int(hex_value[0:2], 16), int(hex_value[2:4], 16), int(hex_value[4:6], 16)
            except Exception:
                continue
        if red >= 170 and green <= 120 and blue <= 120:
            return True
    return False


def _space(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def instruction_is_static_guidance(
    record: ParagraphRecord,
    records: list[ParagraphRecord],
) -> bool:
    """Distinguish explanatory instructions from text that stands in for input.

    Red text alone is not enough to make a field. In many government forms red
    is simply the authoring convention for notes. A nearby explicit ``Notas`` /
    ``Importante`` block or list-style wording makes the paragraph static.
    """

    text = _space(record.text)
    folded = text.casefold()
    if re.match(r"^\s*\d+\s*[)]\s+", text):
        return True
    if folded.startswith((
        "notas:", "nota:", "importante:", "atenção:", "atencao:",
        "(preencher ", "preencher a coluna ", "caso ", "veja que ",
        "observação:", "observacao:",
    )):
        return True
    if record.cell is not None:
        key = id(record.cell._tc)
        for previous in records:
            if previous.ordinal >= record.ordinal or previous.cell is None:
                continue
            if id(previous.cell._tc) != key:
                continue
            previous_text = _space(previous.text).casefold()
            if previous_text.startswith(("notas:", "nota:", "importante:", "atenção:", "atencao:")):
                return True
    return False
