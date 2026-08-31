from __future__ import annotations

import hashlib
import re
from typing import Any, Iterable


def paragraph_fingerprint(text: object) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip().casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]


def build_source_anchor(
    candidate: dict[str, Any],
    records: Iterable[Any],
    *,
    family_fingerprint: str = "",
) -> dict[str, Any]:
    by_ordinal = {int(getattr(record, "ordinal", -1)): record for record in records}
    location = dict(candidate.get("location", {}) or {})
    kind = str(location.get("kind", ""))
    spans = _location_spans(location)
    anchor_spans: list[dict[str, Any]] = []
    for span in spans:
        ordinal = int(span.get("paragraph", -1))
        record = by_ordinal.get(ordinal)
        if record is None:
            continue
        text = str(getattr(record, "text", "") or "")
        start = max(0, int(span.get("start", 0) or 0))
        end = min(len(text), int(span.get("end", len(text)) or len(text)))
        original = str(span.get("original", text[start:end]) or text[start:end])
        left = text[max(0, start - 90):start]
        right = text[end:min(len(text), end + 90)]
        anchor_spans.append(
            {
                "paragraph": ordinal,
                "story": str(getattr(record, "story", "") or ""),
                "table_index": getattr(record, "table_index", None),
                "row_index": getattr(record, "row_index", None),
                "cell_index": getattr(record, "cell_index", None),
                "start": start,
                "end": end,
                "original": original,
                "left_context": left,
                "right_context": right,
                "paragraph_fingerprint": paragraph_fingerprint(text),
                **(
                    {"render": str(span.get("render", ""))}
                    if str(span.get("render", "")).strip()
                    else {}
                ),
            }
        )

    if not anchor_spans and "paragraph" in location:
        ordinal = int(location.get("paragraph", -1))
        record = by_ordinal.get(ordinal)
        if record is not None:
            text = str(getattr(record, "text", "") or "")
            anchor_spans.append(
                {
                    "paragraph": ordinal,
                    "story": str(getattr(record, "story", "") or ""),
                    "table_index": getattr(record, "table_index", None),
                    "row_index": getattr(record, "row_index", None),
                    "cell_index": getattr(record, "cell_index", None),
                    "start": 0,
                    "end": len(text),
                    "original": text,
                    "left_context": "",
                    "right_context": "",
                    "paragraph_fingerprint": paragraph_fingerprint(text),
                }
            )

    return {
        "version": 1,
        "scope": str(candidate.get("dynamic_scope", _scope_from_kind(kind))),
        "family_fingerprint": str(family_fingerprint),
        "spans": anchor_spans,
    }


def resolve_anchor_spans(
    anchor: dict[str, Any],
    records: Iterable[Any],
) -> list[dict[str, Any]]:
    """Resolve reviewed spans against a related document version.

    Resolution is intentionally conservative and bounded to the same/nearby
    paragraph. Exact paragraph fingerprints win. Inline spans then use stable
    left/right context. Whole-paragraph/list anchors are allowed to change in
    length and therefore fall back to the complete structurally matching
    paragraph instead of truncating the new text to the old length.
    """

    by_ordinal = {int(getattr(record, "ordinal", -1)): record for record in records}
    scope = str(anchor.get("scope", "inline") or "inline").casefold()
    resolved: list[dict[str, Any]] = []
    for stored in anchor.get("spans", []) or []:
        if not isinstance(stored, dict):
            continue
        try:
            ordinal = int(stored.get("paragraph", -1) or -1)
        except (TypeError, ValueError):
            return []
        candidates = []
        if ordinal in by_ordinal:
            candidates.append(by_ordinal[ordinal])
        candidates.extend(
            record for key, record in by_ordinal.items()
            if key != ordinal and abs(key - ordinal) <= 4
        )
        # Prefer records that still occupy the same structural owner.
        candidates.sort(
            key=lambda record: (
                0 if _same_structural_owner(stored, record) else 1,
                abs(int(getattr(record, "ordinal", -1)) - ordinal),
            )
        )
        found = None
        for record in candidates:
            text = str(getattr(record, "text", "") or "")
            if not text.strip():
                continue
            if paragraph_fingerprint(text) == str(stored.get("paragraph_fingerprint", "")):
                start = max(0, int(stored.get("start", 0) or 0))
                end = min(len(text), int(stored.get("end", len(text)) or len(text)))
                found = {
                    "paragraph": int(getattr(record, "ordinal", -1)),
                    "start": start,
                    "end": end,
                    "original": text[start:end],
                    **(
                        {"render": str(stored.get("render", ""))}
                        if str(stored.get("render", "")).strip()
                        else {}
                    ),
                }
                break

            context_span = _resolve_context_span(text, stored, scope=scope)
            if context_span is not None:
                start, end = context_span
                current = text[start:end]
                if current.strip():
                    found = {
                        "paragraph": int(getattr(record, "ordinal", -1)),
                        "start": start,
                        "end": end,
                        "original": current,
                        **(
                            {"render": str(stored.get("render", ""))}
                            if str(stored.get("render", "")).strip()
                            else {}
                        ),
                    }
                    break

            # Dynamic paragraphs/lists (and inline fields that originally
            # occupied the complete paragraph, such as a signatory name) can
            # legitimately change to a longer/shorter value. Only use this
            # fallback when the source owner still matches.
            if _same_structural_owner(stored, record) and (
                scope in {"paragraph", "list"} or _stored_span_is_whole_paragraph(stored)
            ):
                found = {
                    "paragraph": int(getattr(record, "ordinal", -1)),
                    "start": 0,
                    "end": len(text),
                    "original": text,
                    **(
                        {"render": str(stored.get("render", ""))}
                        if str(stored.get("render", "")).strip()
                        else {}
                    ),
                }
                break
        if found is None:
            return []
        resolved.append(found)
    return resolved


