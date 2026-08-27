from __future__ import annotations

"""Flexible document-understanding helpers used by assisted field detection.

This module intentionally separates *what is physically present* in a document
from *what Padroniza thinks it means*.  The DOCX/PDF adapters can keep their own
parsing details while the detector consumes the same relationship/evidence
model.
"""

from dataclasses import dataclass, field
import re
import unicodedata
from typing import Any, Iterable

from app.document.detection.structure import SCANNER_STRUCTURE_VERSION, is_numbered_section_heading


_GENERIC_LABEL_RE = re.compile(r"^(?:campo|field)\s*\d+$", re.IGNORECASE)
_CHECKBOX_TEXT_RE = re.compile(r"(?:☐|□|☑|☒|\(\s*\))")
_FILL_RE = re.compile(
    r"^(?:_+|X{4,}|x{4,}|R\$\s*_+|\(?\s*\d{0,2}\s*\)?\s*[_0Xx.-]+|"
    r"(?:escolher|selecione|selecionar)\s+(?:um|uma)\s+(?:item|op[cç][aã]o)\.?)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Evidence:
    code: str
    weight: float
    description: str


@dataclass
class RecordSemantics:
    section: str = ""
    label: str = ""
    label_source: str = ""
    label_confidence: float = 0.0
    row_label: str = ""
    column_label: str = ""
    role: str = "content"
    evidence: list[Evidence] = field(default_factory=list)


def annotate_document_records(records: list[Any], structure=None) -> None:
    """Annotate paragraph-like records with relationship-based semantics.

    ``records`` are deliberately duck-typed.  Today they are DOCX paragraph
    records, but the scoring model only relies on common physical properties
    such as document order, table row/column and visible text.
    """

    current_section = ""
    for record in records:
        text = _space(getattr(record, "text", ""))
        if structure is not None:
            owner = structure.owner_for(getattr(record, "ordinal", -1))
            resolved_section = owner.section if owner is not None else ""
        else:
            if _is_section_text(text):
                current_section = text.rstrip(":").strip()
            resolved_section = current_section
        semantics = RecordSemantics(section=resolved_section)
        _set_semantics(record, semantics)

    for index, record in enumerate(records):
        semantics = _get_semantics(record)
        text = str(getattr(record, "text", "") or "")
        normalized = _space(text)

        # 1. The strongest label is printed in the same physical text block.
        if ":" in text:
            before = _clean_label(text.split(":", 1)[0])
            if _reasonable_label(before):
                _consider_label(
                    semantics,
                    before,
                    "same_text",
                    0.98,
                    "Rótulo antes de ':' no mesmo bloco.",
                )

        # 2. A previous paragraph in the same Word cell is usually the local
        # prompt for a blank/instruction paragraph below it.
        cell = getattr(record, "cell", None)
        if cell is not None:
            cell_key = id(getattr(cell, "_tc", cell))
            for previous in reversed(records[:index]):
                previous_cell = getattr(previous, "cell", None)
                if previous_cell is None or id(getattr(previous_cell, "_tc", previous_cell)) != cell_key:
                    continue
                value = _space(getattr(previous, "text", ""))
                if not value or _looks_like_fill(value):
                    continue
                cleaned = _clean_label(value)
                if _reasonable_label(cleaned, maximum=150):
                    confidence = 0.93 if value.endswith((":", "：")) else 0.84
                    _consider_label(
                        semantics,
                        cleaned,
                        "same_cell_previous",
                        confidence,
                        "Texto anterior na mesma célula.",
                    )
                    break

        # 3. In common form grids the closest cell on the left is the label
        # for this value cell (Label | Value | Label | Value). This relation
        # is stronger than a generic row identity and does not assume a fixed
        # number of columns.
        adjacent_left = _adjacent_left_label(record)
        owner = getattr(record, "structure", None)
        structural_table_kind = str(getattr(owner, "table_kind", "") or "")
        # In matrix/data tables, the cell on the left is another value column,
        # not a label/value pair. Prefer row + column axes there. The adjacent
        # cell rule remains strongest for layout tables used as ordinary forms.
        if adjacent_left and structural_table_kind not in {
            "fixed_form", "repeatable", "editable_sheet", "reference"
        }:
            _consider_label(
                semantics,
                adjacent_left,
                "adjacent_left",
                0.97,
                "Rótulo na célula imediatamente à esquerda.",
            )

        # 4. Resolve row and column axes.  This works for arbitrary form grids
        # and matrices without requiring a particular number of columns.
        row_label, column_label = _table_axes(record)
        semantics.row_label = row_label
        semantics.column_label = column_label
        if row_label and _CHECKBOX_TEXT_RE.search(normalized):
            _consider_label(
                semantics,
                row_label,
                "row_label",
                0.94,
                "Grupo de escolha usa o item da própria linha como pergunta.",
            )
        elif row_label and column_label and _slug(row_label) != _slug(column_label):
            _consider_label(
                semantics,
                f"{row_label} — {column_label}",
                "row_and_column",
                0.88,
                "Rótulos de linha e coluna convergem para a mesma área.",
            )
        elif column_label:
            _consider_label(
                semantics,
                column_label,
                "column_header",
                0.80,
                "Cabeçalho da coluna acima da área.",
            )
        elif row_label:
            _consider_label(
                semantics,
                row_label,
                "row_label",
                0.82,
                "Rótulo da mesma linha antes da área.",
            )

        # 4. The nearest previous non-section text outside a table is useful,
        # but intentionally weaker than local/table relationships.
        if not semantics.label or semantics.label_confidence < 0.75:
            for previous in reversed(records[:index]):
                value = _space(getattr(previous, "text", ""))
                if not value or _looks_like_fill(value):
                    continue
                cleaned = _clean_label(value)
                if _is_section_text(value):
                    break
                if _reasonable_label(cleaned, maximum=120):
                    _consider_label(
                        semantics,
                        cleaned,
                        "nearby_previous",
                        0.58,
                        "Texto anterior próximo no fluxo do documento.",
                    )
                break

        # A section heading is context, not a normal field label.  Use it only
        # as a last-resort hint and keep confidence low so the review UI flags it.
        if not semantics.label and semantics.section:
            semantics.label = _clean_label(semantics.section)
            semantics.label_source = "section_fallback"
            semantics.label_confidence = 0.35
            semantics.evidence.append(
                Evidence("section_fallback", -0.05, "Título da seção usado apenas como fallback.")
            )

        if structure is not None:
            from app.document.detection.roles import classify_record_role
            semantics.role = classify_record_role(record, records, structure).value
        else:
            semantics.role = _infer_record_role(normalized, semantics)
        _set_semantics(record, semantics)


def semantic_label(record: Any) -> tuple[str, str, float]:
    semantics = _get_semantics(record)
    return semantics.label, semantics.label_source, float(semantics.label_confidence)


def semantic_section(record: Any) -> str:
    return _get_semantics(record).section


def postprocess_candidates(
    candidates: Iterable[dict[str, Any]],
    records: list[Any],
    *,
    source_kind: str = "docx",
) -> list[dict[str, Any]]:
    """Score, explain and deduplicate interpretations produced by heuristics.

    High-level structures own their physical source region.  This prevents the
    same Word cells from becoming both, for example, a repeatable table and a
    set of ordinary fields/static cards.
    """

    by_ordinal = {int(getattr(record, "ordinal", -1)): record for record in records}
    candidates = _resolve_region_ownership(list(candidates))
    prepared: list[dict[str, Any]] = []

    for raw in candidates:
        candidate = dict(raw)
        location = dict(candidate.get("location", {}) or {})
        ordinal = _first_location_ordinal(location)
        record = by_ordinal.get(ordinal)
        semantics = _get_semantics(record) if record is not None else RecordSemantics()

        evidences: list[Evidence] = []
        original_confidence = _clamp(float(candidate.get("confidence", 0.0)))
        evidences.append(
            Evidence("heuristic", original_confidence - 0.5, "Sinal encontrado pelo detector especializado.")
        )

        label = _space(candidate.get("label", ""))
        if semantics.section and not candidate.get("section"):
            candidate["section"] = semantics.section

        if semantics.label:
            candidate["semantic_label_suggestion"] = semantics.label
            candidate["semantic_label_source"] = semantics.label_source
            candidate["semantic_label_confidence"] = semantics.label_confidence
            if _labels_equivalent(label, semantics.label):
                evidences.append(
                    Evidence("label_agreement", 0.10, "Rótulo concorda com o contexto físico do documento.")
                )
            elif semantics.label_confidence >= 0.85 and _poor_label(label):
                candidate["label"] = semantics.label
                label = semantics.label
                evidences.append(
                    Evidence("label_repaired", 0.08, "Rótulo fraco substituído por contexto local mais forte.")
                )
            elif semantics.label_confidence >= 0.90 and not _labels_equivalent(label, semantics.label):
                # Two strong but different interpretations are a review signal,
                # not a reason to silently overwrite a usable detector label.
                evidences.append(
                    Evidence(
                        "label_disagreement",
                        -0.06,
                        "O rótulo encontrado pelo detector difere do contexto local forte.",
                    )
                )

        if semantics.label_source in {"same_text", "same_cell_previous", "adjacent_left", "row_label", "row_and_column"}:
            evidences.append(Evidence("local_context", 0.07, "Campo possui contexto local forte."))
        elif semantics.label_source == "section_fallback" and (
            _poor_label(label) or _labels_equivalent(label, semantics.section)
        ):
            evidences.append(Evidence("section_only", -0.18, "Somente o título da seção explica este campo."))

        field_type = str(candidate.get("type", "text") or "text")
        preview = _space(candidate.get("preview", ""))
        if _type_has_semantic_support(field_type, label, preview):
            evidences.append(Evidence("type_support", 0.05, "Formato visual e tipo do campo são compatíveis."))

        source = str(candidate.get("source", ""))
        if source == "terminal_prompt":
            evidences.append(
                Evidence(
                    "terminal_prompt",
                    0.06,
                    "Prompt final após bloco de notas/instruções foi reconhecido como área de preenchimento.",
                )
            )
        elif source == "colored_prompt":
            evidences.append(
                Evidence(
                    "formatting_prompt",
                    0.04,
                    "Texto curto destacado por formatação coincide com um rótulo típico de preenchimento.",
                )
            )
        elif source == "colored_inline_choice":
            evidences.append(
                Evidence(
                    "colored_choice",
                    0.07,
                    "Trecho colorido dentro de texto fixo contém alternativas explícitas separadas por OU.",
                )
            )
        elif source == "inline_placeholder":
            evidences.append(
                Evidence(
                    "placeholder_pattern",
                    0.05,
                    "Máscara/placeholder visual aparece ao lado de um rótulo local.",
                )
            )
        if source in {"checkbox_choice", "long_choice", "repeatable_table", "repeatable_list"}:
            evidences.append(Evidence("group_structure", 0.06, "Vários elementos formam uma estrutura coerente."))
        if candidate.get("region_owner"):
            evidences.append(
                Evidence(
                    "region_ownership",
                    0.04,
                    "Estrutura de nível superior possui esta região física do documento.",
                )
            )
        if location.get("kind") in {"empty_cell", "checkbox_group_multi_cell", "repeatable_table"}:
            evidences.append(Evidence("spatial_structure", 0.05, "Relação de célula/linha reforça a interpretação."))

        if _poor_label(label):
            evidences.append(Evidence("poor_label", -0.30, "Rótulo genérico ou pouco informativo."))
        if source_kind == "pdf_reconstruction":
            # Reconstruction preserves a lot of geometry, but is still an
            # interpretation. Keep borderline cases visibly reviewable.
            evidences.append(Evidence("pdf_reconstruction", -0.02, "Campo veio de reconstrução visual de PDF."))

        delta = sum(e.weight for e in evidences if e.code != "heuristic")
        confidence = _clamp(original_confidence + delta)
        if _poor_label(label):
            confidence = min(confidence, 0.54)

        type_inference = dict(candidate.get("type_inference", {}) or {})
        type_confidence = float(type_inference.get("confidence", 0.0) or 0.0)
        if type_confidence <= 0:
            type_confidence = 0.88 if _type_has_semantic_support(field_type, label, preview) else 0.58
        location_kind = str(location.get("kind", ""))
        structure_confidence = {
            "repeatable_table": 0.99,
            "checkbox_group_multi_cell": 0.96,
            "checkbox_group": 0.94,
            "empty_cell": 0.92,
            "text_span": 0.90,
            "text_spans": 0.90,
            "append_tag": 0.90,
            "paragraph_block": 0.86,
            "paragraph_list": 0.86,
            "paragraph": 0.80,
        }.get(location_kind, 0.72)
        if semantics.section:
            structure_confidence = min(1.0, structure_confidence + 0.04)
        label_confidence = max(
            0.45 if not _poor_label(label) else 0.20,
            float(semantics.label_confidence or 0.0),
        )
        fillable_confidence = original_confidence
        candidate["confidence_dimensions"] = {
            "structure": round(_clamp(structure_confidence), 3),
            "fillable": round(_clamp(fillable_confidence), 3),
            "label": round(_clamp(label_confidence), 3),
            "type": round(_clamp(type_confidence), 3),
        }
        candidate["confidence"] = confidence
        candidate["confidence_band"] = confidence_band(confidence)
        candidate["evidence"] = [
            {"code": e.code, "weight": round(e.weight, 3), "description": e.description}
            for e in evidences
        ]
        candidate["review_reasons"] = [
            e.description for e in evidences if e.weight < 0
        ]
        candidate["detector_version"] = 3
        candidate["scanner_version"] = SCANNER_STRUCTURE_VERSION

        requires_configuration = bool(candidate.get("requires_configuration"))
        poor_label = _poor_label(str(candidate.get("label", "")))
        negative_evidence = bool(candidate["review_reasons"])
        band = str(candidate["confidence_band"])
        if requires_configuration or band == "low" or poor_label:
            review_priority = "required"
        elif band == "medium" or negative_evidence:
            review_priority = "recommended"
        else:
            review_priority = "ready"
        candidate["review_priority"] = review_priority
        candidate["needs_review"] = review_priority != "ready"
        candidate["review_summary"] = {
            "required": "Revisão necessária antes de aplicar.",
            "recommended": "Revisão rápida recomendada.",
            "ready": "Sugestão consistente com os sinais encontrados.",
        }[review_priority]
        candidate["selected"] = bool(
            confidence >= 0.80
            and not requires_configuration
            and not poor_label
        )
        prepared.append(candidate)

    return _deduplicate_candidates(prepared, by_ordinal)


def confidence_band(confidence: float) -> str:
    value = _clamp(confidence)
    if value >= 0.85:
        return "high"
    if value >= 0.65:
        return "medium"
    return "low"


def candidate_explanation(candidate: dict[str, Any]) -> str:
    evidence = candidate.get("evidence", []) or []
    lines = []
    for item in evidence:
        if not isinstance(item, dict):
            continue
        description = _space(item.get("description", ""))
        if description and description not in lines:
            lines.append(description)
    return "\n".join(lines)


def _resolve_region_ownership(
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Suppress lower-level interpretations inside an owned physical region.

    Detectors are intentionally independent, so a future heuristic may still
    emit a field that overlaps a structure detected earlier. Ownership gives us
    a deterministic final arbiter instead of relying only on call order.

    The rule is conservative: a candidate is suppressed only when *all* of its
    referenced paragraphs are inside a stronger owner's region.
    """

    # Only structures with an explicitly bounded physical region participate
    # in ownership.  A checkbox/choice group can share a paragraph with another
    # legitimate field (for example a conditional date), so paragraph-wide
    # ownership would be too aggressive. Repeatable tables have a clear header
    # + model-row boundary and are safe to claim as one region.
    owner_priority = {
        "repeatable_table": 100,
    }

    owners: list[tuple[int, set[int], dict[str, Any]]] = []
    for candidate in candidates:
        source = str(candidate.get("source", ""))
        priority = owner_priority.get(source, 0)
        if priority <= 0:
            continue
        location = dict(candidate.get("location", {}) or {})
        owned = _location_ordinals(location, prefer_owned=True)
        if not owned:
            continue
        candidate.setdefault("region_owner", source)
        owners.append((priority, owned, candidate))

    if not owners:
        return candidates

    result: list[dict[str, Any]] = []
    for candidate in candidates:
        source = str(candidate.get("source", ""))
        candidate_priority = owner_priority.get(source, 0)
        candidate_ordinals = _location_ordinals(
            dict(candidate.get("location", {}) or {}),
            prefer_owned=False,
        )
        suppressed = False
        if candidate_ordinals:
            for priority, owned, owner in owners:
                if owner is candidate or priority <= candidate_priority:
                    continue
                if candidate_ordinals.issubset(owned):
                    owner["ownership_suppressed"] = int(owner.get("ownership_suppressed", 0) or 0) + 1
                    suppressed = True
                    break
        if not suppressed:
            result.append(candidate)
    return result


def _location_ordinals(
    location: dict[str, Any],
    *,
    prefer_owned: bool,
) -> set[int]:
    values: list[Any] = []
    if prefer_owned and location.get("owned_paragraphs"):
        values.extend(location.get("owned_paragraphs", []) or [])
    elif location.get("paragraphs"):
        values.extend(location.get("paragraphs", []) or [])
    elif str(location.get("kind", "")) == "text_spans":
        values.extend(
            span.get("paragraph")
            for span in location.get("spans", []) or []
            if isinstance(span, dict)
        )
    elif "paragraph" in location:
        values.append(location.get("paragraph"))

    result: set[int] = set()
    for value in values:
        try:
            ordinal = int(value)
        except (TypeError, ValueError):
            continue
        if ordinal >= 0:
            result.add(ordinal)
    return result


def _deduplicate_candidates(
    candidates: list[dict[str, Any]],
    by_ordinal: dict[int, Any],
) -> list[dict[str, Any]]:
    # Exact physical-location duplicates are always alternative interpretations
    # of the same fill area. Keep the strongest one and retain evidence from both.
    exact: dict[tuple[Any, ...], dict[str, Any]] = {}
    for candidate in candidates:
        key = _location_signature(candidate.get("location", {}) or {})
        if key not in exact:
            exact[key] = candidate
            continue
        winner, loser = _pick_candidate(exact[key], candidate)
        _merge_candidate_evidence(winner, loser)
        exact[key] = winner

    values = list(exact.values())

    # Semantic duplicates in the same physical row are a common artifact of
    # label-cell + value-cell detection. They should collapse without assuming
    # a fixed table shape.
    result: list[dict[str, Any]] = []
    row_index: dict[tuple[Any, ...], int] = {}
    for candidate in sorted(values, key=lambda item: (_candidate_ordinal(item), -float(item.get("confidence", 0.0)))):
        ordinal = _candidate_ordinal(candidate)
        record = by_ordinal.get(ordinal)
        row_key = (
            getattr(record, "story", None),
            getattr(record, "table_index", None),
            getattr(record, "row_index", None),
            _slug(candidate.get("label", "")),
            str(candidate.get("type", "text")),
        )
        # Outside tables row_index is None, so do not collapse unrelated body
        # paragraphs that happen to share the same label.
        if row_key[1] is not None and row_key[2] is not None and row_key in row_index:
            existing_pos = row_index[row_key]
            winner, loser = _pick_candidate(result[existing_pos], candidate)
            _merge_candidate_evidence(winner, loser)
            result[existing_pos] = winner
            continue
        if row_key[1] is not None and row_key[2] is not None:
            row_index[row_key] = len(result)
        result.append(candidate)

    return result


def _merge_candidate_evidence(winner: dict[str, Any], loser: dict[str, Any]) -> None:
    merged = list(winner.get("evidence", []) or [])
    seen = {str(item.get("code", "")) for item in merged if isinstance(item, dict)}
    for item in loser.get("evidence", []) or []:
        if isinstance(item, dict) and str(item.get("code", "")) not in seen:
            merged.append(dict(item))
            seen.add(str(item.get("code", "")))
    winner["evidence"] = merged
    winner["confidence"] = max(float(winner.get("confidence", 0.0)), float(loser.get("confidence", 0.0)))
    winner["confidence_band"] = confidence_band(float(winner.get("confidence", 0.0)))


def _pick_candidate(a: dict[str, Any], b: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    def score(item: dict[str, Any]) -> tuple[float, int, int]:
        source = str(item.get("source", ""))
        source_priority = {
            "repeatable_table": 6,
            "checkbox_choice": 5,
            "long_choice": 5,
            "sample_value": 4,
            "inline_placeholder": 4,
            "empty_cell": 3,
            "instruction": 3,
            "prefilled_text": 3,
            "terminal_prompt": 5,
            "colored_prompt": 4,
            "colored_inline_choice": 6,
            "dropdown_prompt": 2,
            "learned_mapping": 7,
            "semantic_inline": 4,
            "semantic_prose": 3,
            "repeatable_list": 5,
        }.get(source, 1)
        label_quality = 0 if _poor_label(str(item.get("label", ""))) else 1
        return float(item.get("confidence", 0.0)), source_priority, label_quality

    return (a, b) if score(a) >= score(b) else (b, a)


def _adjacent_left_label(record: Any) -> str:
    table = getattr(record, "table", None)
    row_index = getattr(record, "row_index", None)
    cell_index = getattr(record, "cell_index", None)
    current_cell = getattr(record, "cell", None)
    if table is None or row_index is None or cell_index is None or int(cell_index) <= 0:
        return ""
    try:
        row = table.rows[int(row_index)]
        current_key = id(getattr(current_cell, "_tc", current_cell)) if current_cell is not None else None
        # Walk left from the physical cell index. Skip duplicate references
        # created by merged Word cells.
        for position in range(int(cell_index) - 1, -1, -1):
            cell = row.cells[position]
            key = id(getattr(cell, "_tc", cell))
            if current_key is not None and key == current_key:
                continue
            value = _space(getattr(cell, "text", ""))
            if not value:
                continue
            if _is_section_text(value) or _looks_like_fill(value) or _CHECKBOX_TEXT_RE.search(value):
                return ""
            cleaned = _clean_label(value)
            if _reasonable_label(cleaned, maximum=120):
                # Colon-ended cells are explicit labels. Short plain labels
                # are also allowed because many PDFs lose the colon during
                # reconstruction.
                if value.rstrip().endswith((":", "：")) or len(cleaned.split()) <= 8:
                    return cleaned
            return ""
        return ""
    except Exception:
        return ""


def _table_axes(record: Any) -> tuple[str, str]:
    table = getattr(record, "table", None)
    row_index = getattr(record, "row_index", None)
    cell_index = getattr(record, "cell_index", None)
    current_cell = getattr(record, "cell", None)
    if table is None or row_index is None or cell_index is None:
        return "", ""
    try:
        row = table.rows[int(row_index)]
        current_key = id(getattr(current_cell, "_tc", current_cell)) if current_cell is not None else None
        row_label = ""
        seen: set[int] = set()
        for cell in row.cells:
            key = id(getattr(cell, "_tc", cell))
            if key in seen:
                continue
            seen.add(key)
            if current_key is not None and key == current_key:
                break
            value = _space(getattr(cell, "text", ""))
            if (
                _reasonable_label(value, maximum=120)
                and not _looks_like_fill(value)
                and not value.isdigit()
                and not _CHECKBOX_TEXT_RE.search(value)
                and not _is_section_text(value)
            ):
                # The left-most useful text is normally the row identity. Do
                # not let a later situation/choice cell overwrite it.
                if not row_label:
                    row_label = _clean_label(value)

        column_label = ""
        for previous_row in range(int(row_index) - 1, -1, -1):
            cells = table.rows[previous_row].cells
            if int(cell_index) >= len(cells):
                continue
            value = _space(getattr(cells[int(cell_index)], "text", ""))
            if not value or _looks_like_fill(value) or _is_section_text(value):
                continue
            cleaned = _clean_label(value)
            if _reasonable_label(cleaned, maximum=100):
                column_label = cleaned
                break
        return row_label, column_label
    except Exception:
        return "", ""


def _consider_label(
    semantics: RecordSemantics,
    label: str,
    source: str,
    confidence: float,
    description: str,
) -> None:
    label = _space(label)
    if not label or not _reasonable_label(label, maximum=180):
        return
    semantics.evidence.append(Evidence(source, confidence - 0.5, description))
    if confidence > semantics.label_confidence:
        semantics.label = label
        semantics.label_source = source
        semantics.label_confidence = confidence


def _infer_record_role(text: str, semantics: RecordSemantics) -> str:
    if not text:
        return "blank"
    if _is_section_text(text):
        return "section"
    if _looks_like_fill(text):
        return "fill_area"
    if text.endswith((":", "：")) and _reasonable_label(text):
        return "label"
    if semantics.row_label or semantics.column_label:
        return "table_content"
    return "content"


def _get_semantics(record: Any | None) -> RecordSemantics:
    if record is None:
        return RecordSemantics()
    value = getattr(record, "understanding", None)
    return value if isinstance(value, RecordSemantics) else RecordSemantics()


def _set_semantics(record: Any, semantics: RecordSemantics) -> None:
    try:
        setattr(record, "understanding", semantics)
    except Exception:
        pass


def _first_location_ordinal(location: dict[str, Any]) -> int:
    if "paragraph" in location:
        try:
            return int(location["paragraph"])
        except Exception:
            return -1
    paragraphs = list(location.get("paragraphs", []) or [])
    if not paragraphs and str(location.get("kind", "")) == "text_spans":
        paragraphs = [
            span.get("paragraph")
            for span in location.get("spans", []) or []
            if isinstance(span, dict)
        ]
    if paragraphs:
        try:
            return min(int(value) for value in paragraphs)
        except Exception:
            return -1
    return -1


def _candidate_ordinal(candidate: dict[str, Any]) -> int:
    return _first_location_ordinal(dict(candidate.get("location", {}) or {}))


def _location_signature(location: dict[str, Any]) -> tuple[Any, ...]:
    kind = str(location.get("kind", ""))
    if kind == "text_span":
        return kind, location.get("paragraph"), location.get("start"), location.get("end")
    if kind == "text_spans":
        spans = tuple(
            sorted(
                (span.get("paragraph"), span.get("start"), span.get("end"))
                for span in location.get("spans", []) or []
                if isinstance(span, dict)
            )
        )
        return kind, spans
    if "paragraph" in location:
        return kind, location.get("paragraph")
    if "paragraphs" in location:
        return kind, tuple(location.get("paragraphs", []) or [])
    if kind == "repeatable_table":
        return kind, location.get("table_index")
    return kind, tuple(sorted((str(k), repr(v)) for k, v in location.items()))


def _type_has_semantic_support(field_type: str, label: str, preview: str) -> bool:
    slug = _slug(label)
    text = f"{label} {preview}".casefold()
    if field_type == "date":
        return "data" in slug or bool(re.search(r"_+\s*/\s*_+\s*/\s*_+", preview))
    if field_type == "phone":
        return any(token in slug for token in ("telefone", "celular", "fone")) or "(" in preview
    if field_type == "email":
        return "email" in slug or "e_mail" in slug or "@" in preview
    if field_type == "cpf":
        return "cpf" in slug
    if field_type == "cnpj":
        return "cnpj" in slug
    if field_type == "cep":
        return "cep" in slug
    if field_type in {"dropdown", "checkbox", "checkbox_group"}:
        return any(token in text for token in ("sim", "não", "nao", "escolher", "selecione", "☐", "□"))
    return True


def _poor_label(label: str) -> bool:
    value = _space(label)
    if not value:
        return True
    if _GENERIC_LABEL_RE.fullmatch(value):
        return True
    slug = _slug(value)
    return slug in {"item", "tipo", "campo", "descricao", "opcao"} and len(value.split()) == 1


def _labels_equivalent(a: str, b: str) -> bool:
    sa, sb = _slug(a), _slug(b)
    return bool(sa and sb and (sa == sb or sa in sb or sb in sa))


def _looks_like_fill(value: str) -> bool:
    text = _space(value)
    if not text:
        return True
    return bool(_FILL_RE.fullmatch(text))


def _is_section_text(value: str) -> bool:
    text = _space(value)
    if not text:
        return False
    return is_numbered_section_heading(text) and len(text) <= 190


def _reasonable_label(value: str, *, maximum: int = 150) -> bool:
    text = _space(value).rstrip(":：")
    if len(text) < 2 or len(text) > maximum:
        return False
    if _looks_like_fill(text):
        return False
    if len(text.split()) > 22:
        return False
    return any(character.isalpha() for character in text)


def _clean_label(value: str) -> str:
    text = _space(value).rstrip(":：").strip()
    text = re.sub(r"^\s*\d+(?:\.\d+)*[.)]?\s*", "", text)
    return text.strip()


def _slug(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(character for character in text if not unicodedata.combining(character))
    text = re.sub(r"[^A-Za-z0-9]+", "_", text.casefold()).strip("_")
    return text


def _space(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _clamp(value: float) -> float:
    return max(0.0, min(float(value), 1.0))
