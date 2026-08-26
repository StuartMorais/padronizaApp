from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docx import Document
from docx.table import _Cell

from app.domain.field_ids import FIELD_ID_TOKEN_PATTERN
from app.document.detection.table_structure import analyze_word_table, row_grid_cells
from app.document.docx.tags import PLACEHOLDER_PATTERN, ROW_NUMBER_IDS, TagKind, parse_tag


_REPEAT_MARKER_PATTERN = re.compile(
    rf"\{{\{{\s*repeat:({FIELD_ID_TOKEN_PATTERN})\s*\}}\}}",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RepeatableMarkerRepair:
    table_index: int
    column_index: int
    old_marker: str
    new_marker: str
    reason: str


@dataclass(frozen=True)
class RepeatableMarkerRepairResult:
    changed: bool
    repairs: tuple[RepeatableMarkerRepair, ...] = ()

    @property
    def marker_count(self) -> int:
        return len(self.repairs)


def repair_repeatable_table_markers(docx_path: Path) -> RepeatableMarkerRepairResult:
    """Repair structurally unambiguous malformed repeatable-row markers.

    Older/partial automatic-detection runs could leave a working DOCX with the
    same child marker in several physical columns, for example three
    ``{{itens.quantidade}}`` markers under the grouped headers 2023/2024/2025.
    The normal scanner correctly rejects that ambiguity, but the template
    editor must be able to recover its own working copy instead of crashing.

    Repairs are intentionally conservative:

    * only rows that already contain exactly one ``{{repeat:...}}`` marker are
      considered;
    * unique, correctly-prefixed child IDs are preserved;
    * duplicate child IDs are disambiguated from the physical Word headers;
    * a child marker using the wrong table prefix is moved under the repeat
      table and receives the structural header ID;
    * row-number and repeat markers are never rewritten.

    The file is saved only when at least one marker changes.
    """

    path = Path(docx_path).expanduser().resolve()
    document = Document(str(path))
    repairs: list[RepeatableMarkerRepair] = []

    for table_index, table in enumerate(document.tables):
        structure = analyze_word_table(table)
        header_labels = list(structure.header_labels)

        for row in table.rows:
            row_text = "\n".join(cell.text for cell in _unique_cells(row))
            repeat_matches = list(_REPEAT_MARKER_PATTERN.finditer(row_text))
            table_ids = {match.group(1).strip() for match in repeat_matches}
            if len(table_ids) != 1:
                continue
            table_id = next(iter(table_ids))

            occurrences: list[dict[str, Any]] = []
            for grid_cell in row_grid_cells(row):
                cell = grid_cell.cell
                raw_text = cell.text or ""
                for marker in PLACEHOLDER_PATTERN.finditer(raw_text):
                    raw_marker = marker.group(1).strip()
                    definition = parse_tag(raw_marker, strict=False)
                    if definition.kind in {TagKind.REPEAT, TagKind.ROW_NUMBER}:
                        continue
                    field_id = str(definition.field_id or "").strip()
                    if not field_id:
                        continue
                    prefix = f"{table_id}."
                    correctly_prefixed = field_id.startswith(prefix)
                    child_id = field_id[len(prefix):].strip() if correctly_prefixed else ""
                    simple_child = bool(child_id) and "." not in child_id
                    occurrences.append(
                        {
                            "cell": cell,
                            "column_index": int(grid_cell.start),
                            "raw_marker": raw_marker,
                            "field_id": field_id,
                            "child_id": child_id,
                            "correctly_prefixed": correctly_prefixed and simple_child,
                        }
                    )

            if not occurrences:
                continue

            counts: dict[str, int] = {}
            for item in occurrences:
                if item["correctly_prefixed"]:
                    key = str(item["child_id"])
                    counts[key] = counts.get(key, 0) + 1

            duplicate_ids = {key for key, count in counts.items() if count > 1}
            if not duplicate_ids and all(item["correctly_prefixed"] for item in occurrences):
                continue

            reserved_ids = {
                str(item["child_id"])
                for item in occurrences
                if item["correctly_prefixed"] and str(item["child_id"]) not in duplicate_ids
            }
            assigned_ids = set(reserved_ids)

            for item in occurrences:
                old_child = str(item["child_id"])
                needs_duplicate_repair = item["correctly_prefixed"] and old_child in duplicate_ids
                needs_prefix_repair = not item["correctly_prefixed"]
                if not (needs_duplicate_repair or needs_prefix_repair):
                    continue

                column_index = int(item["column_index"])
                header = (
                    header_labels[column_index]
                    if 0 <= column_index < len(header_labels)
                    else ""
                )
                preferred = _slug(header)
                if not preferred or preferred in {"item", "numero", "n"}:
                    preferred = old_child or f"coluna_{column_index + 1}"
                new_child = _unique_id(preferred, assigned_ids)
                assigned_ids.add(new_child)
                new_field_id = f"{table_id}.{new_child}"
                new_marker = _rewrite_marker_id(str(item["raw_marker"]), new_field_id)
                if new_marker == item["raw_marker"]:
                    continue

                _replace_marker_in_cell(
                    item["cell"],
                    str(item["raw_marker"]),
                    new_marker,
                )
                repairs.append(
                    RepeatableMarkerRepair(
                        table_index=table_index,
                        column_index=column_index,
                        old_marker=str(item["raw_marker"]),
                        new_marker=new_marker,
                        reason=(
                            "duplicate_column_id"
                            if needs_duplicate_repair
                            else "wrong_table_prefix"
                        ),
                    )
                )

    if repairs:
        document.save(str(path))

    return RepeatableMarkerRepairResult(bool(repairs), tuple(repairs))


def _rewrite_marker_id(raw_marker: str, new_field_id: str) -> str:
    value = str(raw_marker or "").strip()
    if ":" not in value:
        return new_field_id

    prefix, definition = value.split(":", 1)
    normalized_prefix = prefix.strip().casefold()
    if normalized_prefix not in {"checkbox", "date", "dropdown", "single_choice", "default_or_text"}:
        return new_field_id

    suffix = ""
    if "|" in definition:
        suffix = "|" + definition.split("|", 1)[1]
    return f"{prefix.strip()}:{new_field_id}{suffix}"


def _replace_marker_in_cell(cell: _Cell, old_marker: str, new_marker: str) -> None:
    old_token = "{{" + old_marker + "}}"
    new_token = "{{" + new_marker + "}}"
    for paragraph in cell.paragraphs:
        text = paragraph.text or ""
        if old_token not in text:
            continue
        replacement = text.replace(old_token, new_token)
        runs = list(paragraph.runs)
        if runs:
            runs[0].text = replacement
            for run in runs[1:]:
                run.text = ""
        else:
            paragraph.add_run(replacement)
        return

    # Markers can be split across several Word runs. ``cell.text`` still
    # exposes the complete token, so fall back to the first paragraph while
    # preserving the paragraph/cell formatting itself.
    text = cell.text or ""
    if old_token not in text:
        return
    replacement = text.replace(old_token, new_token)
    paragraphs = list(cell.paragraphs)
    if not paragraphs:
        cell.add_paragraph(replacement)
        return
    runs = list(paragraphs[0].runs)
    if runs:
        runs[0].text = replacement
        for run in runs[1:]:
            run.text = ""
    else:
        paragraphs[0].add_run(replacement)
    for paragraph in paragraphs[1:]:
        element = paragraph._element
        parent = element.getparent()
        if parent is not None:
            parent.remove(element)


def _unique_cells(row) -> list[_Cell]:
    result: list[_Cell] = []
    seen: set[int] = set()
    for cell in row.cells:
        key = id(cell._tc)
        if key in seen:
            continue
        seen.add(key)
        result.append(cell)
    return result


def _slug(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    normalized = "".join(
        character for character in normalized if not unicodedata.combining(character)
    ).casefold()
    return re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")


def _unique_id(base: str, used: set[str]) -> str:
    candidate = str(base or "coluna").strip("_") or "coluna"
    if candidate not in used:
        return candidate
    index = 2
    while f"{candidate}_{index}" in used:
        index += 1
    return f"{candidate}_{index}"