def source_context(candidate: dict[str, Any], records: Iterable[Any]) -> dict[str, str]:
    by_ordinal = {int(getattr(record, "ordinal", -1)): record for record in records}
    spans = _location_spans(dict(candidate.get("location", {}) or {}))
    if not spans:
        return {}
    span = spans[0]
    record = by_ordinal.get(int(span.get("paragraph", -1)))
    if record is None:
        return {}
    text = str(getattr(record, "text", "") or "")
    start = max(0, int(span.get("start", 0) or 0))
    end = min(len(text), int(span.get("end", len(text)) or len(text)))
    return {
        "before": text[max(0, start - 160):start],
        "target": text[start:end],
        "after": text[end:min(len(text), end + 160)],
    }


def _location_spans(location: dict[str, Any]) -> list[dict[str, Any]]:
    kind = str(location.get("kind", ""))
    if kind == "text_span":
        return [location]
    if kind == "text_spans":
        return [dict(item) for item in location.get("spans", []) or [] if isinstance(item, dict)]
    if kind == "paragraph_list":
        return [
            {"paragraph": int(value), "start": 0, "end": 10**9}
            for value in location.get("paragraphs", []) or []
        ]
    return []


def _scope_from_kind(kind: str) -> str:
    if kind in {"text_span", "text_spans"}:
        return "inline"
    if kind == "paragraph_list":
        return "list"
    return "paragraph"


def _resolve_context_span(
    text: str, stored: dict[str, Any], *, scope: str = "inline"
) -> tuple[int, int] | None:
    left = str(stored.get("left_context", "") or "")
    right = str(stored.get("right_context", "") or "")
    original = str(stored.get("original", "") or "")

    start = _match_left_boundary(text, left) if left else None
    search_start = start if start is not None else 0
    end = _match_right_boundary(text, right, search_start) if right else None
    if start is not None and end is not None and end > start:
        return start, end

    if scope == "paragraph":
        if start is not None and end is None:
            return start, len(text)
        if end is not None and start is None:
            return 0, end
    if scope == "list" and _stored_span_is_whole_paragraph(stored):
        return 0, len(text)

    if start is not None:
        delimiter = _leading_delimiter(right)
        if delimiter:
            delimiter_pos = text.find(delimiter, start)
            if delimiter_pos > start:
                return start, delimiter_pos
        # Compact identifiers (numbers, acronyms, process IDs) usually retain
        # their token shape even when the value changes. Stop at whitespace or
        # punctuation rather than trusting the old character count.
        if original and not re.search(r"\s", original):
            match = re.match(r"[^\s,;:()]+", text[start:])
            if match and match.group(0).strip():
                return start, start + len(match.group(0))
        fallback_end = start + len(original)
        if original and fallback_end <= len(text):
            return start, fallback_end

    if end is not None:
        if original and not re.search(r"\s", original):
            prefix = text[:end]
            match = re.search(r"([^\s,;:()]+)\s*$", prefix)
            if match and match.group(1).strip():
                return match.start(1), match.end(1)
        fallback_start = end - len(original)
        if original and fallback_start >= 0:
            return fallback_start, end
    return None


def _match_left_boundary(text: str, context: str) -> int | None:
    if not context:
        return None
    exact = text.find(context)
    if exact >= 0:
        return exact + len(context)
    for fragment in _context_suffixes(context):
        position = text.find(fragment)
        if position >= 0:
            return position + len(fragment)
    return None


def _match_right_boundary(text: str, context: str, start: int) -> int | None:
    if not context:
        return None
    exact = text.find(context, max(0, start))
    if exact >= 0:
        return exact
    for fragment in _context_prefixes(context):
        position = text.find(fragment, max(0, start))
        if position >= 0:
            return position
    return None


def _context_suffixes(value: str) -> list[str]:
    compact = value[-90:]
    lengths = [len(compact), 72, 56, 44, 34, 26, 20, 16, 12]
    result: list[str] = []
    for length in lengths:
        if length <= 0 or length > len(compact):
            continue
        fragment = compact[-length:]
        if fragment not in result and len(fragment.strip()) >= 8:
            result.append(fragment)
    return result


def _context_prefixes(value: str) -> list[str]:
    compact = value[:90]
    lengths = [len(compact), 72, 56, 44, 34, 26, 20, 16, 12]
    result: list[str] = []
    for length in lengths:
        if length <= 0 or length > len(compact):
            continue
        fragment = compact[:length]
        if fragment not in result and len(fragment.strip()) >= 8:
            result.append(fragment)
    return result


def _leading_delimiter(value: str) -> str:
    if not value:
        return ""
    match = re.match(r"^(\s*[^\wÁÀÂÃÉÊÍÓÔÕÚÇáàâãéêíóôõúç]{1,4}\s*)", value)
    if match:
        delimiter = match.group(1)
        return delimiter if delimiter.strip() else ""
    return ""


def _same_structural_owner(stored: dict[str, Any], record: Any) -> bool:
    stored_story = str(stored.get("story", "") or "")
    if stored_story and stored_story != str(getattr(record, "story", "") or ""):
        return False
    for key, attr in (
        ("table_index", "table_index"),
        ("row_index", "row_index"),
        ("cell_index", "cell_index"),
    ):
        expected = stored.get(key)
        if expected is None:
            continue
        if getattr(record, attr, None) != expected:
            return False
    return True


def _stored_span_is_whole_paragraph(stored: dict[str, Any]) -> bool:
    original = str(stored.get("original", "") or "")
    try:
        start = int(stored.get("start", 0) or 0)
        end = int(stored.get("end", 0) or 0)
    except (TypeError, ValueError):
        return False
    return start == 0 and bool(original) and end >= len(original)
