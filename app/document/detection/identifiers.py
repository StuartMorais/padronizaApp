from __future__ import annotations

import re
import unicodedata
from typing import Any

from app.document.docx.tags import PLACEHOLDER_PATTERN
from app.document.detection.patterns import (
    CHOICE_SEPARATOR_PATTERN,
    LABEL_TAIL_PATTERN,
    SECTION_NUMBER_PATTERN,
)

def _short_choice_label(value: str) -> str:
    cleaned = _clean_label(value)
    lowered = cleaned.casefold()
    rules = (
        (("não se aplica", "nao se aplica"), "Não se aplica"),
        (("não ser superior", "nao ser superior", "provável valor"), "Valor abaixo do limite"),
        (("demandas supervenientes", "art. 13"), "Demanda superveniente"),
        (("emergencial", "calamidade pública", "calamidade publica"), "Emergência ou calamidade"),
        (("sigilos", "sigilosa", "sigilosas"), "Informações sigilosas"),
        (("verificado posteriormente", "setor administrativo"), "Análise administrativa posterior"),
    )
    for tokens, label in rules:
        if any(token in lowered for token in tokens):
            return label
    first_sentence = re.split(r"(?<=[.!?;])\s+", cleaned, maxsplit=1)[0]
    if len(first_sentence) <= 88:
        return first_sentence
    return first_sentence[:85].rstrip(" ,;:-") + "…"


def _looks_like_page_header(value: str) -> bool:
    lowered = value.casefold()
    tokens = (
        "secretaria de estado",
        "governo da paraíba",
        "governo da paraiba",
        "sistema integrado de gerenciamento",
        "cep:",
    )
    return sum(token in lowered for token in tokens) >= 2


def _local_label(value: str) -> str:
    text = _normalize_space(value)
    match = LABEL_TAIL_PATTERN.search(text)
    if match:
        return _clean_label(match.group(1))
    # After another placeholder the remaining text normally starts with the
    # next local label, e.g. " Matrícula: ".
    text = text.strip(" |;–—-")
    if _is_reasonable_label(text):
        return _clean_label(text)
    return ""


def _instruction_label(text: str) -> str:
    cleaned = _normalize_space(text)
    cleaned = re.sub(
        r"^(?:informar|informe|descrever|descreva|detalhar|detalhe|"
        r"indicar|indique|justificar|justifique|preencher|preencha)\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    if len(cleaned) > 76:
        cleaned = cleaned[:73].rstrip(" ,;:-") + "…"
    return cleaned[:1].upper() + cleaned[1:] if cleaned else "Campo a preencher"


def _legacy_placeholder_field_id(token: str) -> str:
    """Return a stable valid assisted ID for a legacy ``{token}`` marker."""

    normalized = unicodedata.normalize("NFKD", str(token or ""))
    normalized = "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    ).casefold()
    normalized = re.sub(r"[^a-z0-9_.-]+", "_", normalized)
    normalized = re.sub(r"_+", "_", normalized).strip("._-")
    if not normalized:
        normalized = "campo"
    if not normalized[0].isalpha():
        normalized = "campo_" + normalized
    return f"auto.{normalized[:72]}"


def _make_field_id(label: str) -> str:
    slug = _slug(label)
    slug = SECTION_NUMBER_PATTERN.sub("", slug)
    slug = slug.strip("._-")
    if not slug:
        slug = "campo"
    if slug[0].isdigit():
        slug = "campo_" + slug
    return f"auto.{slug[:72]}"


def _unique_field_id(base: str, used: set[str]) -> str:
    base = str(base or "auto.campo").strip()
    candidate = base
    index = 2
    while candidate in used:
        candidate = f"{base}_{index}"
        index += 1
    return candidate


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    normalized = "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    ).casefold()
    normalized = SECTION_NUMBER_PATTERN.sub("", normalized)
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized)
    return normalized.strip("_")


def _humanize_id(field_id: str) -> str:
    text = str(field_id).split(".")[-1].replace("_", " ").replace("-", " ")
    return text[:1].upper() + text[1:]


def _clean_label(value: str) -> str:
    text = _normalize_space(value)
    text = SECTION_NUMBER_PATTERN.sub("", text)
    text = text.strip(" :：–—-\t\r\n")
    return text


def _looks_like_section_label(value: str) -> bool:
    raw = _normalize_space(value)
    if not raw or len(raw) > 190:
        return False
    return bool(re.match(r"^\d+(?:\.\d+)*\.?\s+", raw)) or raw.endswith(":")


def _is_reasonable_label(value: str, *, maximum: int = 150) -> bool:
    text = _normalize_space(value).strip(" :：–—-")
    if len(text) < 2 or len(text) > maximum:
        return False
    if PLACEHOLDER_PATTERN.search(text):
        return False
    if CHOICE_SEPARATOR_PATTERN.match(text):
        return False
    return sum(character.isalpha() for character in text) >= 2


def _normalize_space(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _unique_contextual_field_id(
    label: str,
    known_ids: set[str],
    *,
    section: str = "",
    row_label: str = "",
    column_label: str = "",
) -> str:
    """Prefer semantic hierarchy over anonymous numeric collision suffixes."""

    base = _make_field_id(label)
    if base not in known_ids:
        return base
    context_parts = [value for value in (section, row_label, column_label, label) if str(value).strip()]
    if context_parts:
        contextual = _make_field_id(" — ".join(context_parts))
        if contextual not in known_ids:
            return contextual
    return _unique_field_id(base, known_ids)
