from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from docx.document import Document as _Document

from app.document.docx.tags import PLACEHOLDER_PATTERN
from app.document.detection.candidates import _candidate
from app.document.detection.context_helpers import (
    _contains_authoritative_marker, _context_label_for_record, _detected_placeholder_type,
    _is_pure_fill_area_text, _looks_like_fill_area_text, _paragraph_is_red,
)
from app.document.detection.identifiers import (
    _clean_label, _humanize_id, _is_reasonable_label, _legacy_placeholder_field_id,
    _local_label, _looks_like_section_label, _make_field_id, _normalize_space, _slug,
    _unique_field_id,
)
from app.document.detection.models import ParagraphRecord as _ParagraphRecord
from app.document.detection.patterns import (
    CHECKBOX_TOKEN_PATTERN, CURRENCY_PLACEHOLDER_PATTERN, FOLLOWUP_AREA_PATTERN,
    GENERIC_DROPDOWN_PATTERN, INSTRUCTION_PATTERN, LEGACY_BRACED_PLACEHOLDER_PATTERN,
    SAMPLE_EMAIL_PLACEHOLDER_PATTERN, SECTION_NUMBER_PATTERN, UNDERSCORE_PLACEHOLDER_PATTERN,
    X_PLACEHOLDER_PATTERN, ZERO_CPF_PLACEHOLDER_PATTERN, ZERO_PHONE_PLACEHOLDER_PATTERN,
)
from app.document.detection.word_helpers import _unique_row_cells
from app.document.understanding.semantic import semantic_label, semantic_section
from app.document.understanding.smart_template import suggest_field_type

_PREFILLED_TEXT_SECTION_PATTERN = re.compile(
    r"\b(?:justificativa|fundamenta[cç][aã]o|descri[cç][aã]o|detalhamento|"
    r"necessidade|motiva[cç][aã]o|objeto|especifica[cç][aã]o|observa[cç][aã]o|"
    r"provid[eê]ncia|parecer|an[aá]lise|considera[cç][oõ]es|informa[cç][oõ]es)\b",
    re.IGNORECASE,
)
_PREFILLED_TEXT_STATIC_PREFIX_PATTERN = re.compile(
    r"^\s*(?:texto\s+fixo|nota|aten[cç][aã]o|aviso|instru[cç][aã]o|"
    r"orienta[cç][aã]o|observa[cç][aã]o\s+fixa|rodap[eé])\s*[:\-]",
    re.IGNORECASE,
)


def _detect_blank_followup_areas(
    records: list[_ParagraphRecord],
    known_ids: set[str],
    reserved_ordinals: set[int],
) -> list[dict[str, Any]]:
    """Detect blank paragraphs directly after observation/justification prompts."""

    by_cell: dict[int, list[_ParagraphRecord]] = defaultdict(list)
    for record in records:
        if record.cell is not None and record.story == "body":
            by_cell[id(record.cell._tc)].append(record)

    result: list[dict[str, Any]] = []
    for cell_records in by_cell.values():
        cell_records.sort(key=lambda item: item.ordinal)
        for index, record in enumerate(cell_records[:-1]):
            if record.ordinal in reserved_ordinals:
                continue
            prompt = _normalize_space(record.text)
            if not prompt or not FOLLOWUP_AREA_PATTERN.match(prompt):
                continue
            # Use the first truly blank paragraph after the prompt, but do not
            # jump over another visible paragraph.
            target: _ParagraphRecord | None = None
            for following in cell_records[index + 1 :]:
                if _normalize_space(following.text):
                    break
                target = following
                break
            if target is None or target.ordinal in reserved_ordinals:
                continue
            label = _clean_label(prompt)
            field_id = _unique_field_id(_make_field_id(label), known_ids)
            result.append(
                _candidate(
                    field_id=field_id,
                    label=label,
                    field_type="multiline",
                    confidence=0.82,
                    source="empty_cell",
                    preview=prompt,
                    location={
                        "kind": "paragraph",
                        "paragraph": target.ordinal,
                    },
                )
            )
    return result


