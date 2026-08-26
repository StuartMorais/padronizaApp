from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from docx.table import _Cell, Table


_SPACE_RE = re.compile(r"\s+")
_NUMBER_RE = re.compile(r"0*\d{1,4}")
_CONTINUATION_VALUES = {"...", "…", ".."}
_ITEM_HEADERS = {"n", "no", "numero", "n_item", "item"}
_REFERENCE_HEADER_SETS = (
    {"data", "versao", "descricao"},
    {"data", "versão", "descrição"},
)


class TableKind(str, Enum):
    """High-level structural role of a physical Word table."""

    LAYOUT = "layout"
    REPEATABLE = "repeatable"
    FIXED_FORM = "fixed_form"
    EDITABLE_SHEET = "editable_sheet"
    REFERENCE = "reference"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class GridCell:
    cell: _Cell
    start: int
    span: int
    text: str
    lines: tuple[str, ...] = ()


@dataclass
class TableStructure:
    kind: TableKind
    total_columns: int
    title_rows: list[int] = field(default_factory=list)
    title: str = ""
    header_row: int | None = None
    header_labels: list[str] = field(default_factory=list)
    header_groups: list[str] = field(default_factory=list)
    header_options: dict[int, list[dict[str, str]]] = field(default_factory=dict)
    data_rows: list[int] = field(default_factory=list)
    continuation_rows: list[int] = field(default_factory=list)
    footer_rows: list[int] = field(default_factory=list)
    confidence: float = 0.0
    reasons: list[str] = field(default_factory=list)

    @property
    def owned_rows(self) -> list[int]:
        result: list[int] = []
        for value in (
            *self.title_rows,
            *([] if self.header_row is None else [self.header_row]),
            *self.data_rows,
            *self.continuation_rows,
        ):
            if value not in result:
                result.append(value)
        return sorted(result)


