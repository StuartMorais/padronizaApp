from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from app.document.detection.detector import (
    clear_detection_cache,
    detect_docx_with_report,
)
from app.document.detection.models import (
    AutomaticDetectionCancelled,
    AutomaticDetectionError,
)
from app.document.docx.repair import repair_repeatable_table_markers
from app.document.docx.scanner import clear_docx_scan_cache
from app.document.understanding.smart_template import smart_fields_from_docx
from app.repositories.semantic_learning import SemanticLearningStore


@dataclass(frozen=True)
class TemplateScanResult:
    """Complete, UI-independent result of one template localization pass.

    ``fields`` are authoritative fields already represented by Padroniza tags,
    native Word/PDF controls, or editor metadata. ``candidates`` are additional
    untagged areas that require the review-first detection policy before they
    are inserted into the working DOCX.
    """

    fields: tuple[dict[str, Any], ...]
    candidates: tuple[dict[str, Any], ...]
    report: dict[str, Any]
    repaired_marker_count: int = 0

    def field_list(self) -> list[dict[str, Any]]:
        return [deepcopy(field) for field in self.fields]

    def candidate_list(self) -> list[dict[str, Any]]:
        return [deepcopy(candidate) for candidate in self.candidates]

    @property
    def preselected_candidate_count(self) -> int:
        return sum(bool(candidate.get("selected", False)) for candidate in self.candidates)

    @property
    def review_candidate_count(self) -> int:
        return len(self.candidates) - self.preselected_candidate_count


def locate_template_fields(
    source: Path,
    *,
    existing_fields: Iterable[dict[str, Any]] | None = None,
    source_field_hints: Iterable[dict[str, Any]] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    repair_repeatable_markers: bool = True,
    semantic_data_dir: Path | None = None,
    semantic_enabled: bool = True,
) -> TemplateScanResult:
    """Locate every supported field representation in one scanner pipeline.

    The public UI should call this operation rather than asking users to choose
    between "scan tags" and "detect untagged fields". Internally the phases stay
    intentionally separate:

    1. repair only structurally unambiguous legacy repeat markers;
    2. locate authoritative tags/native controls and enrich their metadata;
    3. discover additional untagged candidates without modifying the document;
    4. attach the structural report and review-first selection state.

    This keeps one simple user action while preserving independently testable
    detector layers underneath it.
    """

    path = Path(source).expanduser().resolve()
    if not path.exists() or not path.is_file() or path.suffix.casefold() != ".docx":
        raise AutomaticDetectionError("Selecione um arquivo DOCX válido.")

    _raise_if_cancelled(cancel_check)

    repaired_marker_count = 0
    if repair_repeatable_markers:
        repair_result = repair_repeatable_table_markers(path)
        repaired_marker_count = repair_result.marker_count
        if repair_result.changed:
            # The source bytes changed; invalidate both scanner layers before
            # continuing so neither one can reuse the pre-repair document.
            clear_docx_scan_cache()
            clear_detection_cache()

    _raise_if_cancelled(cancel_check)

    seeded_existing = [
        *[
            deepcopy(field)
            for field in (source_field_hints or [])
            if isinstance(field, dict)
        ],
        *[
            deepcopy(field)
            for field in (existing_fields or [])
            if isinstance(field, dict)
        ],
    ]
    fields = smart_fields_from_docx(path, seeded_existing)

    _raise_if_cancelled(cancel_check)

    field_ids = {
        str(field.get("id", "")).strip()
        for field in fields
        if str(field.get("id", "")).strip()
    }
    semantic_memory = (
        SemanticLearningStore(semantic_data_dir).snapshot()
        if semantic_enabled and semantic_data_dir is not None
        else None
    )
    candidates, report = detect_docx_with_report(
        path,
        existing_field_ids=field_ids,
        existing_fields=fields,
        cancel_check=cancel_check,
        semantic_memory=semantic_memory,
        semantic_enabled=semantic_enabled,
    )

    _raise_if_cancelled(cancel_check)

    return TemplateScanResult(
        fields=tuple(deepcopy(field) for field in fields),
        candidates=tuple(deepcopy(candidate) for candidate in candidates),
        report=deepcopy(report.as_dict()),
        repaired_marker_count=repaired_marker_count,
    )


def _raise_if_cancelled(cancel_check: Callable[[], bool] | None) -> None:
    if cancel_check is not None and bool(cancel_check()):
        raise AutomaticDetectionCancelled("Detecção cancelada pelo usuário.")


def record_semantic_reviews(
    data_dir: Path,
    reviews: Iterable[dict[str, Any]],
) -> int:
    """Persist reviewed semantic suggestions for future template-family scans."""

    prepared = [deepcopy(item) for item in reviews if isinstance(item, dict)]
    if not prepared:
        return 0
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in prepared:
        family = str(item.get("family_fingerprint", "") or "")
        document = str(item.get("document_fingerprint", "") or "")
        if not family or not str(item.get("location_signature", "") or ""):
            continue
        groups.setdefault((family, document), []).append(item)
    store = SemanticLearningStore(Path(data_dir))
    count = 0
    for (family, document), items in groups.items():
        store.record_reviews(
            items,
            family_fingerprint=family,
            document_fingerprint=document,
        )
        count += len(items)
    return count
