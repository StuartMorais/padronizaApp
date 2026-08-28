from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from typing import Any
from pathlib import Path
from uuid import uuid4

from app.document.understanding.context_resolver import prepare_word_controls_with_context
from app.document.conversion.service import DEFAULT_CONVERTER, DocxConversionError
from app.document.word_package import WORD_INPUT_SUFFIXES, WordPackageError, normalize_word_input


SUPPORTED_TEMPLATE_SUFFIXES = frozenset({*WORD_INPUT_SUFFIXES, '.pdf'})


class TemplateSourceError(RuntimeError):
    """Raised when a source file cannot be prepared for the template engine."""


@dataclass(frozen=True)
class PreparedTemplateSource:
    original_path: Path
    docx_path: Path
    converted_from_pdf: bool
    converted_from_docm: bool = False
    warnings: tuple[str, ...] = ()
    native_pdf_fields: int = 0
    native_pdf_field_hints: tuple[dict[str, Any], ...] = ()
    native_word_field_hints: tuple[dict[str, Any], ...] = ()
    prepared_work_copy: bool = False


def prepare_template_source(source_path: Path | str, work_dir: Path | str) -> PreparedTemplateSource:
    """Prepare DOCX, DOCM, or PDF input for the canonical DOCX template engine.

    DOCX remains the canonical editable template format used by the generator.
    DOCM is normalized to an inert DOCX working copy with VBA removed, and a
    PDF is reconstructed into a temporary DOCX. When the PDF contains native
    AcroForm widgets, a temporary PDF copy receives normal Padroniza tags at the
    widget positions before reconstruction. This lets the existing scanner and
    generator reuse those native field definitions instead of losing blank PDF
    fields during text extraction.
    """

    source = Path(source_path).expanduser().resolve()
    if not source.exists() or not source.is_file():
        raise TemplateSourceError('O arquivo selecionado não foi encontrado.')

    suffix = source.suffix.casefold()
    if suffix not in SUPPORTED_TEMPLATE_SUFFIXES:
        raise TemplateSourceError('Selecione um arquivo DOCX, DOCM ou PDF.')

    target_dir = Path(work_dir).expanduser().resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    if suffix in WORD_INPUT_SUFFIXES:
        stem = source.stem[:80] or 'modelo'
        normalized_source = source
        normalized_docm: Path | None = None
        warnings: list[str] = []
        try:
            if suffix == '.docm':
                normalized_docm = target_dir / f'{stem}-docm-{uuid4().hex[:10]}.docx'
                normalized = normalize_word_input(source, normalized_docm)
                normalized_source = normalized.path
                warnings.append(
                    'O DOCM foi aberto como uma cópia DOCX segura; macros VBA não são executadas nem preservadas.'
                )

            destination = target_dir / f'{stem}-contexto-{uuid4().hex[:10]}.docx'
            word_preparation = prepare_word_controls_with_context(normalized_source, destination)
            prepared_docx_path = word_preparation.path
            if suffix == '.docm' and prepared_docx_path != destination:
                # If no native controls needed rewriting, the context resolver
                # returns its input path. Keep a persistent canonical DOCX copy
                # before the temporary normalized DOCM package is removed.
                shutil.copy2(prepared_docx_path, destination)
                prepared_docx_path = destination
        except WordPackageError as exc:
            raise TemplateSourceError(str(exc)) from exc
        except Exception as exc:
            raise TemplateSourceError(f'Não foi possível preparar os controles do Word: {exc}') from exc
        finally:
            if normalized_docm is not None:
                try:
                    normalized_docm.unlink(missing_ok=True)
                except OSError:
                    pass

        warnings.extend(word_preparation.warnings)

        # Padroniza versions before Scanner V6.1.8 reconstructed PDF text by
        # using both bbox edges as paragraph indents.  If a user re-imports one
        # of those generated DOCX files, repair it on the work copy instead of
        # perpetuating the narrow/wrapped layout forever.  The original file is
        # never modified.
        legacy_layout_repaired = False
        try:
            from app.document.conversion.pdf import repair_legacy_pdf_docx_layout

            repair_destination = destination
            legacy_layout_repaired = repair_legacy_pdf_docx_layout(
                prepared_docx_path, repair_destination
            )
            if legacy_layout_repaired:
                prepared_docx_path = repair_destination
                warnings.append(
                    'O layout de um DOCX antigo convertido de PDF pelo Padroniza foi corrigido para preservar a largura normal dos parágrafos.'
                )
        except DocxConversionError as exc:
            raise TemplateSourceError(str(exc)) from exc

        return PreparedTemplateSource(
            original_path=source,
            docx_path=prepared_docx_path,
            converted_from_pdf=False,
            converted_from_docm=suffix == '.docm',
            warnings=tuple(warnings),
            native_word_field_hints=word_preparation.field_hints,
            prepared_work_copy=(
                True
                if suffix == '.docm'
                else bool(word_preparation.changed or legacy_layout_repaired)
            ),
        )

    stem = source.stem[:80] or 'modelo'
    destination = target_dir / f'{stem}-pdf-{uuid4().hex[:10]}.docx'
    warning_list: list[str] = []

    conversion_source = source
    native_field_count = 0
    native_field_hints: tuple[dict[str, Any], ...] = ()
    tagged_pdf: Path | None = None
    try:
        tagged_pdf, native_field_count, native_field_hints = _tag_native_pdf_fields(source, target_dir)
        if tagged_pdf is not None:
            conversion_source = tagged_pdf
            warning_list.append(
                f'{native_field_count} campo(s) nativo(s) do PDF foram reconhecidos e preparados para o modelo.'
            )
        converted = DEFAULT_CONVERTER.pdf_to_docx(
            conversion_source,
            destination,
            warnings=warning_list,
        )
    except DocxConversionError as exc:
        raise TemplateSourceError(str(exc)) from exc
    except Exception as exc:
        raise TemplateSourceError(f'Não foi possível preparar o PDF: {exc}') from exc
    finally:
        if tagged_pdf is not None:
            try:
                tagged_pdf.unlink(missing_ok=True)
            except OSError:
                pass

    return PreparedTemplateSource(
        original_path=source,
        docx_path=converted,
        converted_from_pdf=True,
        warnings=tuple(warning_list),
        native_pdf_fields=native_field_count,
        native_pdf_field_hints=native_field_hints,
    )