def _detect_inline_placeholders(
    record: _ParagraphRecord,
    records: list[_ParagraphRecord],
    known_ids: set[str],
) -> list[dict[str, Any]]:
    text = record.text or ""
    if not text or PLACEHOLDER_PATTERN.search(text):
        return []

    matches = list(CURRENCY_PLACEHOLDER_PATTERN.finditer(text))
    matches.extend(X_PLACEHOLDER_PATTERN.finditer(text))
    matches.extend(UNDERSCORE_PLACEHOLDER_PATTERN.finditer(text))
    matches.extend(ZERO_PHONE_PLACEHOLDER_PATTERN.finditer(text))
    matches.extend(ZERO_CPF_PLACEHOLDER_PATTERN.finditer(text))
    matches.extend(SAMPLE_EMAIL_PLACEHOLDER_PATTERN.finditer(text))
    matches.extend(LEGACY_BRACED_PLACEHOLDER_PATTERN.finditer(text))
    matches.sort(key=lambda match: (match.start(), -(match.end() - match.start())))
    # Some patterns intentionally overlap (for example an xxxxx@example style
    # e-mail also matches the generic X placeholder). Keep only the widest
    # non-overlapping span so one visual fill area becomes one field.
    non_overlapping: list[re.Match[str]] = []
    for match in matches:
        if any(
            match.start() < existing.end() and existing.start() < match.end()
            for existing in non_overlapping
        ):
            continue
        non_overlapping.append(match)
    matches = sorted(non_overlapping, key=lambda match: match.start())
    if not matches:
        return []

    result: list[dict[str, Any]] = []
    previous_end = 0
    for match in matches:
        is_legacy_braced = LEGACY_BRACED_PLACEHOLDER_PATTERN.fullmatch(match.group(0)) is not None
        local_context = text[previous_end : match.start()]
        # PDF-to-DOCX reconstruction frequently groups several visual PDF
        # lines into one Word paragraph separated by manual line breaks.
        # Prefer the text on the current visual line so a paragraph such as
        # ``Placa: ABC1D23\nData: __/__/____\nHorário: __:__`` yields
        # ``Data`` and ``Horário`` instead of labels polluted by the previous
        # line. Fall back to the complete local context for ordinary DOCX.
        visual_line = local_context.rsplit("\n", 1)[-1]
        label = _local_label(visual_line)
        if not label and visual_line != local_context:
            label = _local_label(local_context)
        if not label:
            label = _context_label_for_record(record, records)

        if is_legacy_braced:
            inner_token = str(match.group(1) or "").strip()
            # A single-braced token is only safe to claim automatically when
            # it has a strong field signal: a local/adjacent label, an inline
            # label ending in ':', or an identifier-like dotted/underscored
            # token.  This deliberately ignores prose such as
            # ``Use chaves {assim} no exemplo``.
            has_inline_colon = bool(re.search(r"[:：]\s*$", local_context))
            token_is_structured = any(separator in inner_token for separator in (".", "_", "-"))
            is_isolated_table_value = (
                record.table is not None
                and _normalize_space(text) == _normalize_space(match.group(0))
                and bool(label)
            )
            if not (label and (has_inline_colon or is_isolated_table_value)) and not token_is_structured:
                previous_end = match.end()
                continue

        if not label and CURRENCY_PLACEHOLDER_PATTERN.fullmatch(match.group(0)):
            # A bare monetary mask is semantically stronger than an anonymous
            # ``Campo XX`` suggestion. Parenthetical text such as
            # ``(valor por extenso)`` remains untouched as contextual text.
            label = "Valor"
        if is_legacy_braced:
            inner_token = str(match.group(1) or "").strip()
            field_id_seed = _legacy_placeholder_field_id(inner_token)
            field_id = _unique_field_id(field_id_seed, known_ids)
        else:
            field_id = _unique_field_id(
                _make_field_id(label or f"campo_{record.ordinal + 1}"),
                known_ids,
            )
        known_ids.add(field_id)
        field_type = _detected_placeholder_type(label or field_id, match.group(0))
        candidate = _candidate(
                field_id=field_id,
                label=label or _humanize_id(field_id),
                field_type=field_type,
                confidence=(0.98 if label else 0.82) if is_legacy_braced else (0.91 if label else 0.74),
                source="legacy_placeholder" if is_legacy_braced else "inline_placeholder",
                preview=match.group(0),
                location={
                    "kind": "text_span",
                    "paragraph": record.ordinal,
                    "start": match.start(),
                    "end": match.end(),
                    "original": match.group(0),
                },
            )
        if is_legacy_braced:
            candidate["legacy_marker"] = match.group(0)
            candidate["legacy_marker_id"] = str(match.group(1) or "").strip()
        result.append(candidate)
        previous_end = match.end()
    return result


