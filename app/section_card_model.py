from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable


GROUP_LAYOUT_LABELS = {
    "choice": "Grupo de escolha",
    "form_grid": "Grade do documento",
    "table": "Tabela de registros",
}

LAYOUT_LABELS = {
    "auto": "Automático",
    "grid": "Grade",
    "full_width": "Largura total",
    "choice": "Escolha",
    "form_grid": "Grade do documento",
    "table": "Tabela",
}


def _section_name(field: dict[str, Any]) -> str:
    return str(field.get("section", "")).strip() or "Dados do documento"


def build_section_card_models(fields: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Create presentation-ready section/card models without depending on Qt.

    The returned structure preserves the first appearance of sections and semantic
    groups. It intentionally contains only UI-facing metadata so the editor can be
    rebuilt safely whenever the field table changes.
    """

    sections: list[dict[str, Any]] = []
    by_title: dict[str, dict[str, Any]] = {}

    for source_field in fields:
        field = deepcopy(source_field)
        title = _section_name(field)
        section = by_title.get(title)
        if section is None:
            section = {
                "title": title,
                "field_count": 0,
                "entries": [],
                "search_text": title.casefold(),
            }
            by_title[title] = section
            sections.append(section)

        section["field_count"] += 1
        label = str(field.get("label") or field.get("id") or "Campo sem nome").strip()
        field_id = str(field.get("id", "")).strip()
        field_type = str(field.get("type", "text")).strip() or "text"
        layout = str(field.get("layout", "auto")).strip() or "auto"
        layout_group = str(field.get("layout_group", "")).strip()

        field_model = {
            "id": field_id,
            "label": label,
            "type": field_type,
            "layout": layout,
            "layout_label": LAYOUT_LABELS.get(layout, layout.replace("_", " ").title()),
            "required": bool(field.get("required", False)),
            "search_text": " ".join((title, label, field_id, field_type, layout)).casefold(),
        }

        grouped = layout in GROUP_LAYOUT_LABELS and bool(layout_group)
        if grouped:
            group_key = f"{layout}:{layout_group}"
            entry = next(
                (
                    candidate
                    for candidate in section["entries"]
                    if candidate.get("kind") == "group" and candidate.get("key") == group_key
                ),
                None,
            )
            if entry is None:
                group_label = str(field.get("layout_group_label", "")).strip() or layout_group
                entry = {
                    "kind": "group",
                    "key": group_key,
                    "title": f"{GROUP_LAYOUT_LABELS[layout]} · {group_label}",
                    "layout": layout,
                    "fields": [],
                }
                section["entries"].append(entry)
            entry["fields"].append(field_model)
        else:
            section["entries"].append({"kind": "field", "field": field_model})

        section["search_text"] += f" {field_model['search_text']}"

    return sections


def rename_section_fields(
    fields: Iterable[dict[str, Any]],
    old_name: str,
    new_name: str,
) -> list[dict[str, Any]]:
    old = old_name.strip() or "Dados do documento"
    new = new_name.strip()
    if not new:
        raise ValueError("O nome da seção não pode ficar vazio.")

    result: list[dict[str, Any]] = []
    for source_field in fields:
        field = deepcopy(source_field)
        if _section_name(field) == old:
            field["section"] = new
        result.append(field)
    return result


def reorder_section_fields(
    fields: Iterable[dict[str, Any]],
    section_name: str,
    direction: int,
) -> list[dict[str, Any]]:
    """Move a complete section block while preserving field order inside it."""

    source = [deepcopy(field) for field in fields]
    section_order: list[str] = []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for field in source:
        title = _section_name(field)
        if title not in grouped:
            grouped[title] = []
            section_order.append(title)
        grouped[title].append(field)

    target_name = section_name.strip() or "Dados do documento"
    if target_name not in grouped or direction == 0:
        return source

    current = section_order.index(target_name)
    target = current + (-1 if direction < 0 else 1)
    if target < 0 or target >= len(section_order):
        return source

    section_order[current], section_order[target] = section_order[target], section_order[current]
    return [field for title in section_order for field in grouped[title]]