def _tag_native_pdf_fields(
    source: Path,
    target_dir: Path,
) -> tuple[Path | None, int, tuple[dict[str, Any], ...]]:
    """Return a temporary PDF with AcroForm widgets represented as Padroniza tags."""

    try:
        import fitz
    except Exception:
        return None, 0, ()

    document = fitz.open(str(source))
    if document.needs_pass:
        document.close()
        return None, 0, ()

    page_widgets: list[tuple[object, list[object]]] = []
    total_widgets = 0
    for page in document:
        widgets = []
        widget = page.first_widget
        while widget is not None:
            widgets.append(widget)
            total_widgets += 1
            widget = widget.next
        if widgets:
            page_widgets.append((page, widgets))

    if total_widgets == 0:
        document.close()
        return None, 0, ()

    prepared_fields = 0
    field_hints: list[dict[str, Any]] = []
    for page, widgets in page_widgets:
        page_hint_start = len(field_hints)
        handled_radio_groups: set[str] = set()
        radio_groups: dict[str, list[object]] = {}
        for widget in widgets:
            if str(getattr(widget, 'field_type_string', '')) == 'RadioButton':
                radio_groups.setdefault(str(widget.field_name or 'opcao'), []).append(widget)

        overlays: list[tuple[object, str]] = []
        for widget in widgets:
            field_name = _safe_field_id(str(widget.field_name or f'campo_{prepared_fields + 1}'))
            field_type = str(getattr(widget, 'field_type_string', '') or '')

            if field_type == 'RadioButton':
                if field_name in handled_radio_groups:
                    continue
                handled_radio_groups.add(field_name)
                group = radio_groups.get(str(widget.field_name or 'opcao'), [widget])
                group = sorted(group, key=lambda item: (float(item.rect.y0), float(item.rect.x0)))
                options = []
                for index, item in enumerate(group):
                    next_x = (
                        float(group[index + 1].rect.x0) - 4.0
                        if index + 1 < len(group)
                        and abs(float(group[index + 1].rect.y0) - float(item.rect.y0)) < 12.0
                        else None
                    )
                    options.append(_pdf_widget_option_label(page, item, right_limit=next_x))
                options = [option for option in options if option]
                if len(options) < 2:
                    options = [_radio_export_value(item) for item in group]
                    options = [option for option in options if option]
                tag = '{{single_choice:' + field_name
                if options:
                    tag += '|' + '|'.join(_escape_tag_option(option) for option in options)
                tag += '}}'
                overlays.append((group[0].rect, tag))
                group_label = _pdf_widget_visible_label(page, group[0], prefer_right=False)
                field_hints.append(
                    _native_pdf_field_hint(
                        field_name,
                        label=group_label,
                        field_type='dropdown',
                        options=options,
                    )
                )
                prepared_fields += 1
                continue

            if field_type == 'CheckBox':
                overlays.append((widget.rect, f'{{{{checkbox:{field_name}}}}}'))
                checkbox_label = _pdf_checkbox_visible_label(page, widget)
                field_hints.append(
                    _native_pdf_field_hint(
                        field_name,
                        label=checkbox_label,
                        field_type='checkbox',
                    )
                )
                prepared_fields += 1
                continue

            if field_type == 'ComboBox':
                options = [
                    str(value).strip()
                    for value in (getattr(widget, 'choice_values', None) or [])
                    if str(value).strip()
                ]
                options = [
                    value for value in options
                    if value.casefold() not in {'selecione...', 'selecione', 'escolher um item', 'escolher uma opção'}
                ]
                tag = '{{dropdown:' + field_name
                if options:
                    tag += '|' + '|'.join(_escape_tag_option(option) for option in options)
                tag += '}}'
                overlays.append((widget.rect, tag))
                combo_label = _pdf_widget_visible_label(page, widget, prefer_right=False)
                field_hints.append(
                    _native_pdf_field_hint(
                        field_name,
                        label=combo_label,
                        field_type='dropdown',
                        options=options,
                    )
                )
                prepared_fields += 1
                continue

            is_date = _looks_like_date_field(field_name)
            is_multiline = bool(int(getattr(widget, 'field_flags', 0) or 0) & 4096)
            prefix = 'date:' if is_date else ''
            overlays.append((widget.rect, f'{{{{{prefix}{field_name}}}}}'))
            visible_label = _pdf_widget_visible_label(page, widget, prefer_right=False)
            field_value = str(getattr(widget, 'field_value', '') or '').strip()
            field_hints.append(
                _native_pdf_field_hint(
                    field_name,
                    label=visible_label,
                    field_type=('date' if is_date else 'multiline' if is_multiline else 'text'),
                    placeholder=(field_value if field_value and field_value.casefold() != 'off' else ''),
                    automatic=False if is_date else None,
                    layout=(
                        'full_width'
                        if float(widget.rect.width) / max(float(page.rect.width), 1.0) >= 0.55
                        else ''
                    ),
                )
            )
            prepared_fields += 1

        # Native PDF questionnaire matrices need row-level ownership before the
        # widgets are removed.  AcroForm controls only know their technical
        # field names; the meaningful row label / column header lives in the
        # page geometry.  Preserve that relationship so a repeated radio group
        # such as ``Item | Situação | Observação`` cannot later be rendered as
        # anonymous standalone choices or label the observation field as the
        # nearest option token (for example ``N/A``).
        _apply_native_pdf_matrix_hints(
            page,
            widgets,
            field_hints[page_hint_start:],
        )

        # Remove widgets so their old/default appearances do not survive beside tags.
        for widget in list(widgets):
            try:
                page.delete_widget(widget)
            except Exception:
                pass

        for rect, tag in overlays:
            point = fitz.Point(float(rect.x0), max(float(rect.y0) + 6.0, 8.0))
            page.insert_text(
                point,
                tag,
                fontsize=5.0,
                fontname='helv',
                color=(0, 0, 0),
                overlay=True,
            )

    if prepared_fields == 0:
        document.close()
        return None, 0, ()

    tagged_pdf = target_dir / f'{source.stem[:70]}-acroform-{uuid4().hex[:8]}.pdf'
    document.save(str(tagged_pdf), garbage=4, deflate=True)
    document.close()
    return tagged_pdf, prepared_fields, tuple(field_hints)