def _detect_dropdown_prompt(
    record: _ParagraphRecord,
    records: list[_ParagraphRecord],
    known_ids: set[str],
) -> dict[str, Any] | None:
    text = record.text or ""
    if not text or PLACEHOLDER_PATTERN.search(text):
        return None

    prompt_pattern = re.compile(
        r"(?:escolher|selecione|selecionar)\s+(?:um|uma)\s+"
        r"(?:item|op[cç][aã]o)\.?\s*$",
        re.IGNORECASE,
    )
    match = prompt_pattern.search(text)
    if match is None:
        return None

    prefix = text[: match.start()]
    label = _local_label(prefix) or _context_label_for_record(record, records)
    field_id = _unique_field_id(_make_field_id(label or "opcao"), known_ids)
    return _candidate(
        field_id=field_id,
        label=label or "Selecione uma opção",
        field_type="dropdown",
        confidence=0.82 if label else 0.70,
        source="dropdown_prompt",
        preview=match.group(0),
        location={
            "kind": "text_span",
            "paragraph": record.ordinal,
            "start": match.start(),
            "end": match.end(),
            "original": match.group(0),
        },
        options=[],
        default_selected=False,
        requires_configuration=True,
    )


def _detect_labeled_sample_value(
    record: _ParagraphRecord,
    known_ids: set[str],
) -> dict[str, Any] | None:
    """Detect short example/default values that should still be editable.

    This is deliberately whitelist-based.  Institutional fixed text such as
    ``Órgão: Secretaria ...`` must stay static, while values such as
    ``País: Brasil`` are commonly examples/defaults that help the user
    understand what belongs in the field.
    """

    text = record.text or ""
    if not text or PLACEHOLDER_PATTERN.search(text) or ":" not in text:
        return None

    colon = text.find(":")
    label = _clean_label(text[:colon])
    value_start = colon + 1
    while value_start < len(text) and text[value_start].isspace():
        value_start += 1
    value = _normalize_space(text[value_start:])
    if not value or len(value) > 80:
        return None

    normalized_label = _slug(label)
    editable_example_labels = {
        "pais",
        "nacionalidade",
        # Common short defaults/examples in reconstructed PDF forms. These are
        # deliberately label-whitelisted so institutional prose such as
        # ``Órgão: Secretaria ...`` remains static.
        "placa",
        "setor_responsavel",
    }
    if normalized_label not in editable_example_labels:
        return None
    if (
        INSTRUCTION_PATTERN.match(value)
        or GENERIC_DROPDOWN_PATTERN.match(value)
        or CHECKBOX_TOKEN_PATTERN.search(value)
        or X_PLACEHOLDER_PATTERN.search(value)
        or UNDERSCORE_PLACEHOLDER_PATTERN.search(value)
        or ZERO_PHONE_PLACEHOLDER_PATTERN.search(value)
        or ZERO_CPF_PLACEHOLDER_PATTERN.search(value)
        or CURRENCY_PLACEHOLDER_PATTERN.search(value)
        or SAMPLE_EMAIL_PLACEHOLDER_PATTERN.search(value)
    ):
        return None

    field_id = _unique_field_id(_make_field_id(label), known_ids)
    return _candidate(
        field_id=field_id,
        label=label,
        field_type=suggest_field_type(label),
        confidence=0.86,
        source="sample_value",
        preview=value,
        location={
            "kind": "text_span",
            "paragraph": record.ordinal,
            "start": value_start,
            "end": len(text),
            "original": text[value_start:],
        },
        placeholder=value,
    )


