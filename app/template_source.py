from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from pathlib import Path
from uuid import uuid4

from app.pdf_converter import DocxConversionError, convert_pdf_to_docx


SUPPORTED_TEMPLATE_SUFFIXES = frozenset({'.docx', '.pdf'})


class TemplateSourceError(RuntimeError):
    """Raised when a source file cannot be prepared for the template engine."""


@dataclass(frozen=True)
class PreparedTemplateSource:
    original_path: Path
    docx_path: Path
    converted_from_pdf: bool
    warnings: tuple[str, ...] = ()
    native_pdf_fields: int = 0
    native_pdf_field_hints: tuple[dict[str, Any], ...] = ()


def prepare_template_source(source_path: Path | str, work_dir: Path | str) -> PreparedTemplateSource:
    """Prepare DOCX or PDF input for the existing DOCX template engine.

    DOCX remains the canonical editable template format used by the generator.
    A PDF is reconstructed into a temporary DOCX. When the PDF contains native
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
        raise TemplateSourceError('Selecione um arquivo DOCX ou PDF.')

    if suffix == '.docx':
        return PreparedTemplateSource(
            original_path=source,
            docx_path=source,
            converted_from_pdf=False,
        )

    target_dir = Path(work_dir).expanduser().resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
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
        converted = convert_pdf_to_docx(
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
                checkbox_label = _pdf_widget_visible_label(page, widget, prefer_right=True)
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


def _pdf_widget_visible_label(page, widget, *, prefer_right: bool) -> str:
    """Infer the human-facing text printed next to a native PDF widget.

    AcroForm field names are technical identifiers and often do not match the
    visible document labels.  Prefer text on the same baseline: checkboxes use
    the text to their right, while ordinary controls use the text immediately
    to their left.  A nearby heading above the widget is used only as a fallback
    for large controls such as multiline observation areas.
    """

    rect = widget.rect
    words = page.get_text("words") or []
    same_line: list[tuple[float, float, float, float, str]] = []
    for raw in words:
        x0, y0, x1, y1, text = raw[:5]
        overlap = min(float(y1), float(rect.y1) + 4.0) - max(float(y0), float(rect.y0) - 4.0)
        if overlap <= 0:
            continue
        same_line.append((float(x0), float(y0), float(x1), float(y1), str(text)))

    if prefer_right:
        candidates = [item for item in same_line if item[0] >= float(rect.x1) + 2.0 and item[0] - float(rect.x1) <= 220.0]
        if candidates:
            candidates.sort(key=lambda item: item[0])
            selected = [candidates[0]]
            last_x1 = candidates[0][2]
            for item in candidates[1:]:
                if item[0] - last_x1 > 18.0:
                    break
                selected.append(item)
                last_x1 = item[2]
            return _clean_pdf_visible_label(" ".join(item[4] for item in selected))
    else:
        candidates = [item for item in same_line if item[0] < float(rect.x0) and item[2] <= float(rect.x0) + 32.0 and float(rect.x0) - item[2] <= 180.0]
        if candidates:
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
    rect = widget.rect
    right = min(
        float(page.rect.x1),
        right_limit if right_limit is not None else float(rect.x1) + 180.0,
    )
    area = type(rect)(float(rect.x1) + 2.0, float(rect.y0) - 4.0, right, float(rect.y1) + 5.0)
    text = ' '.join(str(page.get_textbox(area)).split())
    return text.strip(' :-')


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
