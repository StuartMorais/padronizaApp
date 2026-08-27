from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from pathlib import Path
import hashlib
import json
from typing import Any, Callable, Iterable

from docx import Document

from app.document.detection.extraction import build_normalized_document, location_signature
from app.document.detection.identifiers import _slug
from app.document.detection.invariants import apply_candidate_invariants
from app.document.detection.models import AutomaticDetectionCancelled, AutomaticDetectionError
from app.document.detection.passes import (
    DetectionWorkspace,
    run_fallback_detector_passes,
    run_record_detector_passes,
    run_structural_detector_passes,
)
from app.document.detection.records import _collect_paragraph_records
from app.document.detection.selection_policy import apply_review_first_policy
from app.document.detection.structure import StoryZone, TableKind, extract_document_structure
from app.document.docx.scanner import scan_docx_fields
from app.document.understanding.semantic import annotate_document_records, postprocess_candidates
from app.document.semantic_ai.discovery import discover_semantic_regions
from app.document.semantic_ai.engine import LocalSemanticEngine, SEMANTIC_MODEL_VERSION
from app.document.semantic_ai.integration import enrich_candidates_with_semantic_ai


_DETECTION_CACHE_MAXSIZE = 16
_DETECTION_CACHE: OrderedDict[tuple[Any, ...], list[dict[str, Any]]] = OrderedDict()


def clear_detection_cache() -> None:
    """Clear assisted-detection results cached for unchanged source files."""

    _DETECTION_CACHE.clear()


def _detection_cache_key(
    path: Path,
    existing_field_ids: Iterable[str] | None,
    existing_fields: Iterable[dict[str, Any]] | None,
    semantic_memory: dict[str, Any] | None = None,
    semantic_enabled: bool = True,
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
    memory_payload = json.dumps(semantic_memory or {}, ensure_ascii=False, sort_keys=True, default=str)
    memory_signature = hashlib.sha256(memory_payload.encode("utf-8")).hexdigest()[:20]
    return (
        str(path.resolve()),
        int(stat.st_mtime_ns),
        int(stat.st_size),
        ids,
        field_context,
        bool(semantic_enabled),
        SEMANTIC_MODEL_VERSION if semantic_enabled else 0,
        memory_signature if semantic_enabled else "",
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
    semantic_memory: dict[str, Any] | None = None,
    semantic_enabled: bool = True,
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
    cache_key = _detection_cache_key(
        path, provided_ids, provided_fields, semantic_memory, semantic_enabled
    )
    cached = _cached_detection(cache_key)
    if cached is not None:
        _raise_if_cancelled(cancel_check)
        return cached

    document = Document(str(path))
    records = _collect_paragraph_records(document)
    structure = extract_document_structure(document, records)
    normalized_document = build_normalized_document(path, records, structure)
    semantic_engine = LocalSemanticEngine(semantic_memory) if semantic_enabled else None
    annotate_document_records(records, structure)
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
    # Explicit/manual tags, whole manually-tagged repeatable tables and
    # header/footer stories are authoritative/protected before heuristics run.
    reserved_ordinals: set[int] = set(structure.protected_ordinals)
    reserved_ordinals.update(
        record.ordinal
        for record in records
        if (owner := structure.owner_for(record.ordinal)) is not None
        and owner.zone is not StoryZone.BODY
    )
    # Reference tables and genuinely ambiguous data matrices are preserved for
    # manual review instead of being flattened into unrelated field guesses.
    for table_info in structure.tables:
        if table_info.structure.kind is TableKind.REFERENCE:
            reserved_ordinals.update(table_info.record_ordinals)
        elif (
            table_info.structure.kind is TableKind.UNKNOWN
            and len(table_info.structure.data_rows) >= 2
            and table_info.structure.total_columns >= 3
        ):
            reserved_ordinals.update(table_info.record_ordinals)

    workspace = DetectionWorkspace(
        document=document,
        records=records,
        structure=structure,
        known_ids=known_ids,
        reserved_ordinals=reserved_ordinals,
        candidates=candidates,
    )
    check_cancel = lambda: _raise_if_cancelled(cancel_check)
    run_structural_detector_passes(workspace, check_cancel)
    run_record_detector_passes(workspace, check_cancel)
    run_fallback_detector_passes(workspace, check_cancel)
    if semantic_engine is not None:
        check_cancel()
        workspace.candidates.extend(
            discover_semantic_regions(
                records,
                known_ids,
                engine=semantic_engine,
                family_fingerprint=normalized_document.family_fingerprint,
                reserved_ordinals=reserved_ordinals,
            )
        )
    candidates = workspace.candidates

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
    for candidate in candidates:
        location = dict(candidate.get("location", {}) or {})
        candidate["document_fingerprint"] = normalized_document.source_fingerprint
        candidate["family_fingerprint"] = normalized_document.family_fingerprint
        candidate["location_signature"] = location_signature(location)
    if semantic_engine is not None:
        candidates = enrich_candidates_with_semantic_ai(
            candidates,
            records,
            engine=semantic_engine,
            family_fingerprint=normalized_document.family_fingerprint,
        )
    candidates, invariant_issues = apply_candidate_invariants(candidates, structure)
    if invariant_issues:
        issue_payload = [
            {
                "severity": issue.severity,
                "code": issue.code,
                "message": issue.message,
                "field_id": issue.field_id,
            }
            for issue in invariant_issues
        ]
        for candidate in candidates:
            candidate["scanner_invariant_issues"] = [
                dict(issue) for issue in issue_payload
                if not issue.get("field_id") or issue.get("field_id") == candidate.get("field_id")
            ]

    # Discovery is intentionally broader than automatic application.  Only
    # candidates whose evidence dimensions agree are preselected; ambiguous
    # findings stay visible for human confirmation instead of changing the DOCX.
    candidates = apply_review_first_policy(candidates)

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
    paragraphs = list(location.get("paragraphs", []) or [])
    if not paragraphs and str(location.get("kind", "")) == "text_spans":
        paragraphs = [
            span.get("paragraph")
            for span in location.get("spans", []) or []
            if isinstance(span, dict)
        ]
    try:
        return min(int(value) for value in paragraphs)
    except (TypeError, ValueError):
        return 10**9




def detect_docx_with_report(
    docx_path: Path,
    *,
    existing_field_ids: Iterable[str] | None = None,
    existing_fields: Iterable[dict[str, Any]] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    semantic_memory: dict[str, Any] | None = None,
    semantic_enabled: bool = True,
):
    """Return candidates plus a structural review report for the UI."""

    from app.document.detection.report import build_detection_report

    candidates = detect_docx_field_candidates(
        docx_path,
        existing_field_ids=existing_field_ids,
        existing_fields=existing_fields,
        cancel_check=cancel_check,
        semantic_memory=semantic_memory,
        semantic_enabled=semantic_enabled,
    )
    _raise_if_cancelled(cancel_check)
    report = build_detection_report(Path(docx_path), candidates)
    return candidates, report