def analyze_word_table(table: Table) -> TableStructure:
    """Classify a Word table before field-level heuristics inspect its cells.

    Word forms frequently use a table both as layout and as actual tabular
    data.  The distinction must be made from the physical grid first; once a
    data table has been flattened into independent field candidates the UI can
    no longer reliably reconstruct the original relationship.
    """

    total_columns = max(1, len(table.columns))
    rows = [row_grid_cells(row) for row in table.rows]
    if not rows:
        return TableStructure(TableKind.UNKNOWN, total_columns)

    title_rows: list[int] = []
    title_parts: list[str] = []
    cursor = 0
    while cursor < len(rows):
        cells = rows[cursor]
        if len(cells) != 1 or cells[0].span < total_columns:
            break
        text = _clean_text(cells[0].text)
        # Blank spacer rows do not make a table a data structure. Section-like
        # full-width rows are kept as title context; ordinary prose ends title
        # discovery so it can later become a footer/note.
        if not text:
            cursor += 1
            continue
        if _looks_like_section_title(text):
            title_rows.append(cursor)
            title_parts.append(text)
            cursor += 1
            continue
        # A non-numbered full-width caption may be the table title only when
        # no stronger title has been found yet. Once a numbered section owns
        # the table, subsequent merged rows are content/response areas.
        if not title_rows and len(text) <= 160:
            title_rows.append(cursor)
            title_parts.append(text)
            cursor += 1
            continue
        break

    header_row = _find_primary_header_row(rows, start=cursor, total_columns=total_columns)
    if header_row is None:
        return TableStructure(
            TableKind.LAYOUT,
            total_columns,
            title_rows=title_rows,
            title=_best_title(title_parts),
            confidence=0.85,
            reasons=["A tabela não possui cabeçalho tabular multicoluna convincente."],
        )

    header_labels, header_groups, header_options = _expand_header_row(
        rows[header_row],
        total_columns,
    )
    meaningful_headers = [label for label in header_labels if _reasonable_header(label)]
    if total_columns < 3 or len(meaningful_headers) < 3:
        return TableStructure(
            TableKind.LAYOUT,
            total_columns,
            title_rows=title_rows,
            title=_best_title(title_parts),
            header_row=header_row,
            header_labels=header_labels,
            header_groups=header_groups,
            header_options=header_options,
            confidence=0.9,
            reasons=["A grade tem menos de três colunas de dados úteis."],
        )

    data_rows: list[int] = []
    continuation_rows: list[int] = []
    footer_rows: list[int] = []
    numeric_rows: list[int] = []
    blank_editable_cells = 0

    for row_index in range(header_row + 1, len(rows)):
        cells = rows[row_index]
        if not cells:
            continue
        if len(cells) == 1 and cells[0].span >= total_columns:
            footer_rows.extend(range(row_index, len(rows)))
            break
        values = row_values_by_grid(cells, total_columns)
        first = _clean_text(values[0]) if values else ""
        if first in _CONTINUATION_VALUES:
            continuation_rows.append(row_index)
            blank_editable_cells += sum(not _clean_text(value) for value in values[1:])
            continue
        if _NUMBER_RE.fullmatch(first):
            numeric_rows.append(row_index)
            data_rows.append(row_index)
            blank_editable_cells += sum(not _clean_text(value) for value in values[1:])
            continue
        # Non-numbered rows can still form a fixed matrix/form table. Keep rows
        # with several populated cells as structural data, but do not call them
        # repeatable automatically.
        populated = sum(bool(_clean_text(value)) for value in values)
        if populated >= 2:
            data_rows.append(row_index)
            continue
        if populated == 0:
            # A completely blank row under a strong header is model-row evidence
            # for an editable sheet, not a new layout section.
            data_rows.append(row_index)
            blank_editable_cells += max(0, total_columns - 1)
            continue
        footer_rows.extend(range(row_index, len(rows)))
        break

    header_keys = {_slug(label) for label in header_labels if label}
    first_header = _slug(header_labels[0]) if header_labels else ""
    has_item_header = first_header in _ITEM_HEADERS
    has_grouped_header = any(group for group in header_groups)
    reference_header = any(reference.issubset(header_keys) for reference in _REFERENCE_HEADER_SETS)

    if reference_header and not has_item_header:
        return TableStructure(
            TableKind.REFERENCE,
            total_columns,
            title_rows=title_rows,
            title=_best_title(title_parts),
            header_row=header_row,
            header_labels=header_labels,
            header_groups=header_groups,
            header_options=header_options,
            data_rows=data_rows,
            continuation_rows=continuation_rows,
            footer_rows=footer_rows,
            confidence=0.96,
            reasons=["Cabeçalhos indicam tabela de histórico/referência, não formulário de itens."],
        )

    # Strong repeatable-table signature. One numbered model row plus an ellipsis
    # row is intentionally equivalent to several numbered rows; this is a very
    # common institutional Word convention and is exactly what the SIA33TDR
    # fixture uses.
    repeat_score = 0
    reasons: list[str] = []
    if has_item_header:
        repeat_score += 2
        reasons.append("A primeira coluna é um identificador de item/número.")
    if numeric_rows:
        repeat_score += 2
        reasons.append("Existe linha modelo numerada.")
    if len(numeric_rows) >= 2:
        repeat_score += 2
        reasons.append("Há várias linhas numeradas consecutivas.")
    if continuation_rows:
        repeat_score += 2
        reasons.append("Existe linha de continuação com reticências.")
    if blank_editable_cells >= 2:
        repeat_score += 1
        reasons.append("A linha modelo contém várias células destinadas a preenchimento.")
    if title_rows:
        repeat_score += 1
        reasons.append("Há título de seção mesclado sobre a grade.")
    if has_grouped_header:
        repeat_score += 1
        reasons.append("O cabeçalho possui agrupamento de colunas/mesclagem horizontal.")

    if repeat_score >= 6 and numeric_rows:
        confidence = min(0.99, 0.86 + 0.02 * repeat_score)
        return TableStructure(
            TableKind.REPEATABLE,
            total_columns,
            title_rows=title_rows,
            title=_best_title(title_parts),
            header_row=header_row,
            header_labels=header_labels,
            header_groups=header_groups,
            header_options=header_options,
            data_rows=data_rows,
            continuation_rows=continuation_rows,
            footer_rows=footer_rows,
            confidence=confidence,
            reasons=reasons,
        )

    # Header followed immediately by a single blank/full-width note row is the
    # existing editable-sheet pattern.  Only the primary header is eligible;
    # rows deep inside a fixed table must never be reinterpreted as new headers.
    next_index = header_row + 1
    if next_index < len(rows):
        next_cells = rows[next_index]
        if len(next_cells) == 1 and next_cells[0].span >= total_columns:
            note = _clean_text(next_cells[0].text)
            if not note or len(note) >= 55 or _looks_like_fill_area(note):
                return TableStructure(
                    TableKind.EDITABLE_SHEET,
                    total_columns,
                    title_rows=title_rows,
                    title=_best_title(title_parts),
                    header_row=header_row,
                    header_labels=header_labels,
                    header_groups=header_groups,
                    header_options=header_options,
                    footer_rows=list(range(next_index, len(rows))),
                    confidence=0.94,
                    reasons=["Cabeçalho multicoluna seguido por área mesclada de resposta/nota."],
                )

    if len(data_rows) >= 2:
        return TableStructure(
            TableKind.FIXED_FORM,
            total_columns,
            title_rows=title_rows,
            title=_best_title(title_parts),
            header_row=header_row,
            header_labels=header_labels,
            header_groups=header_groups,
            header_options=header_options,
            data_rows=data_rows,
            continuation_rows=continuation_rows,
            footer_rows=footer_rows,
            confidence=0.9,
            reasons=["Cabeçalho e várias linhas formam uma matriz fixa, não uma lista numerada."],
        )

    return TableStructure(
        TableKind.UNKNOWN,
        total_columns,
        title_rows=title_rows,
        title=_best_title(title_parts),
        header_row=header_row,
        header_labels=header_labels,
        header_groups=header_groups,
        header_options=header_options,
        data_rows=data_rows,
        continuation_rows=continuation_rows,
        footer_rows=footer_rows,
        confidence=0.55,
        reasons=["A tabela possui grade real, mas não há evidência suficiente para automatizar sua semântica."],
    )