def _detect_labeled_instruction(
    record: _ParagraphRecord,
    known_ids: set[str],
) -> dict[str, Any] | None:
    text = record.text or ""
    if not text or PLACEHOLDER_PATTERN.search(text) or ":" not in text:
        return None
    colon = text.find(":")
    label = _clean_label(text[:colon])
    tail_start = colon + 1
    while tail_start < len(text) and text[tail_start].isspace():
        tail_start += 1
    tail = text[tail_start:]
    if not _is_reasonable_label(label, maximum=120) or not INSTRUCTION_PATTERN.match(tail):
        return None
    if len(_normalize_space(tail)) < 12 or len(_normalize_space(tail)) > 800:
        return None

    field_type = suggest_field_type(label)
    if field_type == "text" and len(_normalize_space(tail)) >= 70:
        field_type = "multiline"
    field_id = _unique_field_id(_make_field_id(label), known_ids)
    return _candidate(
        field_id=field_id,
        label=label,
        field_type=field_type,
        confidence=0.90 if _paragraph_is_red(record.paragraph) else 0.82,
        source="instruction",
        preview=tail,
        location={
            "kind": "text_span",
            "paragraph": record.ordinal,
            "start": tail_start,
            "end": len(text),
            "original": tail,
        },
    )


def _detect_prefilled_written_text(
    record: _ParagraphRecord,
    records: list[_ParagraphRecord],
    known_ids: set[str],
) -> dict[str, Any] | None:
    """Detect existing prose that likely represents an editable answer.

    Some institutional templates are distributed *already filled* with a
    previous/requester-authored justification instead of a visual blank.  A
    placeholder-only detector necessarily treats that prose as fixed text.
    Detector V2.9 recognizes the strongest structural versions of this pattern
    and converts the prose into a multiline field whose initial value is the
    original text.

    The rule is intentionally conservative.  Long prose is not enough on its
    own: it must live under a numbered response-like section or inside a
    full-width/merged table response row.  Explicitly fixed notes and ordinary
    headers remain static.
    """

    raw_text = str(record.text or "")
    text = _normalize_space(raw_text)
    role = str(getattr(getattr(record, "understanding", None), "role", "") or "")
    if role in {
        "instruction", "note", "heading", "table_title", "table_header",
        "table_reference", "signature", "example", "tagged",
    }:
        return None
    owner = getattr(record, "structure", None)
    if getattr(owner, "table_kind", "") in {"fixed_form", "reference"}:
        return None
    if (
        len(text) < 45
        or len(text) > 2200
        or record.story != "body"
        or _contains_authoritative_marker(record.paragraph)
        or _looks_like_section_label(text)
        or _PREFILLED_TEXT_STATIC_PREFIX_PATTERN.match(text)
        or CHECKBOX_TOKEN_PATTERN.search(text)
        or GENERIC_DROPDOWN_PATTERN.fullmatch(text)
        or _is_pure_fill_area_text(text)
    ):
        return None

    # A paragraph made mostly of a short heading followed by punctuation is
    # not a written response, even when Word wrapped it visually.
    if len(text.split()) < 7 or sum(ch.isalpha() for ch in text) < 24:
        return None

    section = _clean_label(semantic_section(record))
    section_is_response = bool(section and _PREFILLED_TEXT_SECTION_PATTERN.search(section))

    # A full-width/merged table row is another common way users store a written
    # answer below a heading or below a table header.  Determine this from
    # unique XML cells rather than the apparent ``row.cells`` count because
    # python-docx repeats references for merged cells.
    full_width_response_row = False
    table_context_label = ""
    if record.table is not None and record.row_index is not None and record.cell is not None:
        try:
            row = record.table.rows[int(record.row_index)]
            unique_cells = _unique_row_cells(row)
            current_key = id(record.cell._tc)
            if len(unique_cells) == 1 and id(unique_cells[0]._tc) == current_key:
                # Require meaningful structure above the prose: either a
                # numbered section already in scope or a preceding header row
                # with at least two short cells. This prevents random one-cell
                # narrative tables from becoming editable by accident.
                has_header_row = False
                for previous_index in range(int(record.row_index) - 1, -1, -1):
                    previous_cells = _unique_row_cells(record.table.rows[previous_index])
                    values = [_normalize_space(cell.text) for cell in previous_cells]
                    values = [value for value in values if value]
                    if not values:
                        continue
                    if len(values) >= 2 and all(len(value) <= 90 for value in values):
                        has_header_row = True
                        break
                    if len(values) == 1 and _looks_like_section_label(values[0]):
                        table_context_label = _clean_label(values[0])
                        break
                full_width_response_row = bool(section or has_header_row or table_context_label)
        except (IndexError, AttributeError, TypeError, ValueError):
            full_width_response_row = False

    if not section_is_response and not full_width_response_row:
        return None

    label = section or table_context_label or _context_label_for_record(record, records)
    label = _clean_label(label)
    if not _is_reasonable_label(label, maximum=180):
        label = "Texto editável"

    # Full-width narrative rows are a little more ambiguous than explicit
    # Justificativa/Descrição sections, so keep their confidence lower.  Both
    # remain reviewable in the assisted-detection screen.
    confidence = 0.90 if section_is_response else 0.82
    field_id = _unique_field_id(_make_field_id(label), known_ids)
    return _candidate(
        field_id=field_id,
        label=label,
        field_type="multiline",
        confidence=confidence,
        source="prefilled_text",
        preview=text,
        location={
            "kind": "paragraph",
            "paragraph": record.ordinal,
            "table_index": record.table_index,
            "row_index": record.row_index,
            "cell_index": record.cell_index,
            "prefilled_text": True,
        },
        default_value=raw_text.strip(),
    )


