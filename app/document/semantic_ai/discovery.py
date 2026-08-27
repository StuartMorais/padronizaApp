from __future__ import annotations

import re
from typing import Any, Iterable

from app.document.detection.candidates import _candidate
from app.document.detection.identifiers import _make_field_id, _normalize_space, _unique_field_id
from app.document.semantic_ai.anchors import resolve_anchor_spans
from app.document.semantic_ai.engine import LocalSemanticEngine


_ATA_NUMBER_RE = re.compile(
    r"(?i)(?:\bAta(?:\s+de\s+Registro\s+de\s+Pre[cç]os)?|\bARP)\s*"
    r"(?:n(?:[º°o.]|úmero)?\s*)?(?P<value>\d{1,8}/\d{4})"
)
_PROCESS_NUMBER_RE = re.compile(
    r"(?i)\bprocesso(?:\s+(?:administrativo|licitat[oó]rio))?\s*"
    r"(?:n(?:[º°o.]|úmero)?\s*)?(?P<value>\d[\d./-]{3,})"
)
_CONTRACT_NUMBER_RE = re.compile(
    r"(?i)\bcontrato\s*(?:n(?:[º°o.]|úmero)?\s*)?(?P<value>\d[\d./-]{2,})"
)
_MANAGING_AGENCY_RE = re.compile(
    r"(?i)\b[oó]rg[aã]o\s+gerenciador\s+[ée](?:\s+[ao])?\s+"
    r"(?P<agency>[^,.;]{5,}?)(?:\s+[–—-]\s*(?P<acronym>[A-ZÁÉÍÓÚÇ]{2,}(?:/[A-Z]{2})?))?"
    r"(?=\s*(?:,|\.|;|$))"
)
_BULLET_LINE_RE = re.compile(r"^\s*[•·▪◦*\-–—]\s*(?P<value>.+?)\s*$")
_ALL_CAPS_NAME_RE = re.compile(
    r"^[A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][A-ZÁÀÂÃÉÊÍÓÔÕÚÇ' -]{7,}$"
)
_REGISTRATION_RE = re.compile(r"(?i)^\s*(?:mat\.?|matr[ií]cula\s*:?)\s*(?P<value>.+?)\s*$")
_CONCLUSION_RE = re.compile(r"(?i)^\s*(?:diante|ante)\s+do\s+exposto\b")


def discover_semantic_regions(
    records: list[Any],
    known_ids: set[str],
    *,
    engine: LocalSemanticEngine,
    family_fingerprint: str,
    reserved_ordinals: set[int] | None = None,
) -> list[dict[str, Any]]:
    """Discover dynamic content that has meaning but no traditional blank.

    Every fresh result is review-first. Reviewed template-family decisions own
    their exact source region first: accepted mappings can be reused, while a
    region the author explicitly kept fixed is not repeatedly suggested.
    Deterministic application still happens later.
    """

    reserved = set(reserved_ordinals or ())
    body = [
        record for record in records
        if str(getattr(record, "story", "")) == "body"
        and int(getattr(record, "ordinal", -1)) not in reserved
    ]

    learned, learned_claims = _discover_learned_mappings(
        body,
        known_ids,
        engine=engine,
        family_fingerprint=family_fingerprint,
    )
    result: list[dict[str, Any]] = list(learned)
    result.extend(_discover_inline_facts(body, known_ids, engine))
    result.extend(_discover_repeatable_lists(body, known_ids, engine))
    result.extend(_discover_numbered_prose(body, known_ids, engine))
    result.extend(_discover_conclusion(body, known_ids, engine))
    result.extend(_discover_signature_block(body, known_ids))
    result = _suppress_learned_region_conflicts(result, learned_claims)
    return _remove_nested_semantic_spans(result)