def _native_pdf_field_hint(
    field_id: str,
    *,
    label: str = "",
    field_type: str = "text",
    options: list[str] | None = None,
    placeholder: str = "",
    automatic: bool | None = None,
    layout: str = "",
) -> dict[str, Any]:
    hint: dict[str, Any] = {
        "id": field_id,
        "label": label or _humanize_pdf_field_id(field_id),
        "label_source": "native_pdf",
        "type": field_type,
        "type_source": "native_pdf",
        "detection_source": "native_pdf",
    }
    if options:
        hint["options"] = list(options)
    if placeholder:
        hint["placeholder"] = placeholder
        hint["example"] = placeholder
    if automatic is not None:
        hint["automatic"] = bool(automatic)
    if layout:
        hint["layout"] = layout
    return hint


def _humanize_pdf_field_id(field_id: str) -> str:
    words = [part for part in re.split(r"[._-]+", field_id.strip()) if part]
    if not words:
        return "Campo PDF"
    return " ".join(words).capitalize()


def _pdf_same_line_words(page, rect) -> list[tuple[float, float, float, float, str]]:
    words = page.get_text("words") or []
    same_line: list[tuple[float, float, float, float, str]] = []
    for raw in words:
        x0, y0, x1, y1, text = raw[:5]
        overlap = min(float(y1), float(rect.y1) + 4.0) - max(float(y0), float(rect.y0) - 4.0)
        if overlap <= 0:
            continue
        same_line.append((float(x0), float(y0), float(x1), float(y1), str(text)))
    return same_line