def _detect_adjacent_sample_value(
    record: _ParagraphRecord,
    records: list[_ParagraphRecord],
    known_ids: set[str],
) -> dict[str, Any] | None:
    """Detect editable example/default values stored in the next table cell.

    Many institutional forms use four physical cells per row::

        E-mail: | servidor@orgao.gov.br | Telefone: | (83) 99999-9999

    The values are examples/defaults, not fixed institutional prose.  Keep this
    heuristic label-whitelisted so rows such as ``Órgão: Secretaria ...`` stay
    read-only.
    """

    text = _normalize_space(record.text)
    role = str(getattr(getattr(record, "understanding", None), "role", "") or "")
    owner = getattr(record, "structure", None)
    if role in {"table_header", "table_title", "table_reference", "heading", "tagged"}:
        return None
    if (
        not text
        or record.cell is None
        or record.table is None
        or record.row_index is None
        or len(record.cell.paragraphs) != 1
        or _contains_authoritative_marker(record.paragraph)
    ):
        return None

    # Do not require a trailing colon here. Real Word forms frequently use
    # alternating cells such as ``E-mail | exemplo@orgao.gov.br | Telefone |
    # (83) 99999-9999``. The physical adjacency is the delimiter. Keeping the
    # semantic whitelist below prevents ordinary institutional prose from
    # being converted merely because it sits next to another cell.
    explicit_label = text.endswith((":", "："))
    label = _clean_label(text)
    if not _is_reasonable_label(label, maximum=100):
        return None

    normalized_label = _slug(label)
    allowed_plain_labels = {
        "unidade",
        "lotacao",
        "setor",
        "municipio",
        "cidade",
        "pais",
        "nacionalidade",
    }
    email_labels = {"email", "e_mail", "correio_eletronico"}
    phone_labels = {"telefone", "celular", "fone"}

    unique_cells = _unique_row_cells(record.table.rows[record.row_index])
    current_index = next(
        (index for index, cell in enumerate(unique_cells) if id(cell._tc) == id(record.cell._tc)),
        -1,
    )
    if current_index < 0 or current_index + 1 >= len(unique_cells):
        return None
    value_cell = unique_cells[current_index + 1]
    value_records = [item for item in records if item.cell is not None and id(item.cell._tc) == id(value_cell._tc)]
    non_empty = [item for item in value_records if _normalize_space(item.text)]
    if len(non_empty) != 1 or _contains_authoritative_marker(non_empty[0].paragraph):
        return None

    value_record = non_empty[0]
    value = _normalize_space(value_record.text)
    if not value or len(value) > 100 or _is_pure_fill_area_text(value):
        return None

    looks_editable = False
    if normalized_label in email_labels:
        looks_editable = bool(
            re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value, re.IGNORECASE)
        )
    elif normalized_label in phone_labels:
        looks_editable = bool(
            re.fullmatch(r"\(?\d{2}\)?\s*\d{4,5}\s*-\s*\d{4}", value)
        )
    elif normalized_label in allowed_plain_labels:
        # Short human-readable defaults such as ``Diretoria Administrativa``
        # are useful placeholders. Avoid values that look like sentences.
        looks_editable = (
            len(value) <= 60
            and not value.endswith((".", ";"))
            and len(value.split()) <= 6
            and not CHECKBOX_TOKEN_PATTERN.search(value)
        )

    if not looks_editable:
        return None

    field_id = _unique_field_id(_make_field_id(label), known_ids)
    return _candidate(
        field_id=field_id,
        label=label,
        field_type=suggest_field_type(label),
        confidence=0.88 if explicit_label else 0.85,
        source="sample_value",
        preview=value,
        location={
            "kind": "text_span",
            "paragraph": value_record.ordinal,
            "start": 0,
            "end": len(value_record.text),
            "original": value_record.text,
        },
        placeholder=value,
    )


