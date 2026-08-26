from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

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
    _unique_field_id,
)
from app.document.detection.roles import instruction_is_static_guidance
from app.document.detection.tables import (
    _detect_editable_sheet_tables,
    _detect_long_choice_blocks,
    _detect_repeatable_tables,
)
from app.document.detection.text_fields import (
    _detect_adjacent_sample_value,
    _detect_blank_followup_areas,
    _detect_colored_inline_choice,
    _detect_colored_prompt,
    _detect_consistency_repair_fields,
    _detect_dropdown_prompt,
    _detect_empty_cells,
    _detect_inline_placeholders,
    _detect_label_only_field,
    _detect_labeled_instruction,
    _detect_labeled_sample_value,
    _detect_prefilled_written_text,
    _detect_terminal_prompt,
)
from app.document.understanding.smart_template import suggest_field_type


CancelCheck = Callable[[], None]


@dataclass
class DetectionWorkspace:
    """Mutable state shared by the independent assisted-detection passes."""

    document: Any
    records: list[Any]
    structure: Any
    known_ids: set[str]
    reserved_ordinals: set[int]
    candidates: list[dict[str, Any]] = field(default_factory=list)


def run_structural_detector_passes(
    workspace: DetectionWorkspace,
    check_cancel: CancelCheck,
) -> None:
    """Run detectors that claim multi-record/table regions before text fields."""

    document = workspace.document
    records = workspace.records
    known_ids = workspace.known_ids
    reserved = workspace.reserved_ordinals
    candidates = workspace.candidates

    check_cancel()
    long_choices = _detect_long_choice_blocks(document, records, known_ids)
    for candidate in long_choices:
        candidates.append(candidate)
        reserved.update(
            int(value)
            for value in candidate.get("location", {}).get("paragraphs", [])
        )
        known_ids.add(str(candidate.get("field_id", "")))

    check_cancel()
    repeatable_tables = _detect_repeatable_tables(
        document,
        records,
        known_ids,
        reserved,
    )
    for candidate in repeatable_tables:
        candidates.append(candidate)
        reserved.update(
            int(value)
            for value in candidate.get("location", {}).get("paragraphs", [])
        )
        known_ids.add(str(candidate.get("field_id", "")))

    check_cancel()
    editable_sheets = _detect_editable_sheet_tables(
        document,
        records,
        known_ids,
        reserved,
    )
    for candidate in editable_sheets:
        candidates.append(candidate)
        reserved.update(
            int(value)
            for value in candidate.get("location", {}).get("paragraphs", [])
        )
        known_ids.add(str(candidate.get("field_id", "")))

    check_cancel()
    checkbox_choices = _detect_checkbox_choice_groups(
        document,
        records,
        known_ids,
        reserved,
    )
    for candidate in checkbox_choices:
        candidates.append(candidate)
        reserved.update(
            int(value)
            for value in candidate.get("location", {}).get("paragraphs", [])
        )
        for field in candidate.get("fields", []) or []:
            known_ids.add(str(field.get("id", "")))

    check_cancel()
    single_checkboxes = _detect_standalone_checkboxes(records, known_ids, reserved)
    for candidate in single_checkboxes:
        candidates.append(candidate)
        reserved.add(int(candidate.get("location", {}).get("paragraph", -1)))
        known_ids.add(str(candidate.get("field_id", "")))

    check_cancel()
    followup_areas = _detect_blank_followup_areas(records, known_ids, reserved)
    for candidate in followup_areas:
        candidates.append(candidate)
        known_ids.add(str(candidate.get("field_id", "")))