def _pdf_contiguous_right_label(page, rect, *, right_limit: float | None = None) -> str:
    same_line = _pdf_same_line_words(page, rect)
    right_edge = (
        min(float(page.rect.x1), float(right_limit))
        if right_limit is not None
        else min(float(page.rect.x1), float(rect.x1) + 220.0)
    )
    candidates = [
        item
        for item in same_line
        if item[0] >= float(rect.x1) + 2.0
        and item[0] <= right_edge
        and item[0] - float(rect.x1) <= 220.0
    ]
    if not candidates:
        return ""
    candidates.sort(key=lambda item: item[0])
    selected = [candidates[0]]
    last_x1 = candidates[0][2]
    for item in candidates[1:]:
        # A new label / question on the same visual row normally starts after
        # a noticeably larger horizontal gap.  Keep multi-word alternatives
        # such as "Não conforme" together while stopping before a neighbor
        # such as "Requer acesso externo".
        if item[0] - last_x1 > 18.0:
            break
        selected.append(item)
        last_x1 = item[2]
    return _clean_pdf_visible_label(" ".join(item[4] for item in selected))


def _pdf_contiguous_left_label(page, rect) -> str:
    same_line = _pdf_same_line_words(page, rect)
    candidates = [
        item
        for item in same_line
        if item[0] < float(rect.x0)
        and item[2] <= float(rect.x0) + 32.0
        and float(rect.x0) - item[2] <= 180.0
    ]
    if not candidates:
        return ""
    candidates.sort(key=lambda item: item[0])
    selected_rev = [candidates[-1]]
    first_x0 = candidates[-1][0]
    for item in reversed(candidates[:-1]):
        if first_x0 - item[2] > 18.0:
            break
        selected_rev.append(item)
        first_x0 = item[0]
    selected = list(reversed(selected_rev))
    return _clean_pdf_visible_label(" ".join(item[4] for item in selected))


