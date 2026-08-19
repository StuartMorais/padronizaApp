from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Iterable

from docx import Document

from app.document.detection.candidates import _candidate
from app.document.detection.checkboxes import (
    _detect_checkbox_choice_groups,
    _detect_standalone_checkboxes,
)
from app.document.detection.context_helpers import (
    _contains_authoritative_marker,
    _context_label_for_record,
    _is_instruction_candidate,
    _paragraph_is_red,
)
from app.document.detection.identifiers import (
    _instruction_label,
    _make_field_id,
    _normalize_space,
    _slug,
    _unique_field_id,
)
from app.document.detection.models import AutomaticDetectionCancelled, AutomaticDetectionError
from app.document.detection.records import _collect_paragraph_records
from app.document.detection.tables import (
    _detect_editable_sheet_tables,
    _detect_long_choice_blocks,
    _detect_repeatable_tables,
)
from app.document.detection.text_fields import (
    _detect_adjacent_sample_value,
    _detect_blank_followup_areas,
    _detect_consistency_repair_fields,
    _detect_dropdown_prompt,
    _detect_empty_cells,
    _detect_inline_placeholders,
    _detect_label_only_field,
    _detect_labeled_instruction,
    _detect_labeled_sample_value,
    _detect_prefilled_written_text,
)
from app.document.docx.scanner import scan_docx_fields
from app.document.understanding.semantic import annotate_document_records, postprocess_candidates
from app.document.understanding.smart_template import suggest_field_type


_DETECTION_CACHE_MAXSIZE = 16
_DETECTION_CACHE: OrderedDict[tuple[Any, ...], list[dict[str, Any]]] = OrderedDict()


def clear_detection_cache() -> None:
    """Clear assisted-detection results cached for unchanged source files."""

    _DETECTION_CACHE.clear()


def _detection_cache_key(
    path: Path,
    existing_field_ids: Iterable[str] | None,
    existing_fields: Iterable[dict[str, Any]] | None,
) -> tuple[Any, ...]:
    stat = path.stat()
    ids = tuple(
        sorted(
            {
                str(value).strip()
                for value in (existing_field_ids or [])
                if str(value).strip()
            }
        )
    )
    field_context = tuple(
        sorted(
            (
                str(field.get("id", "")).strip(),
                str(field.get("label", "")).strip(),
                str(field.get("section", "")).strip(),
                str(field.get("detection_source", "")).strip(),
            )
            for field in (existing_fields or [])
            if isinstance(field, dict)
        )
    )
    return (
        str(path.resolve()),
        int(stat.st_mtime_ns),
        int(stat.st_size),
        ids,
        field_context,
    )


def _cached_detection(key: tuple[Any, ...]) -> list[dict[str, Any]] | None:
    cached = _DETECTION_CACHE.get(key)
    if cached is None:
        return None
    _DETECTION_CACHE.move_to_end(key)
    return deepcopy(cached)


def _store_detection_cache(
    key: tuple[Any, ...],
    candidates: list[dict[str, Any]],
) -> None:
    _DETECTION_CACHE[key] = deepcopy(candidates)
    _DETECTION_CACHE.move_to_end(key)
    while len(_DETECTION_CACHE) > _DETECTION_CACHE_MAXSIZE:
        _DETECTION_CACHE.popitem(last=False)


def _raise_if_cancelled(cancel_check: Callable[[], bool] | None) -> None:
    if cancel_check is not None and bool(cancel_check()):
        raise AutomaticDetectionCancelled("Detecção cancelada pelo usuário.")