def run_record_detector_passes(
    workspace: DetectionWorkspace,
    check_cancel: CancelCheck,
) -> None:
    """Run local paragraph/cell detectors after structural ownership is fixed."""

    records = workspace.records
    known_ids = workspace.known_ids
    reserved = workspace.reserved_ordinals
    candidates = workspace.candidates
    structure = workspace.structure

    for record in records:
        check_cancel()
        if record.ordinal in reserved:
            continue
        if _contains_authoritative_marker(record.paragraph):
            continue

        terminal_prompt = _detect_terminal_prompt(
            record,
            records,
            known_ids,
            structure,
        )
        if terminal_prompt is not None:
            candidates.append(terminal_prompt)
            known_ids.add(str(terminal_prompt.get("field_id", "")))
            continue

        dropdown_prompt = _detect_dropdown_prompt(record, records, known_ids)
        if dropdown_prompt is not None:
            candidates.append(dropdown_prompt)
            known_ids.add(str(dropdown_prompt.get("field_id", "")))
            continue

        colored_inline_choice = _detect_colored_inline_choice(record, records, known_ids)
        if colored_inline_choice is not None:
            candidates.append(colored_inline_choice)
            known_ids.add(str(colored_inline_choice.get("field_id", "")))
            continue

        colored_prompt = _detect_colored_prompt(record, records, known_ids)
        if colored_prompt is not None:
            candidates.append(colored_prompt)
            known_ids.add(str(colored_prompt.get("field_id", "")))
            continue

        sample_value = _detect_labeled_sample_value(record, known_ids)
        if sample_value is not None:
            candidates.append(sample_value)
            known_ids.add(str(sample_value.get("field_id", "")))
            continue

        labeled_instruction = _detect_labeled_instruction(record, known_ids)
        if labeled_instruction is not None:
            candidates.append(labeled_instruction)
            known_ids.add(str(labeled_instruction.get("field_id", "")))
            continue

        inline = _detect_inline_placeholders(record, records, known_ids)
        if inline:
            candidates.extend(inline)
            known_ids.update(str(item.get("field_id", "")) for item in inline)
            continue

        text = _normalize_space(record.text)
        if not text:
            continue

        if _is_instruction_candidate(record) and not instruction_is_static_guidance(
            record,
            records,
        ):
            label = _context_label_for_record(record, records)
            field_type = "multiline" if len(text) >= 70 else suggest_field_type(label or text)
            if field_type == "text" and len(text) >= 70:
                field_type = "multiline"
            field_id = _unique_field_id(_make_field_id(label or text[:60]), known_ids)
            known_ids.add(field_id)
            candidates.append(
                _candidate(
                    field_id=field_id,
                    label=label or _instruction_label(text),
                    field_type=field_type,
                    confidence=0.84 if _paragraph_is_red(record.paragraph) else 0.76,
                    source="instruction",
                    preview=text,
                    location={"kind": "paragraph", "paragraph": record.ordinal},
                )
            )
            continue

        prefilled_text = _detect_prefilled_written_text(record, records, known_ids)
        if prefilled_text is not None:
            candidates.append(prefilled_text)
            known_ids.add(str(prefilled_text.get("field_id", "")))
            continue

        adjacent_sample = _detect_adjacent_sample_value(record, records, known_ids)
        if adjacent_sample is not None:
            candidates.append(adjacent_sample)
            known_ids.add(str(adjacent_sample.get("field_id", "")))
            continue

        label_only = _detect_label_only_field(record, records, known_ids)
        if label_only is not None:
            candidates.append(label_only)
            known_ids.add(str(label_only.get("field_id", "")))


def run_fallback_detector_passes(
    workspace: DetectionWorkspace,
    check_cancel: CancelCheck,
) -> None:
    """Run lower-priority cell/consistency detectors last."""

    check_cancel()
    workspace.candidates.extend(
        _detect_empty_cells(
            workspace.document,
            workspace.records,
            workspace.known_ids,
            workspace.reserved_ordinals,
        )
    )

    check_cancel()
    workspace.candidates.extend(
        _detect_consistency_repair_fields(
            workspace.records,
            workspace.candidates,
            workspace.known_ids,
        )
    )