def _remove_nested_semantic_spans(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Prevent two accepted semantic fields from rewriting the same text.

    A dynamic prose block owns its editable paragraph/body. Inline facts are
    still useful in fixed prose elsewhere, but nested replacements would make
    offsets ambiguous and produce surprising tags.
    """

    owned: dict[int, list[tuple[int, int]]] = {}
    whole_paragraphs: set[int] = set()
    for candidate in candidates:
        if str(candidate.get("source", "")) != "semantic_prose":
            continue
        location = dict(candidate.get("location", {}) or {})
        kind = str(location.get("kind", ""))
        if kind == "paragraph":
            try:
                whole_paragraphs.add(int(location.get("paragraph", -1)))
            except (TypeError, ValueError):
                pass
        elif kind == "text_span":
            try:
                ordinal = int(location.get("paragraph", -1))
                start = int(location.get("start", 0))
                end = int(location.get("end", 0))
            except (TypeError, ValueError):
                continue
            if ordinal >= 0 and end > start:
                owned.setdefault(ordinal, []).append((start, end))

    filtered: list[dict[str, Any]] = []
    for candidate in candidates:
        location = dict(candidate.get("location", {}) or {})
        if str(location.get("kind", "")) != "text_spans":
            filtered.append(candidate)
            continue
        spans = []
        for span in location.get("spans", []) or []:
            if not isinstance(span, dict):
                continue
            try:
                ordinal = int(span.get("paragraph", -1))
                start = int(span.get("start", 0))
                end = int(span.get("end", 0))
            except (TypeError, ValueError):
                continue
            if ordinal in whole_paragraphs:
                continue
            if any(start >= owner_start and end <= owner_end for owner_start, owner_end in owned.get(ordinal, [])):
                continue
            spans.append(dict(span))
        if not spans:
            continue
        candidate = dict(candidate)
        candidate["location"] = {**location, "spans": spans}
        filtered.append(candidate)
    return filtered

def _discover_inline_facts(
    records: list[Any],
    known_ids: set[str],
    engine: LocalSemanticEngine,
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}

    def add_span(
        concept_id: str,
        *,
        label: str,
        field_type: str,
        record: Any,
        start: int,
        end: int,
        value: str,
        confidence: float,
    ) -> None:
        if not value.strip():
            return
        entry = grouped.get(concept_id)
        if entry is None:
            if concept_id in known_ids:
                return
            field_id = concept_id
            known_ids.add(field_id)
            entry = _candidate(
                field_id=field_id,
                label=label,
                field_type=field_type,
                confidence=confidence,
                source="semantic_inline",
                preview=value,
                location={"kind": "text_spans", "spans": []},
                default_value=value,
            )
            entry["semantic_concept_id"] = concept_id
            entry["dynamic_scope"] = "inline"
            entry["semantic_discovery"] = True
            grouped[concept_id] = entry
        entry["location"]["spans"].append(
            {
                "paragraph": int(getattr(record, "ordinal", -1)),
                "start": int(start),
                "end": int(end),
                "original": value,
            }
        )
        # Different values for the same semantic concept in one document must
        # not be silently forced into one field. Keep the candidate reviewable.
        previous = str(entry.get("default_value", "") or "")
        if previous and previous != value:
            entry["semantic_value_disagreement"] = True
            entry["requires_configuration"] = True

    for record in records:
        text = str(getattr(record, "text", "") or "")
        if not text or "{{" in text:
            continue
        for match in _ATA_NUMBER_RE.finditer(text):
            value = match.group("value")
            add_span(
                "procurement.ata_number",
                label="Número da Ata",
                field_type="text",
                record=record,
                start=match.start("value"),
                end=match.end("value"),
                value=value,
                confidence=0.91,
            )
        for match in _PROCESS_NUMBER_RE.finditer(text):
            value = match.group("value")
            add_span(
                "process.number",
                label="Número do processo",
                field_type="text",
                record=record,
                start=match.start("value"),
                end=match.end("value"),
                value=value,
                confidence=0.88,
            )
        for match in _CONTRACT_NUMBER_RE.finditer(text):
            value = match.group("value")
            add_span(
                "contract.number",
                label="Número do contrato",
                field_type="text",
                record=record,
                start=match.start("value"),
                end=match.end("value"),
                value=value,
                confidence=0.88,
            )
        for match in _MANAGING_AGENCY_RE.finditer(text):
            agency = str(match.group("agency") or "").strip()
            if agency:
                agency_start = match.start("agency")
                # Trim whitespace from the regex span itself.
                while agency_start < match.end("agency") and text[agency_start].isspace():
                    agency_start += 1
                agency_end = agency_start + len(agency)
                add_span(
                    "procurement.managing_agency",
                    label="Órgão gerenciador",
                    field_type="text",
                    record=record,
                    start=agency_start,
                    end=agency_end,
                    value=agency,
                    confidence=0.90,
                )
            acronym = str(match.group("acronym") or "").strip()
            if acronym:
                add_span(
                    "organization.acronym",
                    label="Sigla do órgão",
                    field_type="text",
                    record=record,
                    start=match.start("acronym"),
                    end=match.end("acronym"),
                    value=acronym,
                    confidence=0.88,
                )

    # If an acronym was established from a strong managing-agency sentence,
    # reuse the same field for exact occurrences in related procurement prose.
    acronym_candidate = grouped.get("organization.acronym")
    if acronym_candidate is not None:
        acronym = str(acronym_candidate.get("default_value", "") or "").strip()
        if acronym:
            seen = {
                (int(span.get("paragraph", -1)), int(span.get("start", -1)), int(span.get("end", -1)))
                for span in acronym_candidate.get("location", {}).get("spans", []) or []
            }
            for record in records:
                text = str(getattr(record, "text", "") or "")
                for match in re.finditer(re.escape(acronym), text):
                    key = (int(getattr(record, "ordinal", -1)), match.start(), match.end())
                    if key in seen:
                        continue
                    context = text[max(0, match.start() - 90):match.end() + 30].casefold()
                    if not any(token in context for token in ("ata", "arp", "órgão", "orgao", "gerenci")):
                        continue
                    acronym_candidate["location"]["spans"].append(
                        {
                            "paragraph": key[0],
                            "start": key[1],
                            "end": key[2],
                            "original": acronym,
                        }
                    )
                    seen.add(key)

    return list(grouped.values())


def _discover_repeatable_lists(
    records: list[Any],
    known_ids: set[str],
    engine: LocalSemanticEngine,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    by_position = {index: record for index, record in enumerate(records)}
    consumed: set[int] = set()

    for index, record in by_position.items():
        ordinal = int(getattr(record, "ordinal", -1))
        if ordinal in consumed:
            continue
        raw = str(getattr(record, "text", "") or "")
        lines = [line for line in raw.splitlines() if line.strip()]
        values: list[str] = []
        if len(lines) >= 2 and all(_BULLET_LINE_RE.match(line) for line in lines):
            values = [_clean_list_item(_BULLET_LINE_RE.match(line).group("value")) for line in lines]  # type: ignore[union-attr]
            paragraphs = [ordinal]
        else:
            match = _BULLET_LINE_RE.match(raw)
            if match is None or len(raw) > 150:
                continue
            paragraphs = []
            values = []
            cursor = index
            while cursor in by_position:
                current = by_position[cursor]
                current_text = str(getattr(current, "text", "") or "")
                current_match = _BULLET_LINE_RE.match(current_text)
                if current_match is None or len(current_text) > 150:
                    break
                paragraphs.append(int(getattr(current, "ordinal", -1)))
                values.append(_clean_list_item(current_match.group("value")))
                cursor += 1
            if len(values) < 2:
                continue

        previous_text = _previous_visible_text(records, index)
        concept, similarity = engine.best_concept_for_text(
            f"{previous_text} | lista de materiais | {' '.join(values[:3])}"
        )
        contextual = any(
            token in previous_text.casefold()
            for token in ("contemplando", "materiais", "itens", "aquisi", "fornecimento")
        )
        if not contextual and not (concept and concept.concept_id == "procurement.items" and similarity >= 0.42):
            continue

        field_id = "procurement.items"
        if field_id in known_ids:
            continue
        known_ids.add(field_id)
        candidate = _candidate(
            field_id=field_id,
            label="Materiais / itens",
            field_type="repeatable_list",
            confidence=0.84 if contextual else 0.75,
            source="repeatable_list",
            preview="; ".join(values),
            location={"kind": "paragraph_list", "paragraphs": paragraphs},
            default_value=values,
        )
        candidate["semantic_concept_id"] = "procurement.items"
        candidate["dynamic_scope"] = "list"
        candidate["semantic_discovery"] = True
        candidate["list_style"] = "bullet"
        candidate["list_punctuation"] = "semicolon"
        candidate["minimum_items"] = 1
        result.append(candidate)
        consumed.update(paragraphs)
    return result


def _discover_numbered_prose(
    records: list[Any],
    known_ids: set[str],
    engine: LocalSemanticEngine,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for record in records:
        raw = str(getattr(record, "text", "") or "")
        if "\n" not in raw or "{{" in raw:
            continue
        title, body = raw.split("\n", 1)
        title = _normalize_space(title).rstrip(":")
        body_value = body.strip()
        if not title or len(title) > 110 or len(body_value) < 45:
            continue
        num_pr = getattr(getattr(record, "paragraph", None), "_p", None)
        try:
            is_numbered = bool(num_pr is not None and num_pr.pPr is not None and num_pr.pPr.numPr is not None)
        except Exception:
            is_numbered = False
        if not is_numbered:
            continue
        concept, similarity = engine.best_concept_for_text(title)
        if concept is None or concept.preferred_scope != "paragraph" or similarity < 0.34:
            continue
        field_id = concept.concept_id
        if field_id in known_ids:
            continue
        known_ids.add(field_id)
        start = raw.find("\n") + 1
        while start < len(raw) and raw[start].isspace() and raw[start] != "\n":
            start += 1
        candidate = _candidate(
            field_id=field_id,
            label=title,
            field_type="multiline",
            confidence=max(0.72, min(0.88, 0.62 + similarity * 0.28)),
            source="semantic_prose",
            preview=body_value,
            location={
                "kind": "text_span",
                "paragraph": int(getattr(record, "ordinal", -1)),
                "start": start,
                "end": len(raw),
                "original": raw[start:],
            },
            default_value=body_value,
        )
        candidate["semantic_concept_id"] = concept.concept_id
        candidate["dynamic_scope"] = "paragraph"
        candidate["semantic_discovery"] = True
        result.append(candidate)
    return result


def _discover_conclusion(
    records: list[Any],
    known_ids: set[str],
    engine: LocalSemanticEngine,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for record in records:
        raw = str(getattr(record, "text", "") or "")
        text = _normalize_space(raw)
        if len(text) < 90 or not _CONCLUSION_RE.match(text) or "{{" in raw:
            continue
        # "Diante/Ante do exposto" is an explicit administrative conclusion
        # cue; semantic similarity enriches confidence but does not need to
        # defeat more frequent procurement vocabulary in the same paragraph.
        concept = engine.concept("justification.conclusion")
        if concept is None:
            continue
        _semantic_match, similarity = engine.best_concept_for_text(text[:180])
        field_id = concept.concept_id
        if field_id in known_ids:
            field_id = _unique_field_id(field_id, known_ids)
        known_ids.add(field_id)
        candidate = _candidate(
            field_id=field_id,
            label=concept.label,
            field_type="multiline",
            confidence=max(0.67, min(0.80, 0.58 + similarity * 0.22)),
            source="semantic_prose",
            preview=text,
            location={"kind": "paragraph", "paragraph": int(getattr(record, "ordinal", -1))},
            default_value=raw.strip(),
        )
        candidate["semantic_concept_id"] = concept.concept_id
        candidate["dynamic_scope"] = "paragraph"
        candidate["semantic_discovery"] = True
        result.append(candidate)
    return result


def _discover_signature_block(
    records: list[Any],
    known_ids: set[str],
) -> list[dict[str, Any]]:
    visible = [(idx, record) for idx, record in enumerate(records) if _normalize_space(getattr(record, "text", ""))]
    result: list[dict[str, Any]] = []
    for pos in range(len(visible) - 2):
        _, name_record = visible[pos]
        _, role_record = visible[pos + 1]
        _, reg_record = visible[pos + 2]
        name = _normalize_space(getattr(name_record, "text", ""))
        role = _normalize_space(getattr(role_record, "text", ""))
        registration_text = _normalize_space(getattr(reg_record, "text", ""))
        reg_match = _REGISTRATION_RE.match(registration_text)
        if not _ALL_CAPS_NAME_RE.match(name) or not reg_match:
            continue
        if len(name.split()) < 2 or len(role) < 3 or len(role) > 80 or role.isupper():
            continue
        registration = str(reg_match.group("value") or "").strip()
        specs = (
            ("person.name", "Nome do signatário", name_record, name, 0, len(str(getattr(name_record, "text", "") or "")), 0.89),
            ("person.role", "Cargo / função", role_record, role, 0, len(str(getattr(role_record, "text", "") or "")), 0.84),
        )
        for field_id, label, record, value, start, end, confidence in specs:
            if field_id in known_ids:
                continue
            resolved_id = field_id
            known_ids.add(resolved_id)
            candidate = _candidate(
                field_id=resolved_id,
                label=label,
                field_type="text",
                confidence=confidence,
                source="semantic_inline",
                preview=value,
                location={
                    "kind": "text_span",
                    "paragraph": int(getattr(record, "ordinal", -1)),
                    "start": start,
                    "end": end,
                    "original": value,
                },
                default_value=value,
            )
            candidate["semantic_concept_id"] = field_id
            candidate["dynamic_scope"] = "inline"
            candidate["semantic_discovery"] = True
            result.append(candidate)

        raw_reg = str(getattr(reg_record, "text", "") or "")
        reg_start = raw_reg.find(registration)
        if reg_start >= 0:
            if "person.registration" in known_ids:
                break
            resolved_id = "person.registration"
            known_ids.add(resolved_id)
            candidate = _candidate(
                field_id=resolved_id,
                label="Matrícula",
                field_type="text",
                confidence=0.91,
                source="semantic_inline",
                preview=registration,
                location={
                    "kind": "text_span",
                    "paragraph": int(getattr(reg_record, "ordinal", -1)),
                    "start": reg_start,
                    "end": reg_start + len(registration),
                    "original": registration,
                },
                default_value=registration,
            )
            candidate["semantic_concept_id"] = "person.registration"
            candidate["dynamic_scope"] = "inline"
            candidate["semantic_discovery"] = True
            result.append(candidate)
        break
    return result


def _discover_learned_mappings(
    records: list[Any],
    known_ids: set[str],
    *,
    engine: LocalSemanticEngine,
    family_fingerprint: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    result: list[dict[str, Any]] = []
    claims: list[dict[str, Any]] = []
    if not family_fingerprint:
        return result, claims
    for review in engine.memory.reviews:
        if str(review.get("family_fingerprint", "") or "") != family_fingerprint:
            continue
        anchor = dict(review.get("source_anchor", {}) or {})
        if not anchor:
            continue
        spans = resolve_anchor_spans(anchor, records)
        if not spans:
            continue
        scope = str(review.get("dynamic_scope", anchor.get("scope", "inline")) or "inline")
        location, default_value = _learned_location_and_value(scope, spans, records, review)
        if not location:
            continue

        accepted = bool(review.get("accepted", False))
        claims.append(
            {
                "accepted": accepted,
                "field_id": str(review.get("field_id", "") or "").strip(),
                "concept_id": str(review.get("concept_id", "") or ""),
                "location": location,
            }
        )
        if not accepted:
            continue

        field_id = str(review.get("field_id", "") or "").strip()
        if not field_id or field_id in known_ids:
            continue
        field_type = str(review.get("type", "text") or "text")
        known_ids.add(field_id)
        candidate = _candidate(
            field_id=field_id,
            label=str(review.get("label", "") or field_id),
            field_type=field_type,
            confidence=0.98,
            source="learned_mapping",
            preview=str(default_value),
            location=location,
            default_value=default_value,
        )
        candidate["semantic_concept_id"] = str(review.get("concept_id", "") or "")
        candidate["dynamic_scope"] = scope
        if scope == "list":
            candidate["list_style"] = str(review.get("list_style", "bullet") or "bullet")
            candidate["list_punctuation"] = str(review.get("list_punctuation", "semicolon") or "semicolon")
            candidate["minimum_items"] = int(review.get("minimum_items", 1) or 0)
        candidate["learned_mapping"] = True
        candidate["learned_review_count"] = int(review.get("review_count", 1) or 1)
        result.append(candidate)
    return result, claims


def _learned_location_and_value(
    scope: str,
    spans: list[dict[str, Any]],
    records: list[Any],
    review: dict[str, Any],
) -> tuple[dict[str, Any], Any]:
    if scope == "inline":
        return {"kind": "text_spans", "spans": spans}, spans[0].get("original", "")
    if scope == "paragraph" and len(spans) == 1:
        span = dict(spans[0])
        location = {
            "kind": "text_span",
            "paragraph": span["paragraph"],
            "start": int(span.get("start", 0) or 0),
            "end": int(span.get("end", 0) or 0),
            "original": str(span.get("original", "") or ""),
        }
        return location, span.get("original", "")
    if scope == "list":
        paragraphs = list(dict.fromkeys(int(span["paragraph"]) for span in spans))
        current_items: list[str] = []
        by_ordinal = {int(getattr(record, "ordinal", -1)): record for record in records}
        for ordinal in paragraphs:
            raw_text = str(getattr(by_ordinal.get(ordinal), "text", "") or "")
            for line in raw_text.splitlines():
                match = _BULLET_LINE_RE.match(line)
                if match:
                    current_items.append(_clean_list_item(match.group("value")))
        if not current_items:
            return {}, None
        return {"kind": "paragraph_list", "paragraphs": paragraphs}, current_items
    return {}, None


def _suppress_learned_region_conflicts(
    candidates: list[dict[str, Any]],
    claims: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Honor reviewed ownership before fresh semantic discovery.

    Accepted mappings own their source span and rejected mappings mark the same
    span as intentionally fixed. Only fresh semantic candidates are filtered;
    structural/native candidates remain authoritative and untouched.
    """

    if not claims:
        return candidates
    result: list[dict[str, Any]] = []
    semantic_sources = {"semantic_inline", "semantic_prose", "repeatable_list"}
    for candidate in candidates:
        if bool(candidate.get("learned_mapping", False)):
            result.append(candidate)
            continue
        if str(candidate.get("source", "")) not in semantic_sources:
            result.append(candidate)
            continue
        location = dict(candidate.get("location", {}) or {})
        if any(_locations_overlap(location, dict(claim.get("location", {}) or {})) for claim in claims):
            continue
        result.append(candidate)
    return result


def _locations_overlap(left: dict[str, Any], right: dict[str, Any]) -> bool:
    for left_ordinal, left_start, left_end in _location_ranges(left):
        for right_ordinal, right_start, right_end in _location_ranges(right):
            if left_ordinal != right_ordinal:
                continue
            if max(left_start, right_start) < min(left_end, right_end):
                return True
    return False


def _location_ranges(location: dict[str, Any]) -> list[tuple[int, int, int]]:
    kind = str(location.get("kind", ""))
    if kind == "paragraph":
        try:
            return [(int(location.get("paragraph", -1)), 0, 10**9)]
        except (TypeError, ValueError):
            return []
    if kind == "text_span":
        try:
            return [(
                int(location.get("paragraph", -1)),
                int(location.get("start", 0) or 0),
                int(location.get("end", 0) or 0),
            )]
        except (TypeError, ValueError):
            return []
    if kind == "text_spans":
        ranges: list[tuple[int, int, int]] = []
        for span in location.get("spans", []) or []:
            if not isinstance(span, dict):
                continue
            try:
                ranges.append((
                    int(span.get("paragraph", -1)),
                    int(span.get("start", 0) or 0),
                    int(span.get("end", 0) or 0),
                ))
            except (TypeError, ValueError):
                continue
        return ranges
    if kind == "paragraph_list":
        ranges = []
        for value in location.get("paragraphs", []) or []:
            try:
                ranges.append((int(value), 0, 10**9))
            except (TypeError, ValueError):
                continue
        return ranges
    return []


def _previous_visible_text(records: list[Any], index: int) -> str:
    for position in range(index - 1, max(-1, index - 5), -1):
        if position < 0:
            break
        text = _normalize_space(getattr(records[position], "text", ""))
        if text:
            return text
    return ""


def _clean_list_item(value: str) -> str:
    text = _normalize_space(value)
    text = text.rstrip(";,. ")
    return text
