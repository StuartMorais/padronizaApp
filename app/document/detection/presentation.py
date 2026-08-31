from __future__ import annotations

import ast
import re
from typing import Any


_GENERIC_LABELS = {
    "campo",
    "campo a preencher",
    "possível campo",
    "texto editável",
    "texto a preencher",
    "selecione uma opção",
    "escolha uma opção",
    "escolha uma alternativa",
    "itens da tabela",
    "itens da planilha",
}

_TECHNICAL_PREFIXES = ("auto.", "pdf_", "field_", "campo_")


def candidate_display_label(candidate: dict[str, Any]) -> str:
    """Return the user-facing name shown during field review.

    The review table is deliberately a semantic/user layer. Internal field IDs,
    detector names and generic fallback labels are useful for diagnostics but
    should not be the primary name a non-technical reviewer has to interpret.
    """

    label = _clean(candidate.get("label", ""))
    if _is_specific_label(label, candidate):
        return label

    for key in ("semantic_label_suggestion", "semantic_ai_label_suggestion"):
        suggestion = _clean(candidate.get(key, ""))
        if _is_specific_label(suggestion, candidate):
            return suggestion

    context = dict(candidate.get("source_context", {}) or {})
    nearby_label = _label_from_before_context(context.get("before", ""))
    if nearby_label:
        return nearby_label

    section = _clean(candidate.get("section", ""))
    if section and section.casefold() not in _GENERIC_LABELS:
        preview = _short_value(candidate_document_excerpt(candidate), 52)
        return f"{section} — {preview}" if preview else section

    field_id = _clean(candidate.get("field_id", ""))
    humanized = _humanize_field_id(field_id)
    if humanized:
        return humanized

    preview = _short_value(candidate_document_excerpt(candidate), 58)
    return f"Texto a preencher — {preview}" if preview else "Campo a preencher"


def candidate_document_excerpt(candidate: dict[str, Any], *, max_length: int = 320) -> str:
    """Return a readable document excerpt without leaking Python representations."""

    context = dict(candidate.get("source_context", {}) or {})
    target = _display_value(context.get("target", ""))
    if target:
        return _truncate(target, max_length)

    preview = _display_value(candidate.get("preview", ""))
    if preview:
        return _truncate(preview, max_length)

    default_value = _display_value(candidate.get("default_value", ""))
    if default_value:
        return _truncate(default_value, max_length)

    location = dict(candidate.get("location", {}) or {})
    kind = str(location.get("kind", ""))
    if kind in {"empty_cell", "append_tag"}:
        label = candidate_display_label_without_excerpt(candidate)
        return f"Área vazia associada a “{label}”" if label else "Área vazia a preencher"
    return "Trecho exato não disponível"


def candidate_display_label_without_excerpt(candidate: dict[str, Any]) -> str:
    """Label fallback that cannot recurse through candidate_document_excerpt."""

    label = _clean(candidate.get("label", ""))
    if _is_specific_label(label, candidate):
        return label
    for key in ("semantic_label_suggestion", "semantic_ai_label_suggestion"):
        suggestion = _clean(candidate.get(key, ""))
        if _is_specific_label(suggestion, candidate):
            return suggestion
    context = dict(candidate.get("source_context", {}) or {})
    nearby_label = _label_from_before_context(context.get("before", ""))
    if nearby_label:
        return nearby_label
    return _humanize_field_id(_clean(candidate.get("field_id", "")))


def _display_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        ordered = []
        for key in ("label", "value", "text", "name"):
            part = _clean(value.get(key, ""))
            if part and part not in ordered:
                ordered.append(part)
        if ordered:
            return " — ".join(ordered)
        return "; ".join(
            f"{_clean(key)}: {_display_value(item)}"
            for key, item in value.items()
            if _display_value(item)
        )
    if isinstance(value, (list, tuple, set)):
        parts = [_display_value(item) for item in value]
        return "; ".join(part for part in parts if part)

    text = str(value or "").strip()
    if not text:
        return ""

    # Older candidates sometimes persisted list defaults using ``str(list)``.
    # Render them as document text instead of exposing Python syntax in the UI.
    if text[:1] in "[({" and text[-1:] in "])}":
        try:
            parsed = ast.literal_eval(text)
        except (ValueError, SyntaxError):
            parsed = None
        if isinstance(parsed, (list, tuple, set, dict)):
            return _display_value(parsed)

    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return " · ".join(line for line in lines if line)


def _label_from_before_context(value: Any) -> str:
    text = str(value or "").replace("\r", "\n")
    if not text.strip():
        return ""
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.split("\n") if line.strip()]
    if not lines:
        return ""
    tail = lines[-1]

    # A label ending in ':' is the strongest generic cue and avoids making a
    # semantic guess about unfamiliar institutional vocabulary.
    match = re.search(r"(?:^|[.;!?])\s*([^.;!?]{2,90}?)\s*:\s*$", tail)
    if match:
        label = _clean_label(match.group(1))
        if label:
            return label
    if tail.endswith(":"):
        label = _clean_label(tail[:-1])
        if label:
            return label
    return ""


def _clean_label(value: str) -> str:
    value = re.sub(r"\s+", " ", str(value or "")).strip(" \t\r\n:;–—-")
    value = re.sub(r"^[•·▪◦]+\s*", "", value).strip()
    if len(value) > 90:
        value = value[-90:].lstrip(" ,.;:-")
    return value


def _is_specific_label(label: str, candidate: dict[str, Any]) -> bool:
    if not label or label.casefold() in _GENERIC_LABELS:
        return False
    field_id = _clean(candidate.get("field_id", ""))
    if label == field_id and (
        "." in label or "_" in label or label.casefold().startswith(_TECHNICAL_PREFIXES)
    ):
        return False
    return True


def _humanize_field_id(field_id: str) -> str:
    if not field_id:
        return ""
    parts = [part for part in re.split(r"[._-]+", field_id) if part]
    while parts and parts[0].casefold() in {"auto", "field", "campo", "pdf"}:
        parts.pop(0)
    if not parts:
        return ""
    text = " ".join(parts)
    return text[:1].upper() + text[1:]


def _short_value(value: str, limit: int) -> str:
    value = _clean(value)
    return _truncate(value, limit) if value else ""


def _truncate(value: str, limit: int) -> str:
    value = str(value or "").strip()
    if len(value) <= limit:
        return value
    return value[: max(1, limit - 1)].rstrip() + "…"


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()