def _pdf_widget_visible_label(page, widget, *, prefer_right: bool) -> str:
    """Infer the human-facing text printed next to a native PDF widget.

    AcroForm field names are technical identifiers and often do not match the
    visible document labels. Prefer text on the same baseline: checkboxes use
    the text to their right, while ordinary controls use the text immediately
    to their left. A nearby heading above the widget is used only as a fallback
    for large controls such as multiline observation areas.
    """

    rect = widget.rect
    if prefer_right:
        label = _pdf_contiguous_right_label(page, rect)
        if label:
            return label
    else:
        label = _pdf_contiguous_left_label(page, rect)
        if label:
            return label

    words = page.get_text("words") or []

    # Large fields often have a section-like label immediately above them.
    above = []
    for raw in words:
        x0, y0, x1, y1, text = raw[:5]
        vertical_gap = float(rect.y0) - float(y1)
        if not (0.0 <= vertical_gap <= 45.0):
            continue
        if float(x1) < float(rect.x0) - 20.0 or float(x0) > float(rect.x1) + 20.0:
            continue
        above.append((vertical_gap, float(y0), float(x0), str(text)))
    if above:
        min_gap = min(item[0] for item in above)
        nearest = [item for item in above if abs(item[0] - min_gap) <= 3.0]
        nearest.sort(key=lambda item: item[2])
        return _clean_pdf_visible_label(" ".join(item[3] for item in nearest))

    return ""


def _clean_pdf_visible_label(value: str) -> str:
    value = " ".join(str(value).split()).strip(" :-")
    value = re.sub(r"^\d+(?:\.\d+)*\.?\s+", "", value).strip()
    return value


def _safe_field_id(value: str) -> str:
    value = value.strip().casefold()
    value = re.sub(r'[^a-z0-9_.-]+', '_', value)
    value = re.sub(r'_+', '_', value).strip('_.-')
    return value or 'campo_pdf'


def _looks_like_date_field(field_id: str) -> bool:
    pieces = set(re.split(r'[._-]+', field_id.casefold()))
    return bool({'data', 'date', 'dt'} & pieces) or field_id.casefold().endswith('_data')


def _pdf_widget_option_label(page, widget, *, right_limit: float | None = None) -> str:
    return _pdf_contiguous_right_label(page, widget.rect, right_limit=right_limit)


def _pdf_checkbox_visible_label(page, widget) -> str:
    """Prefer the human question over a generic yes/no token beside a box.

    A common PDF pattern is ``Requer acesso externo: [ ] Sim``.  The immediate
    text to the right is only the answer token, while the meaningful field label
    sits to the left.  Long declarations/resources still keep their right-side
    text because it is descriptive rather than generic.
    """

    right = _pdf_contiguous_right_label(page, widget.rect)
    generic_answer = _clean_pdf_visible_label(right).casefold() in {
        'sim', 'não', 'nao', 'yes', 'no', 'ok', 'marcar', 'selecionar'
    }
    if right and not generic_answer:
        return right
    left = _pdf_contiguous_left_label(page, widget.rect)
    return left or right