def row_grid_cells(row) -> list[GridCell]:
    """Return unique row cells with their physical Word-grid positions."""

    result: list[GridCell] = []
    cells = list(row.cells)
    index = 0
    while index < len(cells):
        cell = cells[index]
        key = id(cell._tc)
        end = index + 1
        while end < len(cells) and id(cells[end]._tc) == key:
            end += 1
        raw_lines = tuple(
            line
            for paragraph in cell.paragraphs
            if (line := _clean_text(paragraph.text))
        )
        result.append(
            GridCell(
                cell=cell,
                start=index,
                span=max(1, end - index),
                text=_clean_text(cell.text),
                lines=raw_lines,
            )
        )
        index = end
    return result


def row_values_by_grid(cells: list[GridCell], total_columns: int) -> list[str]:
    values = [""] * total_columns
    for cell in cells:
        for position in range(cell.start, min(total_columns, cell.start + cell.span)):
            values[position] = cell.text
    return values


def _find_primary_header_row(
    rows: list[list[GridCell]],
    *,
    start: int,
    total_columns: int,
) -> int | None:
    # Only inspect the first two non-title rows. A row deep inside a fixed table
    # can contain several short values but is data, not a new spreadsheet header.
    considered = 0
    for row_index in range(start, min(len(rows), start + 3)):
        cells = rows[row_index]
        if not cells:
            continue
        if len(cells) == 1 and cells[0].span >= total_columns:
            continue
        considered += 1
        # A Word form often has a visually tabular row like
        # ``E-mail | servidor@... | Telefone | (83) ...``.  Those are
        # label/value pairs, not a data-table header. Detect obvious values
        # before classifying the row as a structural header.
        if any(_looks_like_value_or_fill(cell.text) for cell in cells):
            if considered >= 2:
                break
            continue
        reasonable = sum(_reasonable_header(cell.text) for cell in cells)
        if len(cells) >= 3 and reasonable >= 3:
            return row_index
        if considered >= 2:
            break
    return None


def _expand_header_row(
    cells: list[GridCell],
    total_columns: int,
) -> tuple[list[str], list[str], dict[int, list[dict[str, str]]]]:
    labels = [""] * total_columns
    groups = [""] * total_columns
    options: dict[int, list[dict[str, str]]] = {}

    for cell in cells:
        expanded, group, cell_options = _expand_header_cell(cell)
        for offset in range(cell.span):
            position = cell.start + offset
            if position >= total_columns:
                break
            label = expanded[offset] if offset < len(expanded) else cell.text
            labels[position] = label or f"Coluna {position + 1}"
            groups[position] = group
            if cell_options and cell.span == 1:
                options[position] = cell_options

    return labels, groups, options