def detect_docx_field_candidates(
    docx_path: Path,
    *,
    existing_field_ids: Iterable[str] | None = None,
    existing_fields: Iterable[dict[str, Any]] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> list[dict[str, Any]]:
    """Return conservative fill-field suggestions for an untagged DOCX.

    The result is safe to display in a review dialog. It does not modify the
    document. Explicit ``{{tags}}`` and native Word controls are excluded from
    automatic replacement candidates.
    """

    path = Path(docx_path)
    if not path.exists() or not path.is_file() or path.suffix.lower() != ".docx":
        raise AutomaticDetectionError("Selecione um arquivo DOCX válido.")

    _raise_if_cancelled(cancel_check)
    provided_ids = tuple(
        str(field_id).strip()
        for field_id in (existing_field_ids or [])
        if str(field_id).strip()
    )
    provided_fields = tuple(
        dict(field)
        for field in (existing_fields or [])
        if isinstance(field, dict)
    )
    cache_key = _detection_cache_key(path, provided_ids, provided_fields)
    cached = _cached_detection(cache_key)
    if cached is not None:
        _raise_if_cancelled(cancel_check)
        return cached

    document = Document(str(path))
    records = _collect_paragraph_records(document)
    annotate_document_records(records)
    _raise_if_cancelled(cancel_check)
    existing_field_list = [dict(field) for field in provided_fields]
    known_ids = {field_id for field_id in provided_ids if field_id}
    known_ids.update(
        str(field.get("id", "")).strip()
        for field in existing_field_list
        if str(field.get("id", "")).strip()
    )
    _raise_if_cancelled(cancel_check)
    try:
        scanned_existing_fields = [
            dict(field)
            for field in scan_docx_fields(path)
            if isinstance(field, dict)
            and str(field.get("id", "")).strip()
        ]
        known_ids.update(
            str(field.get("id", "")).strip()
            for field in scanned_existing_fields
        )

        # Keep the scanner authoritative even when callers only provide IDs or
        # no existing metadata at all.  Richer editor metadata wins for the
        # same ID; newly scanned explicit/native fields fill the gaps.
        existing_ids = {
            str(field.get("id", "")).strip()
            for field in existing_field_list
            if str(field.get("id", "")).strip()
        }
        for field in scanned_existing_fields:
            field_id = str(field.get("id", "")).strip()
            if field_id not in existing_ids:
                existing_field_list.append(field)
                existing_ids.add(field_id)
        _raise_if_cancelled(cancel_check)
    except AutomaticDetectionCancelled:
        raise
    except Exception:
        # Automatic detection should still be usable when an unrelated
        # malformed native control exists. The normal scanner will report
        # that issue before the model can be saved.
        pass

    candidates: list[dict[str, Any]] = []
    reserved_ordinals: set[int] = set()

    _raise_if_cancelled(cancel_check)
    long_choices = _detect_long_choice_blocks(
        document,
        records,
        known_ids,
    )
    for candidate in long_choices:
        candidates.append(candidate)
        reserved_ordinals.update(
            int(value)
            for value in candidate.get("location", {}).get("paragraphs", [])
        )
        known_ids.add(str(candidate.get("field_id", "")))

    _raise_if_cancelled(cancel_check)
    repeatable_tables = _detect_repeatable_tables(
        document,
        records,
        known_ids,
        reserved_ordinals,
    )
    for candidate in repeatable_tables:
        candidates.append(candidate)
        reserved_ordinals.update(
            int(value)
            for value in candidate.get("location", {}).get("paragraphs", [])
        )
        known_ids.add(str(candidate.get("field_id", "")))

    _raise_if_cancelled(cancel_check)
    editable_sheets = _detect_editable_sheet_tables(
        document,
        records,
        known_ids,
        reserved_ordinals,
    )
    for candidate in editable_sheets:
        candidates.append(candidate)
        reserved_ordinals.update(
            int(value)
            for value in candidate.get("location", {}).get("paragraphs", [])
        )
        known_ids.add(str(candidate.get("field_id", "")))

    _raise_if_cancelled(cancel_check)
    checkbox_choices = _detect_checkbox_choice_groups(
        document,
        records,
        known_ids,
        reserved_ordinals,
    )
    for candidate in checkbox_choices:
        candidates.append(candidate)
        reserved_ordinals.update(
            int(value)
            for value in candidate.get("location", {}).get("paragraphs", [])
        )
        for field in candidate.get("fields", []) or []:
            known_ids.add(str(field.get("id", "")))

    _raise_if_cancelled(cancel_check)
    single_checkboxes = _detect_standalone_checkboxes(
        records,
        known_ids,
        reserved_ordinals,
    )
    for candidate in single_checkboxes:
        candidates.append(candidate)
        reserved_ordinals.add(int(candidate.get("location", {}).get("paragraph", -1)))
        known_ids.add(str(candidate.get("field_id", "")))

    _raise_if_cancelled(cancel_check)
    followup_areas = _detect_blank_followup_areas(
        records,
        known_ids,
        reserved_ordinals,
    )
    for candidate in followup_areas:
        candidates.append(candidate)
        known_ids.add(str(candidate.get("field_id", "")))

    for record in records:
        _raise_if_cancelled(cancel_check)
        if record.ordinal in reserved_ordinals:
            continue
        if _contains_authoritative_marker(record.paragraph):
            continue

        dropdown_prompt = _detect_dropdown_prompt(
            record,
            records,
            known_ids,
        )
        if dropdown_prompt is not None:
            candidates.append(dropdown_prompt)
            known_ids.add(str(dropdown_prompt.get("field_id", "")))
            continue

        sample_value = _detect_labeled_sample_value(
            record,
            known_ids,
        )
        if sample_value is not None:
            candidates.append(sample_value)
            known_ids.add(str(sample_value.get("field_id", "")))
            continue

        labeled_instruction = _detect_labeled_instruction(
            record,
            known_ids,
        )
        if labeled_instruction is not None:
            candidates.append(labeled_instruction)
            known_ids.add(str(labeled_instruction.get("field_id", "")))
            continue

        inline = _detect_inline_placeholders(
            record,
            records,
            known_ids,
        )
        if inline:
            candidates.extend(inline)
            known_ids.update(str(item.get("field_id", "")) for item in inline)
            continue

        text = _normalize_space(record.text)
        if not text:
            continue

        if _is_instruction_candidate(record):
            label = _context_label_for_record(record, records)
            field_type = "multiline" if len(text) >= 70 else suggest_field_type(label or text)
            if field_type == "text" and len(text) >= 70:
                field_type = "multiline"
            field_id = _unique_field_id(
                _make_field_id(label or text[:60]),
                known_ids,
            )
            known_ids.add(field_id)
            candidates.append(
                _candidate(
                    field_id=field_id,
                    label=label or _instruction_label(text),
                    field_type=field_type,
                    confidence=0.84 if _paragraph_is_red(record.paragraph) else 0.76,
                    source="instruction",
                    preview=text,
                    location={
                        "kind": "paragraph",
                        "paragraph": record.ordinal,
                    },
                )
            )
            continue

        prefilled_text = _detect_prefilled_written_text(
            record,
            records,
            known_ids,
        )
        if prefilled_text is not None:
            candidates.append(prefilled_text)
            known_ids.add(str(prefilled_text.get("field_id", "")))
            continue

        adjacent_sample = _detect_adjacent_sample_value(
            record,
            records,
            known_ids,
        )
        if adjacent_sample is not None:
            candidates.append(adjacent_sample)
            known_ids.add(str(adjacent_sample.get("field_id", "")))
            continue

        label_only = _detect_label_only_field(
            record,
            records,
            known_ids,
        )
        if label_only is not None:
            candidates.append(label_only)
            known_ids.add(str(label_only.get("field_id", "")))

    _raise_if_cancelled(cancel_check)
    candidates.extend(
        _detect_empty_cells(
            document,
            records,
            known_ids,
            reserved_ordinals,
        )
    )

    _raise_if_cancelled(cancel_check)
    candidates.extend(
        _detect_consistency_repair_fields(
            records,
            candidates,
            known_ids,
        )
    )

    source_kind = (
        "pdf_reconstruction"
        if "convertido de pdf" in str(document.core_properties.subject or "").casefold()
        else "docx"
    )
    _raise_if_cancelled(cancel_check)
    candidates = postprocess_candidates(candidates, records, source_kind=source_kind)
    _raise_if_cancelled(cancel_check)
    candidates = _suppress_authoritative_semantic_duplicates(
        candidates,
        existing_field_list,
    )

    _raise_if_cancelled(cancel_check)
    # Stable order keeps the review screen aligned with the source document.
    candidates.sort(
        key=lambda item: (
            _candidate_first_ordinal(item),
            -float(item.get("confidence", 0.0)),
            str(item.get("field_id", "")),
        )
    )
    for index, candidate in enumerate(candidates, start=1):
        candidate["candidate_id"] = f"candidate_{index:04d}"
    _raise_if_cancelled(cancel_check)
    _store_detection_cache(cache_key, candidates)
    return deepcopy(candidates)


def _suppress_authoritative_semantic_duplicates(
    candidates: list[dict[str, Any]],
    existing_fields: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Drop assisted suggestions already owned by authoritative fields.

    Explicit Padroniza tags, native Word/PDF controls and manually configured
    fields are stronger than assisted detection.  This matters especially for
    a Word form laid out as ``Rótulo | {{campo}}``: the empty-cell detector can
    otherwise create ``auto.rotulo`` from the label cell even though the
    adjacent tagged cell already owns the same semantic field.

    Suppression remains conservative.  We primarily match label + section.
    When an authoritative field has no section metadata yet (common while a
    DOCX is first being scanned), label-only ownership is allowed only for a
    unique, non-generic label.
    """

    authoritative: set[tuple[str, str]] = set()
    authoritative_label_counts: dict[str, int] = {}
    sectionless_labels: set[str] = set()
    generic_label_keys = {
        "campo", "data", "nome", "tipo", "valor", "item", "quantidade",
        "descricao", "observacao", "responsavel", "matricula", "situacao",
    }

    for field in existing_fields:
        field_id = str(field.get("id", "")).strip()
        source = str(field.get("detection_source") or "").strip().casefold()

        # Existing assisted fields must not suppress a newer interpretation of
        # the document.  Everything else is authoritative here: explicit tags
        # usually have no detection_source, while native controls identify
        # themselves explicitly.
        is_assisted = source in {"automatic", "assisted", "auto_detection"}
        if not is_assisted and not source and field_id.casefold().startswith("auto."):
            # Defensive compatibility with very old auto-detected models that
            # did not persist detection_source.
            is_assisted = True
        if is_assisted:
            continue

        label_key = _slug(str(field.get("label", "")))
        if not label_key:
            continue
        section_key = _slug(str(field.get("section", "")))
        authoritative.add((label_key, section_key))
        authoritative_label_counts[label_key] = authoritative_label_counts.get(label_key, 0) + 1
        if not section_key:
            sectionless_labels.add(label_key)

    if not authoritative:
        return candidates

    unique_sectionless_labels = {
        label_key
        for label_key in sectionless_labels
        if authoritative_label_counts.get(label_key, 0) == 1
        and label_key not in generic_label_keys
        and len(label_key) >= 6
    }

    result: list[dict[str, Any]] = []
    for candidate in candidates:
        label_keys = {
            key
            for key in (
                _slug(str(candidate.get("label", ""))),
                _slug(str(candidate.get("semantic_label_suggestion", ""))),
            )
            if key
        }
        section_key = _slug(str(candidate.get("section", "")))

        duplicate = any((label_key, section_key) in authoritative for label_key in label_keys)

        # Native/explicit fields can be discovered before section inference has
        # run.  A unique descriptive label is still strong enough to own the
        # semantic field across that short metadata gap.
        if not duplicate and label_keys:
            duplicate = any(label_key in unique_sectionless_labels for label_key in label_keys)

        if duplicate:
            continue
        result.append(candidate)
    return result


def _candidate_first_ordinal(candidate: dict[str, Any]) -> int:
    location = candidate.get("location", {}) or {}
    if "paragraph" in location:
        try:
            return int(location["paragraph"])
        except (TypeError, ValueError):
            return 10**9
    paragraphs = location.get("paragraphs", []) or []
    try:
        return min(int(value) for value in paragraphs)
    except (TypeError, ValueError):
        return 10**9


