from __future__ import annotations

from typing import Any

from docx.oxml.ns import qn
from docx.table import _Cell

def _remove_floating_checkmark_shapes(root: Any, *, limit: int) -> int:
    """Remove standalone floating checked-box artwork from an assisted copy.

    Word can render a checked square as a floating text box completely outside
    the table that visually contains it. When we materialize an inferred blank
    marker cell as a real tagged checkbox, that old floating artwork must be
    removed or it would remain permanently checked in the generated document.
    """

    if limit <= 0:
        return 0
    mc_tag = "{http://schemas.openxmlformats.org/markup-compatibility/2006}AlternateContent"
    tc_tag = qn("w:tc")
    check_chars = set("✓✔√☑☒")
    removed = 0
    for node in list(root.iter(mc_tag)):
        # Never remove artwork structurally inside a table cell here; regular
        # marker-cell replacement already handles those nodes.
        ancestor = node.getparent()
        inside_cell = False
        while ancestor is not None:
            if ancestor.tag == tc_tag:
                inside_cell = True
                break
            ancestor = ancestor.getparent()
        if inside_cell:
            continue

        text = "".join((item.text or "") for item in node.iter(qn("w:t")))
        compact = "".join(ch for ch in text if not ch.isspace())
        if not compact or any(ch not in check_chars for ch in compact):
            continue
        parent = node.getparent()
        if parent is None:
            continue
        parent.remove(node)
        removed += 1
        if removed >= limit:
            break
    return removed


def _unique_row_cells(row) -> list[_Cell]:
    result: list[_Cell] = []
    seen: set[int] = set()
    for cell in row.cells:
        key = id(cell._tc)
        if key in seen:
            continue
        seen.add(key)
        result.append(cell)
    return result