def _apply_native_pdf_matrix_hints(
    page,
    widgets: list[object],
    hints: list[dict[str, Any]],
) -> None:
    """Attach row/column ownership to repeated AcroForm choice rows.

    PDF forms frequently implement a questionnaire matrix as several unrelated
    AcroForm radio groups plus text fields.  The controls themselves do not
    carry the visible row label (``Documentação disponível``) or the column
    title (``Situação`` / ``Observação``).  Detect repeated, vertically aligned
    radio groups and preserve that page geometry as Padroniza table metadata.

    This is deliberately conservative: a matrix needs at least two radio groups
    with the same option count and nearly identical x positions.  Isolated
    radio groups such as ``Prioridade`` remain normal choice cards.
    """

    hint_by_id = {
        str(hint.get("id", "")).strip(): hint
        for hint in hints
        if str(hint.get("id", "")).strip()
    }
    if not hint_by_id:
        return

    radio_groups: dict[str, list[object]] = {}
    text_widgets: list[object] = []
    for widget in widgets:
        field_type = str(getattr(widget, "field_type_string", "") or "")
        field_id = _safe_field_id(str(getattr(widget, "field_name", "") or ""))
        if not field_id:
            continue
        if field_type == "RadioButton":
            radio_groups.setdefault(field_id, []).append(widget)
        elif field_type == "Text":
            text_widgets.append(widget)

    rows: list[dict[str, Any]] = []
    for field_id, group in radio_groups.items():
        if len(group) < 2 or field_id not in hint_by_id:
            continue
        ordered = sorted(group, key=lambda item: (float(item.rect.x0), float(item.rect.y0)))
        x_positions = tuple(float(item.rect.x0) for item in ordered)
        top = min(float(item.rect.y0) for item in ordered)
        bottom = max(float(item.rect.y1) for item in ordered)
        left = min(float(item.rect.x0) for item in ordered)
        right = max(float(item.rect.x1) for item in ordered)
        rows.append(
            {
                "field_id": field_id,
                "widgets": ordered,
                "x_positions": x_positions,
                "count": len(ordered),
                "top": top,
                "bottom": bottom,
                "left": left,
                "right": right,
                "center_y": (top + bottom) / 2.0,
            }
        )

    if len(rows) < 2:
        return
    rows.sort(key=lambda item: (item["top"], item["left"]))

    clusters: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for row in rows:
        if not current:
            current = [row]
            continue
        previous = current[-1]
        aligned = (
            row["count"] == previous["count"]
            and len(row["x_positions"]) == len(previous["x_positions"])
            and all(
                abs(float(a) - float(b)) <= 12.0
                for a, b in zip(row["x_positions"], previous["x_positions"])
            )
        )
        close_vertically = 0.0 <= float(row["top"]) - float(previous["top"]) <= 65.0
        if aligned and close_vertically:
            current.append(row)
        else:
            if len(current) >= 2:
                clusters.append(current)
            current = [row]
    if len(current) >= 2:
        clusters.append(current)

    for cluster_index, cluster in enumerate(clusters, start=1):
        first = cluster[0]
        matrix_group = f"native_pdf_matrix_p{int(getattr(page, 'number', 0))}_{cluster_index}"

        # Discover the nearest header line above the first data row.  Splitting
        # that line into left / choice / right regions is more stable than
        # guessing labels from individual controls, because the row itself is
        # full of radio option text such as "N/A".
        observation_widgets: dict[str, object] = {}
        for row in cluster:
            sibling = _native_pdf_same_row_text_widget(row, text_widgets)
            if sibling is not None:
                observation_widgets[row["field_id"]] = sibling

        observation_left = min(
            [float(widget.rect.x0) for widget in observation_widgets.values()]
            or [float(first["right"]) + 70.0]
        )
        row_header, choice_header, observation_header = _native_pdf_matrix_headers(
            page,
            first_row_top=float(first["top"]),
            choice_left=float(first["left"]),
            observation_left=float(observation_left),
        )
        # Repeated Yes/No questions can share x positions without being a
        # matrix.  Claim the region only when a real header line establishes
        # both the row-identity column and the choice column.
        if not row_header or not choice_header:
            continue
        observation_header = observation_header or "Observação"

        for row_index, row in enumerate(cluster, start=1):
            hint = hint_by_id.get(str(row["field_id"]))
            if hint is None:
                continue
            row_label = _pdf_contiguous_left_label(page, row["widgets"][0].rect)
            row_label = row_label or str(hint.get("label", "")).strip()
            if not row_label:
                # A matrix without a row identity is too ambiguous to claim.
                continue

            row_key = f"row_{row_index}"
            hint.update(
                {
                    "label": row_label,
                    "layout": "table",
                    "layout_group": matrix_group,
                    "layout_row": row_key,
                    "layout_row_label": row_label,
                    "layout_row_header_label": row_header,
                    "layout_column": choice_header,
                    "layout_column_index": 1,
                    "layout_order": row_index - 1,
                    "selection": "single",
                    "choice_required": bool(hint.get("required", True)),
                    "tag_type": "single_choice",
                    "choice_group_label": row_label,
                    "compact_choice": True,
                    "matrix_owner": matrix_group,
                }
            )

            sibling = observation_widgets.get(str(row["field_id"]))
            if sibling is None:
                continue
            sibling_id = _safe_field_id(str(getattr(sibling, "field_name", "") or ""))
            sibling_hint = hint_by_id.get(sibling_id)
            if sibling_hint is None:
                continue
            sibling_hint.update(
                {
                    "label": f"{row_label} — {observation_header}",
                    "layout": "table",
                    "layout_group": matrix_group,
                    "layout_row": row_key,
                    "layout_row_label": row_label,
                    "layout_row_header_label": row_header,
                    "layout_column": observation_header,
                    "layout_column_index": 2,
                    "layout_order": row_index - 1,
                    "matrix_owner": matrix_group,
                    "matrix_role": "observation",
                }
            )


