from __future__ import annotations

from typing import Any
from docx.table import _Cell, Table
from docx.text.paragraph import Paragraph

class AutomaticDetectionError(ValueError):
    """Raised when accepted automatic detections cannot be applied safely."""


class AutomaticDetectionCancelled(AutomaticDetectionError):
    """Raised when the user cooperatively cancels assisted detection."""


class ParagraphRecord:
    __slots__ = (
        "ordinal",
        "paragraph",
        "text",
        "story",
        "table_index",
        "row_index",
        "cell_index",
        "cell",
        "table",
        "understanding",
    )

    def __init__(
        self,
        *,
        ordinal: int,
        paragraph: Paragraph,
        story: str,
        table_index: int | None = None,
        row_index: int | None = None,
        cell_index: int | None = None,
        cell: _Cell | None = None,
        table: Table | None = None,
    ) -> None:
        self.ordinal = ordinal
        self.paragraph = paragraph
        self.text = paragraph.text or ""
        self.story = story
        self.table_index = table_index
        self.row_index = row_index
        self.cell_index = cell_index
        self.cell = cell
        self.table = table
        self.understanding = None


class CandidateDefinition(dict[str, Any]):
    """Dict-compatible candidate model used during assisted detection."""

