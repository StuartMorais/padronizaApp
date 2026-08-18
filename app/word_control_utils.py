from __future__ import annotations

import unicodedata
from collections.abc import Iterator
from typing import Any

from docx.oxml.ns import qn


def iter_document_stories(document: Any) -> Iterator[Any]:
    """Percorre cabeçalhos, corpo e rodapés de um documento Word."""
    for section in document.sections:
        yield section.header
        yield section.first_page_header
        yield section.even_page_header

    yield document

    for section in document.sections:
        yield section.footer
        yield section.first_page_footer
        yield section.even_page_footer


def iter_unique_story_roots(document: Any) -> Iterator[Any]:
    """Percorre uma única vez cada raiz XML do corpo, cabeçalhos e rodapés."""
    processed_parts: set[object] = set()
    for story in iter_document_stories(document):
        part = story.part
        if part in processed_parts:
            continue
        processed_parts.add(part)
        yield document.element if story is document else story._element


def normalize_control_id(value: str) -> str:
    normalized = unicodedata.normalize("NFC", str(value).strip())
    lowered = normalized.casefold()
    for prefix in ("checkbox:", "date:"):
        if lowered.startswith(prefix):
            return normalized.split(":", 1)[1].strip()
    for prefix in ("dropdown:", "single_choice:"):
        if lowered.startswith(prefix):
            return normalized.split(":", 1)[1].split("|", 1)[0].strip()
    return normalized


def get_control_identifier(sdt_element: Any) -> str | None:
    properties = sdt_element.find(qn("w:sdtPr"))
    if properties is None:
        return None

    for element_name in ("w:tag", "w:alias"):
        element = properties.find(qn(element_name))
        if element is None:
            continue
        value = element.get(qn("w:val"), "").strip()
        if value:
            return normalize_control_id(value)
    return None


def read_dropdown_options(dropdown_element: Any) -> list[str]:
    if dropdown_element is None:
        return []

    options: list[str] = []
    for item in dropdown_element.findall(qn("w:listItem")):
        display_text = item.get(qn("w:displayText"), "").strip()
        value = item.get(qn("w:value"), "").strip()
        option = display_text or value
        if option:
            options.append(option)
    return options


def find_native_control_elements(properties: Any) -> tuple[Any, Any, Any, Any]:
    """Retorna caixa, data, lista suspensa e caixa combinada, nessa ordem."""
    return (
        properties.find(qn("w14:checkbox")),
        properties.find(qn("w:date")),
        properties.find(qn("w:dropDownList")),
        properties.find(qn("w:comboBox")),
    )


def classify_native_control(properties: Any) -> tuple[str | None, Any]:
    """Retorna o tipo do controle e seu elemento de configuração principal."""
    checkbox, date_control, dropdown, combo_box = (
        find_native_control_elements(properties)
    )
    if checkbox is not None:
        return "checkbox", checkbox
    if date_control is not None:
        return "date", date_control
    if dropdown is not None:
        return "dropdown", dropdown
    if combo_box is not None:
        return "dropdown", combo_box
    return None, None