def _detect_label_only_field(
    record: _ParagraphRecord,
    records: list[_ParagraphRecord],
    known_ids: set[str],
) -> dict[str, Any] | None:
    text = _normalize_space(record.text)
    if (
        not text.endswith(":")
        or record.cell is None
        or len(record.cell.paragraphs) != 1
        or _contains_authoritative_marker(record.paragraph)
    ):
        return None
    label = _clean_label(text)
    if not _is_reasonable_label(label, maximum=100):
        return None
    if _looks_like_section_label(text) and SECTION_NUMBER_PATTERN.match(text):
        return None

    # A bare label can represent a fill area inside its own cell (for example
    # ``Responsável legal:``), but a very common Word grid stores the label in
    # one cell and the actual mask/value in the immediately following cell. In
    # that case the following cell owns the field and creating another tag in
    # the label cell causes duplicate inputs and staircase layouts.
    has_form_neighbor = False
    if record.table is not None and record.row_index is not None:
        try:
            unique_cells = _unique_row_cells(record.table.rows[record.row_index])
            current_index = next(
                (
                    index
                    for index, cell in enumerate(unique_cells)
                    if id(cell._tc) == id(record.cell._tc)
                ),
                -1,
            )
            if current_index >= 0 and current_index + 1 < len(unique_cells):
                immediate_text = _normalize_space(unique_cells[current_index + 1].text)
                if not immediate_text:
                    return None
                if _is_pure_fill_area_text(immediate_text):
                    return None

            for cell in unique_cells:
                if id(cell._tc) == id(record.cell._tc):
                    continue
                neighbor = _normalize_space(cell.text)
                if not neighbor:
                    return None
                if _looks_like_fill_area_text(neighbor):
                    has_form_neighbor = True
                    break
        except (IndexError, AttributeError):
            pass
    if not has_form_neighbor:
        return None

    field_id = _unique_field_id(_make_field_id(label), known_ids)
    return _candidate(
        field_id=field_id,
        label=label,
        field_type=suggest_field_type(label),
        confidence=0.82,
        source="empty_cell",
        preview="Área vazia após o rótulo",
        location={
            "kind": "append_tag",
            "paragraph": record.ordinal,
        },
    )


def _detect_empty_cells(
    document: _Document,
    records: list[_ParagraphRecord],
    known_ids: set[str],
    reserved_ordinals: set[int],
) -> list[dict[str, Any]]:
    del document
    result: list[dict[str, Any]] = []
    by_cell: dict[int, list[_ParagraphRecord]] = defaultdict(list)
    for record in records:
        if record.cell is not None:
            by_cell[id(record.cell._tc)].append(record)

    visited_cells: set[int] = set()
    for record in records:
        if record.cell is None or record.table is None or record.row_index is None or record.cell_index is None:
            continue
        cell_key = id(record.cell._tc)
        if cell_key in visited_cells:
            continue
        visited_cells.add(cell_key)
        cell_records = by_cell.get(cell_key, [])
        if not cell_records or any(item.ordinal in reserved_ordinals for item in cell_records):
            continue
        if any(_normalize_space(item.text) for item in cell_records):
            continue
        if record.cell.tables:
            continue
        if record.cell_index <= 0:
            continue
        try:
            previous_cell = record.table.rows[record.row_index].cells[record.cell_index - 1]
        except (IndexError, AttributeError):
            continue
        previous_text = _normalize_space(previous_cell.text)
        label = previous_text.strip(" :：–—-")
        if not _is_reasonable_label(label):
            continue
        explicit_label = previous_text.rstrip().endswith((":", "："))
        ordinal = cell_records[0].ordinal
        field_id = _unique_field_id(_make_field_id(label), known_ids)
        known_ids.add(field_id)
        result.append(
            _candidate(
                field_id=field_id,
                label=label,
                field_type=suggest_field_type(label),
                confidence=0.84 if explicit_label else 0.68,
                source="empty_cell",
                preview="Célula vazia",
                location={
                    "kind": "empty_cell",
                    "paragraph": ordinal,
                },
                default_selected=explicit_label,
            )
        )
    return result