def _expand_header_cell(
    cell: GridCell,
) -> tuple[list[str], str, list[dict[str, str]]]:
    lines = [line for line in cell.lines if line]
    flat = _clean_header(cell.text)
    if cell.span <= 1:
        choice_options = _choice_options_from_lines(lines or [flat])
        if choice_options:
            if len(lines) >= 2:
                label = _clean_header(" ".join(lines[:-1])) or flat
            else:
                label = _label_without_choice_suffix(flat, choice_options) or flat
            return [label], "", choice_options
        return [flat], "", []

    # Common grouped header: "Quantidade" on one line and one year per grid
    # column on the next line. Keep the group name while giving each physical
    # column a distinct label/ID in the application.
    years = re.findall(r"\b(?:19|20)\d{2}\b", " ".join(lines[1:] if len(lines) > 1 else lines))
    if len(years) == cell.span:
        group = _clean_header(lines[0] if lines else flat)
        return [f"{group} — {year}" for year in years], group, []

    if len(lines) >= 2:
        group = _clean_header(lines[0])
        tail = " ".join(lines[1:])
        parts = [
            _clean_header(value)
            for value in re.split(r"\s{2,}|\t+|\s*/\s*", tail)
            if _clean_header(value)
        ]
        if len(parts) == cell.span:
            return [f"{group} — {part}" for part in parts], group, []

    return [flat for _ in range(cell.span)], flat, []


def _choice_options_from_lines(lines: list[str]) -> list[dict[str, str]]:
    if not lines:
        return []

    tail = _clean_text(lines[-1])
    if "/" not in tail:
        return []

    candidate = tail
    # When Word stores the visual second line as a real paragraph, the last
    # line can be interpreted directly.  When it stores a manual line break in
    # one paragraph, only accept a trailing choice list introduced by ``?`` or
    # ``:``. This avoids turning headers such as
    # ``Especificação/Descrição (Material/Equipamento/Serviço)`` into dropdowns.
    if len(lines) == 1:
        match = re.search(r"[?:]\s*(?P<choices>[^?:]+(?:/[^?:]+)+)\s*$", tail)
        if match is None:
            return []
        candidate = _clean_text(match.group("choices"))

    raw = [_clean_text(value) for value in candidate.split("/")]
    values = [value for value in raw if value and len(value) <= 24]
    if not (2 <= len(values) <= 6):
        return []
    if any(len(value.split()) > 4 for value in values):
        return []
    return [{"label": value, "value": value} for value in values]


def _label_without_choice_suffix(
    label: str,
    options: list[dict[str, str]],
) -> str:
    values = [str(option.get("value", "")).strip() for option in options]
    if not values:
        return _clean_header(label)
    suffix = r"\s*/\s*".join(re.escape(value) for value in values)
    return _clean_header(re.sub(rf"\s*{suffix}\s*$", "", label, flags=re.IGNORECASE))


def _reasonable_header(value: Any) -> bool:
    text = _clean_header(value)
    if len(text) < 2 or len(text) > 130:
        return False
    if _looks_like_fill_area(text):
        return False
    # A field/sample mask is data, not a header.
    if re.fullmatch(r"[Xx_\-. /()0-9]+", text):
        return False
    return True


def _looks_like_value_or_fill(value: Any) -> bool:
    text = _clean_text(value)
    if _looks_like_fill_area(text):
        return True
    if re.search(r"[Xx_]{4,}", text):
        return True
    if "@" in text and re.search(r"\S+@\S+", text):
        return True
    # Numeric phone samples must contain a real phone separator.  A loose
    # ``DD DDDD DDDD`` pattern also matches grouped year headers such as
    # ``2023 2024 2025`` and would incorrectly disqualify a legitimate
    # multi-level table header.
    if re.search(r"(?:\(\d{2}\)|\b\d{2}\b)\s*\d{4,5}-\d{4}\b", text):
        return True
    if re.search(r"(?:_+|0{2,})\s*/\s*(?:_+|0{2,})", text):
        return True
    if re.search(r"(?:escolher|selecione)\s+(?:um|uma)\s+(?:item|op[cç][aã]o)", text, re.IGNORECASE):
        return True
    return False


def _looks_like_section_title(value: str) -> bool:
    from app.document.detection.structure import parse_numbered_section_heading
    return parse_numbered_section_heading(_clean_text(value)) is not None


def _looks_like_fill_area(value: str) -> bool:
    text = _clean_text(value)
    if not text:
        return True
    return bool(re.fullmatch(r"(?:[_Xx.\-–— ]{3,}|Escolher um item\.?)", text, re.IGNORECASE))


def _clean_header(value: Any) -> str:
    return _clean_text(value).strip("| :：–—-\t\r\n")


def _clean_text(value: Any) -> str:
    return _SPACE_RE.sub(" ", str(value or "")).strip()


def _best_title(parts: list[str]) -> str:
    for value in reversed(parts):
        if _looks_like_section_title(value):
            return value.rstrip(":").strip()
    return (parts[-1].rstrip(":").strip() if parts else "")


def _slug(value: Any) -> str:
    import unicodedata

    normalized = unicodedata.normalize("NFKD", _clean_text(value))
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "_", ascii_text.casefold()).strip("_")