def _native_pdf_same_row_text_widget(row: dict[str, Any], widgets: list[object]):
    """Return the nearest text widget to the right of a matrix choice row."""

    candidates: list[tuple[float, object]] = []
    center_y = float(row["center_y"])
    right = float(row["right"])
    for widget in widgets:
        rect = widget.rect
        widget_center = (float(rect.y0) + float(rect.y1)) / 2.0
        if abs(widget_center - center_y) > 10.0:
            continue
        if float(rect.x0) <= right + 8.0:
            continue
        distance = float(rect.x0) - right
        if distance > 220.0:
            continue
        candidates.append((distance, widget))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def _native_pdf_matrix_headers(
    page,
    *,
    first_row_top: float,
    choice_left: float,
    observation_left: float,
) -> tuple[str, str, str]:
    """Return the left / choice / observation headers above a PDF matrix."""

    words = page.get_text("words") or []
    candidates: list[tuple[float, float, float, float, str]] = []
    for raw in words:
        x0, y0, x1, y1, text = raw[:5]
        gap = first_row_top - float(y1)
        if 5.0 <= gap <= 45.0:
            candidates.append((float(x0), float(y0), float(x1), float(y1), str(text)))
    if not candidates:
        return "", "", ""

    # Use the closest visual line only; the next line above is commonly the
    # numbered section title and must never become a matrix column heading.
    nearest_y = max(item[1] for item in candidates)
    line = [item for item in candidates if abs(item[1] - nearest_y) <= 3.0]
    line.sort(key=lambda item: item[0])

    left_words = [item[4] for item in line if item[2] < choice_left - 8.0]
    choice_words = [
        item[4]
        for item in line
        if item[0] >= choice_left - 12.0 and item[2] < observation_left - 8.0
    ]
    observation_words = [item[4] for item in line if item[0] >= observation_left - 40.0]
    return (
        _clean_pdf_visible_label(" ".join(left_words)),
        _clean_pdf_visible_label(" ".join(choice_words)),
        _clean_pdf_visible_label(" ".join(observation_words)),
    )

def _radio_export_value(widget) -> str:
    try:
        states = widget.button_states() or {}
    except Exception:
        states = {}
    values = [str(value) for value in states.get('normal', []) if str(value).casefold() != 'off']
    return values[0] if values else ''


def _escape_tag_option(value: str) -> str:
    # The current tag syntax reserves | as the option separator.
    return str(value).replace('|', '/').replace('}}', '')