def _detect_consistency_repair_fields(
    records: list[_ParagraphRecord],
    candidates: list[dict[str, Any]],
    known_ids: set[str],
) -> list[dict[str, Any]]:
    """Suggest a missing sibling field when the surrounding table is consistent.

    This is intentionally a *repair* pass rather than another primary heuristic.
    It only fires when at least two peer rows already establish that the same
    visual column is editable. This helps arbitrary user-made matrices where one
    row uses a slightly different blank representation without requiring a fixed
    document template.
    """

    by_ordinal = {record.ordinal: record for record in records}
    occupied_cells: set[tuple[int, int, int]] = set()
    column_rows: dict[tuple[int, int], set[int]] = defaultdict(set)
    repeatable_tables: set[int] = set()

    for candidate in candidates:
        location = candidate.get("location", {}) or {}
        if str(candidate.get("source", "")) == "repeatable_table":
            try:
                repeatable_tables.add(int(location.get("table_index", -1)))
            except (TypeError, ValueError):
                pass
        ordinals: list[int] = []
        if "paragraph" in location:
            try:
                ordinals.append(int(location.get("paragraph", -1)))
            except (TypeError, ValueError):
                pass
        for value in location.get("paragraphs", []) or []:
            try:
                ordinals.append(int(value))
            except (TypeError, ValueError):
                continue
        for ordinal in ordinals:
            record = by_ordinal.get(ordinal)
            if (
                record is None
                or record.table_index is None
                or record.row_index is None
                or record.cell_index is None
            ):
                continue
            key = (int(record.table_index), int(record.row_index), int(record.cell_index))
            occupied_cells.add(key)
            column_rows[(key[0], key[2])].add(key[1])

    established_columns = {
        key for key, rows in column_rows.items()
        if len(rows) >= 2 and key[0] not in repeatable_tables
    }
    if not established_columns:
        return []

    by_cell: dict[tuple[int, int, int], list[_ParagraphRecord]] = defaultdict(list)
    for record in records:
        if (
            record.table_index is None
            or record.row_index is None
            or record.cell_index is None
        ):
            continue
        by_cell[(int(record.table_index), int(record.row_index), int(record.cell_index))].append(record)

    result: list[dict[str, Any]] = []
    for (table_index, row_index, cell_index), cell_records in by_cell.items():
        if (table_index, cell_index) not in established_columns:
            continue
        if (table_index, row_index, cell_index) in occupied_cells:
            continue
        if any(_contains_authoritative_marker(record.paragraph) for record in cell_records):
            continue

        texts = [record.text or "" for record in cell_records]
        combined = _normalize_space(" ".join(texts))
        if combined and not all(_is_pure_fill_area_text(text) for text in texts):
            continue

        target = next((record for record in cell_records if record.paragraph is not None), None)
        if target is None:
            continue
        label, label_source, label_confidence = semantic_label(target)
        if not label or label_confidence < 0.74 or label_source == "section_fallback":
            continue

        field_id = _unique_field_id(_make_field_id(label), known_ids)
        known_ids.add(field_id)
        preview = combined or "área vazia"
        field_type = _detected_placeholder_type(label, combined)
        result.append(
            _candidate(
                field_id=field_id,
                label=label,
                field_type=field_type,
                confidence=0.68,
                source="consistency_repair",
                preview=preview,
                location={
                    "kind": "empty_cell" if not combined else "paragraph",
                    "paragraph": target.ordinal,
                    "repair_basis": "peer_column",
                    "table_index": table_index,
                    "row_index": row_index,
                    "cell_index": cell_index,
                },
                default_selected=False,
            )
        )

    return result


def _detect_terminal_prompt(
    record: _ParagraphRecord,
    records: list[_ParagraphRecord],
    known_ids: set[str],
    structure,
) -> dict[str, Any] | None:
    """Detect the final prompt after an instructional block.

    Institutional forms often put several note paragraphs and the actual input
    prompt in the same merged Word cell.  There may be no blank cell or visual
    placeholder after the prompt, so a placeholder-only detector misses the
    entire numbered section.  The prompt is preserved and the accepted tag is
    appended after it rather than replacing the printed label.
    """

    from app.document.detection.field_inference import infer_field_type
    from app.document.detection.roles import terminal_prompt_score

    if _contains_authoritative_marker(record.paragraph):
        return None
    score, reasons = terminal_prompt_score(record, records, structure)
    if score < 0.65:
        return None

    label = _clean_label(record.text)
    if not _is_reasonable_label(label, maximum=190):
        return None
    owner = structure.owner_for(record.ordinal) if structure is not None else None
    section = owner.section if owner is not None else ""
    inference = infer_field_type(label, section=section, preview=record.text)
    field_id = _unique_field_id(_make_field_id(label), known_ids)
    candidate = _candidate(
        field_id=field_id,
        label=label,
        field_type=inference.field_type,
        confidence=min(0.96, max(score, inference.confidence * 0.88)),
        source="terminal_prompt",
        preview=record.text,
        location={
            "kind": "append_tag",
            "paragraph": record.ordinal,
        },
    )
    if section:
        candidate["section"] = section
    candidate["terminal_prompt_reasons"] = reasons
    candidate["type_inference"] = {
        "confidence": inference.confidence,
        "reasons": list(inference.reasons),
    }
    return candidate


def _detect_colored_prompt(
    record: _ParagraphRecord,
    records: list[_ParagraphRecord],
    known_ids: set[str],
) -> dict[str, Any] | None:
    """Detect short colored placeholders such as ``Nome`` / ``Matrícula``.

    Some institutional DOCX files use red words as the fill target itself
    rather than ``XXXX`` or an underscore.  We require a short field-like
    token and strong structural context so ordinary colored instructions stay
    static.
    """

    from app.document.detection.field_inference import infer_field_type
    from app.document.detection.identifiers import _unique_contextual_field_id

    text = _normalize_space(record.text)
    if (
        not text
        or len(text) > 70
        or not _paragraph_is_red(record.paragraph)
        or _contains_authoritative_marker(record.paragraph)
    ):
        return None
    role = str(getattr(getattr(record, "understanding", None), "role", "") or "")
    if role in {"note", "heading", "table_header", "table_reference", "tagged"}:
        return None

    semantic, _source, semantic_confidence = semantic_label(record)
    owner = getattr(record, "structure", None)
    section = str(getattr(owner, "section", "") or semantic_section(record) or "")
    normalized = _slug(text)
    field_words = {
        "nome", "nome_completo", "cargo", "matricula", "setor", "lotacao", "funcao",
        "cpf", "cnpj", "email", "e_mail", "telefone", "celular", "cep", "cidade", "uf",
        "data", "valor", "quantidade", "descricao", "observacao", "justificativa",
    }
    if normalized not in field_words:
        return None

    table_kind = str(getattr(owner, "table_kind", "") or "")
    label = (
        semantic
        if table_kind in {"fixed_form", "repeatable", "editable_sheet"}
        and semantic and semantic_confidence >= 0.75
        else _clean_label(text)
    )
    semantics = getattr(record, "understanding", None)
    row_label = str(getattr(semantics, "row_label", "") or "")
    column_label = str(getattr(semantics, "column_label", "") or "")
    field_id = _unique_contextual_field_id(
        label,
        known_ids,
        section=section,
        row_label=row_label,
        column_label=column_label,
    )
    inference = infer_field_type(label, section=section, preview=text)
    candidate = _candidate(
        field_id=field_id,
        label=label,
        field_type=inference.field_type,
        confidence=0.91 if semantic_confidence >= 0.80 else 0.83,
        source="colored_prompt",
        preview=text,
        location={
            "kind": "paragraph",
            "paragraph": record.ordinal,
        },
    )
    if section:
        candidate["section"] = section
    candidate["type_inference"] = {
        "confidence": inference.confidence,
        "reasons": list(inference.reasons),
    }
    return candidate
