from __future__ import annotations

from collections import OrderedDict
from datetime import date
from html import escape
from typing import Any

from PySide6.QtCore import QDate, QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QCheckBox,
    QDateEdit,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.field_utils import (
    condition_matches,
    dropdown_option_values,
    infer_field_type,
    is_assisted_detection_field,
    sample_value,
    validate_field,
    validation_hint,
)
from app.layout_inference import group_form_grid_static_rows, layout_blocks
from app.widgets.context_help import HelpIconButton
from app.widgets.exclusive_choice import ChoiceOptionCheckBox, ExclusiveChoiceWidget
from app.widgets.readable_checkbox import ReadableCheckBox
from app.widgets.repeatable_table import RepeatableTableWidget
from app.widgets.searchable_dropdown import SearchableDropdown
from app.widgets.smart_line_edit import SmartLineEdit
from app.profile_mapping import build_profile_payload, resolve_profile_values


class _CollapsibleSection(QFrame):
    """Compact collapsible section used by long generated forms."""

    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("formSection")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.toggle = QToolButton()
        self.toggle.setObjectName("formSectionToggle")
        self.toggle.setText(title)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.ArrowType.DownArrow)
        self.toggle.setCheckable(True)
        self.toggle.setChecked(True)
        self.toggle.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.toggle.clicked.connect(self.set_expanded)
        outer.addWidget(self.toggle)

        self.body = QFrame()
        self.body.setObjectName("formSectionBody")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(14, 12, 14, 14)
        self.body_layout.setSpacing(12)
        outer.addWidget(self.body)

    def set_expanded(self, expanded: bool) -> None:
        self.toggle.setChecked(bool(expanded))
        self.toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )
        self.body.setVisible(bool(expanded))

    def expand(self) -> None:
        self.set_expanded(True)


# noinspection SpellCheckingInspection
class DocumentForm(QWidget):
    """Dynamic form with semantic sections, choices, tables and validation."""

    values_changed = Signal()
    edit_field_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.fields: list[dict[str, Any]] = []
        self.sections: list[dict[str, Any]] = []
        self.field_widgets: dict[str, QWidget] = {}
        self.field_containers: dict[str, QWidget] = {}
        self.field_definitions: dict[str, dict[str, Any]] = {}
        self.field_error_labels: dict[str, QLabel] = {}
        self.field_hint_labels: dict[str, QLabel] = {}
        self.field_sections: dict[str, _CollapsibleSection] = {}
        self.checkbox_groups: dict[str, list[str]] = {}
        self.button_groups: list[QButtonGroup] = []
        self.section_widgets: list[tuple[_CollapsibleSection, list[str]]] = []
        self.block_widgets: list[tuple[QWidget, list[str]]] = []
        self._touched_fields: set[str] = set()
        self._revealed_fields: set[str] = set()
        self._last_validation_issues: list[dict[str, str]] = []
        self._show_all_validation = False
        self._updating = False

        self.content_layout = QVBoxLayout(self)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(12)

        self.progress_card: QFrame | None = None
        self.progress_label: QLabel | None = None
        self.progress_bar: QProgressBar | None = None

    def set_fields(self, fields: list[dict[str, Any]]) -> None:
        self.set_template(fields, [])

    def set_template(
        self,
        fields: list[dict[str, Any]],
        sections: list[dict[str, Any]] | None = None,
    ) -> None:
        self._clear_layout(self.content_layout)
        self.fields = [dict(field) for field in fields if isinstance(field, dict)]
        self.sections = [dict(section) for section in (sections or []) if isinstance(section, dict)]
        self.field_widgets.clear()
        self.field_containers.clear()
        self.field_definitions.clear()
        self.field_error_labels.clear()
        self.field_hint_labels.clear()
        self.field_sections.clear()
        self.checkbox_groups.clear()
        self.button_groups.clear()
        self.section_widgets.clear()
        self.block_widgets.clear()
        self.reset_validation_visibility()

        visible_fields = [field for field in self.fields if not self._is_automatic_date(field)]
        if visible_fields:
            self._create_progress_card()

        ordered_sections = self._resolved_sections()
        rendered_ids: set[str] = set()

        for section in ordered_sections:
            title = str(section.get("title", "Informações")).strip() or "Informações"
            field_ids = [str(value) for value in section.get("fields", [])]
            section_fields = [
                field
                for field_id in field_ids
                for field in self.fields
                if str(field.get("id", "")) == field_id and field_id not in rendered_ids
            ]
            section_widget = self._build_section(title, section_fields, rendered_ids)
            if section_widget is not None:
                self.content_layout.addWidget(section_widget)

        remaining = [
            field
            for field in self.fields
            if str(field.get("id", "")) not in rendered_ids
            and not self._is_automatic_date(field)
        ]
        fallback = self._build_section("Informações adicionais", remaining, rendered_ids)
        if fallback is not None:
            self.content_layout.addWidget(fallback)

        required_note = QLabel(
            "Os campos marcados com * são obrigatórios. Em grupos de escolha exclusiva, "
            "cada alternativa aparece como uma caixa grande e clicável, mas somente uma "
            "pode permanecer selecionada."
        )
        required_note.setObjectName("mutedText")
        required_note.setWordWrap(True)
        self.content_layout.addWidget(required_note)
        self.content_layout.addStretch()

        # Some assisted-detection fields represent text that already exists in
        # the source document (for example a previously written justification).
        # These are real starting values, not placeholders: show the source text
        # inside the editor so the user can keep or edit it before generation.
        default_values = {
            str(field.get("id", "")).strip(): field.get("default_value")
            for field in self.fields
            if str(field.get("id", "")).strip()
            and "default_value" in field
            and field.get("default_value") is not None
        }
        if default_values:
            self.set_values(default_values, emit_signal=False)
        else:
            self._refresh_visibility()
            self._update_progress()

    def _create_progress_card(self) -> None:
        card = QFrame()
        card.setObjectName("formProgressCard")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(12)

        label = QLabel("Preenchimento do formulário")
        label.setObjectName("formProgressLabel")
        layout.addWidget(label)

        progress = QProgressBar()
        progress.setObjectName("formProgressBar")
        progress.setTextVisible(False)
        progress.setRange(0, 1)
        progress.setValue(0)
        progress.setMaximumWidth(280)
        layout.addWidget(progress, 1)

        details = QLabel()
        details.setObjectName("formProgressDetails")
        layout.addWidget(details)

        self.progress_card = card
        self.progress_label = details
        self.progress_bar = progress
        self.content_layout.addWidget(card)

    def _build_section(
        self,
        title: str,
        section_fields: list[dict[str, Any]],
        rendered_ids: set[str],
    ) -> _CollapsibleSection | None:
        visible_fields = [field for field in section_fields if not self._is_automatic_date(field)]
        visible_fields = [
            field for field in visible_fields
            if str(field.get("id", "")).strip()
            and str(field.get("id", "")).strip() not in rendered_ids
        ]
        if not visible_fields:
            return None

        section = _CollapsibleSection(title)
        section_ids: list[str] = []
        for block in layout_blocks(visible_fields):
            block_type = str(block.get("type", "grid"))
            block_fields = [dict(field) for field in block.get("fields", [])]
            if block_type == "choice":
                widget = self._build_choice_block(block, block_fields, rendered_ids, section)
            elif block_type == "table":
                widget = self._build_table_block(block, block_fields, rendered_ids, section)
            elif block_type == "form_grid":
                widget = self._build_form_grid_block(
                    block, block_fields, rendered_ids, section
                )
            else:
                widget = self._build_grid_block(block_fields, rendered_ids, section)
            if widget is None:
                continue
            ids = [str(field.get("id", "")).strip() for field in block_fields]
            ids = [field_id for field_id in ids if field_id]
            section_ids.extend(ids)
            self.block_widgets.append((widget, ids))
            section.body_layout.addWidget(widget)

        if not section_ids:
            section.deleteLater()
            return None
        self.section_widgets.append((section, section_ids))
        return section

    def _register_field(
        self,
        field: dict[str, Any],
        rendered_ids: set[str],
        section: _CollapsibleSection,
        *,
        force_choice: bool = False,
    ) -> tuple[str, str, QWidget] | None:
        field_id = str(field.get("id", "")).strip()
        if not field_id or field_id in rendered_ids:
            return None
        rendered_ids.add(field_id)
        self.field_definitions[field_id] = field
        self.field_sections[field_id] = section

        field_type = infer_field_type(field_id, str(field.get("type", "text")))
        field["type"] = field_type
        widget = self._create_widget(field, force_choice=force_choice)
        widget.setProperty("baseToolTip", widget.toolTip())
        self.field_widgets[field_id] = widget
        self._connect_widget(widget, field_id)
        return field_id, field_type, widget

    def _build_grid_block(
        self,
        fields: list[dict[str, Any]],
        rendered_ids: set[str],
        section: _CollapsibleSection,
    ) -> QWidget | None:
        block = QFrame()
        block.setObjectName("formGridBlock")
        grid = QGridLayout(block)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        row = 0
        column = 0
        added = 0
        for field in fields:
            registered = self._register_field(field, rendered_ids, section)
            if registered is None:
                continue
            field_id, field_type, widget = registered
            added += 1

            label = str(field.get("label", field_id)).strip() or field_id
            required = bool(field.get("required", False)) and field_type != "checkbox"
            display_label = f"{label} *" if required else label
            container = self._create_field_card(
                field_id, display_label, widget, field_type, field
            )
            self.field_containers[field_id] = container

            full_width = self._should_span_full_width(field_id, field_type, field)
            if full_width:
                if column != 0:
                    row += 1
                    column = 0
                grid.addWidget(container, row, 0, 1, 2)
                row += 1
            else:
                grid.addWidget(container, row, column)
                column += 1
                if column >= 2:
                    row += 1
                    column = 0

        return block if added else None

    def _build_choice_block(
        self,
        block_definition: dict[str, Any],
        fields: list[dict[str, Any]],
        rendered_ids: set[str],
        section: _CollapsibleSection,
    ) -> QWidget | None:
        card = QFrame()
        card.setObjectName("choiceGroupCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 11)
        layout.setSpacing(8)

        group_label = str(block_definition.get("label", "")).strip()
        if not group_label:
            group_label = self._choice_group_label(fields)
        if group_label.casefold() == section.toggle.text().strip().casefold():
            group_label = "Selecione uma opção"
        required = any(
            bool(field.get("choice_required", False) or field.get("required", False))
            for field in fields
        )
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(6)
        title = QLabel(f"{group_label} *" if required else group_label)
        title.setObjectName("fieldLabel")
        title.setWordWrap(True)
        title_row.addWidget(title, 1)
        if fields:
            correction = self._create_correction_button(
                str(fields[0].get("id", "")),
                fields[0],
            )
            if correction is not None:
                title_row.addWidget(correction)
        layout.addLayout(title_row)

        helper = QLabel(
            "Clique em qualquer parte da alternativa. Somente uma opção pode ser selecionada."
        )
        helper.setObjectName("choiceGroupHint")
        helper.setWordWrap(True)
        layout.addWidget(helper)

        # A single_choice tag is stored as one dropdown field whose alternatives
        # are rendered as stacked, checkbox-like rows.
        if len(fields) == 1:
            field = fields[0]
            field_id = str(field.get("id", "")).strip()
            field_type = infer_field_type(field_id, str(field.get("type", "text")))
            if field_type == "dropdown":
                registered = self._register_field(
                    field, rendered_ids, section, force_choice=True
                )
                if registered is not None:
                    registered_id, _registered_type, widget = registered
                    if isinstance(widget, ExclusiveChoiceWidget):
                        layout.addWidget(widget)
                        self.field_containers[registered_id] = card

                        error_label = QLabel()
                        error_label.setObjectName("fieldValidationMessage")
                        error_label.setWordWrap(True)
                        error_label.hide()
                        layout.addWidget(error_label)
                        self.field_error_labels[registered_id] = error_label
                        return card

        options = QVBoxLayout()
        options.setContentsMargins(0, 0, 0, 0)
        options.setSpacing(7)
        button_group = QButtonGroup(card)
        button_group.setExclusive(True)
        self.button_groups.append(button_group)

        group_name = str(
            block_definition.get("group")
            or (fields[0].get("layout_group") if fields else "")
            or (fields[0].get("group") if fields else "")
        ).strip()
        added = 0
        for field in fields:
            registered = self._register_field(
                field, rendered_ids, section, force_choice=True
            )
            if registered is None:
                continue
            field_id, _field_type, widget = registered
            if not isinstance(widget, ChoiceOptionCheckBox):
                continue
            added += 1
            button_group.addButton(widget)
            options.addWidget(widget)
            self.field_containers[field_id] = card
            self.checkbox_groups.setdefault(group_name, []).append(field_id)
            self.field_error_labels[field_id] = QLabel()

        layout.addLayout(options)

        error_label = QLabel()
        error_label.setObjectName("fieldValidationMessage")
        error_label.setWordWrap(True)
        error_label.hide()
        layout.addWidget(error_label)
        for field in fields:
            field_id = str(field.get("id", "")).strip()
            if field_id in self.field_widgets:
                self.field_error_labels[field_id] = error_label

        return card if added else None

    def _build_form_grid_block(
        self,
        block_definition: dict[str, Any],
        fields: list[dict[str, Any]],
        rendered_ids: set[str],
        section: _CollapsibleSection,
    ) -> QWidget | None:
        """Render a form-like Word table without inventing table headers.

        Each DOCX row remains one visual form row. Horizontal merges are
        represented by column spans, while static cells become read-only
        contextual information instead of duplicated field headings.
        """

        outer = QFrame()
        outer.setObjectName("formDocumentGridCard")
        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(8)

        group_label = str(block_definition.get("label", "")).strip()
        if group_label and group_label.casefold() != section.toggle.text().casefold():
            title = QLabel(group_label)
            title.setObjectName("fieldLabel")
            title.setWordWrap(True)
            outer_layout.addWidget(title)

        grid_frame = QFrame()
        grid_frame.setObjectName("formDocumentGrid")
        grid = QGridLayout(grid_frame)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)

        grid_columns = max(
            [
                self._safe_int(field.get("layout_grid_columns"), 1)
                for field in fields
            ]
            + [
                self._safe_int(row.get("layout_grid_columns"), 1)
                for row in block_definition.get("static_rows", [])
                if isinstance(row, dict)
            ]
            + [1]
        )
        grid_columns = max(1, min(grid_columns, 12))
        sheet_mode = any(
            str(field.get("layout_presentation", "")).strip().casefold() == "sheet"
            for field in fields
        )
        if sheet_mode:
            grid_frame.setObjectName("formDocumentSheet")
            grid.setHorizontalSpacing(0)
            grid.setVerticalSpacing(0)
        for column in range(grid_columns):
            grid.setColumnStretch(column, 1)

        field_rows: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
        for index, field in enumerate(fields):
            row_key = str(field.get("layout_row", f"row_{index}")).strip() or f"row_{index}"
            field_rows.setdefault(row_key, []).append(field)

        row_static_cells: dict[str, list[dict[str, Any]]] = {}
        for cell in block_definition.get("row_static_cells", []) or []:
            if not isinstance(cell, dict):
                continue
            row_key = str(cell.get("layout_row", "")).strip()
            if row_key:
                row_static_cells.setdefault(row_key, []).append(cell)

        items: list[tuple[int, int, str, Any]] = []
        # Static cells from one physical Word row must stay on one visual row.
        # Older metadata stored each static cell independently, which made a
        # four-cell row render as a diagonal staircase. Group by explicit
        # ``layout_row`` when available and fall back to ``layout_order`` so
        # existing automatically-created models are repaired too.
        for static_row in group_form_grid_static_rows(
            block_definition.get("static_rows", []) or []
        ):
            items.append(
                (
                    self._safe_int(static_row.get("layout_order"), 0),
                    0,
                    "static_row",
                    list(static_row.get("cells", []) or []),
                )
            )
        for sequence, (row_key, row_fields) in enumerate(field_rows.items()):
            order = min(
                self._safe_int(field.get("layout_order"), sequence)
                for field in row_fields
            )
            items.append((order, 1, "fields", (row_key, row_fields)))
        items.sort(key=lambda item: (item[0], item[1]))

        visual_row = 0
        added = 0
        for _order, _kind_order, item_type, payload in items:
            if item_type == "static_row":
                row_added = False
                for static_cell in sorted(
                    payload,
                    key=lambda item: self._safe_int(item.get("layout_column_index"), 0),
                ):
                    text = str(static_cell.get("text", "")).strip()
                    if not text:
                        continue
                    start = self._safe_int(static_cell.get("layout_column_index"), 0)
                    span = self._safe_int(static_cell.get("layout_column_span"), grid_columns)
                    start = max(0, min(start, grid_columns - 1))
                    span = max(1, min(span, grid_columns - start))
                    grid.addWidget(
                        self._create_form_grid_static(text, sheet=sheet_mode),
                        visual_row,
                        start,
                        1,
                        span,
                    )
                    row_added = True
                if row_added:
                    visual_row += 1
                continue

            row_key, row_payload = payload
            row_fields = list(row_payload)
            cells: OrderedDict[tuple[int, int], list[dict[str, Any]]] = OrderedDict()
            for field in sorted(
                row_fields,
                key=lambda item: self._safe_int(item.get("layout_column_index"), 0),
            ):
                start = self._safe_int(field.get("layout_column_index"), 0)
                span = self._safe_int(field.get("layout_column_span"), 1)
                start = max(0, min(start, grid_columns - 1))
                span = max(1, min(span, grid_columns - start))
                cells.setdefault((start, span), []).append(field)

            row_added = False
            for static_cell in sorted(
                row_static_cells.get(str(row_key), []),
                key=lambda item: self._safe_int(item.get("layout_column_index"), 0),
            ):
                text = str(static_cell.get("text", "")).strip()
                if not text:
                    continue
                start = self._safe_int(static_cell.get("layout_column_index"), 0)
                span = self._safe_int(static_cell.get("layout_column_span"), 1)
                start = max(0, min(start, grid_columns - 1))
                span = max(1, min(span, grid_columns - start))
                grid.addWidget(
                    self._create_form_grid_static(text),
                    visual_row,
                    start,
                    1,
                    span,
                )
                row_added = True

            for (start, span), cell_fields in cells.items():
                # Keep an exclusive checkbox group that originally lived in one
                # Word cell together.  Rendering the options as ordinary fields
                # loses the question/prompt (for example ``Há impedimento
                # conhecido? ☐ Sim ☐ Não``) and also drops exclusivity.
                if self._is_embedded_choice_cell(cell_fields):
                    cell_container, cell_added = self._create_embedded_choice_form_grid_cell(
                        cell_fields,
                        rendered_ids,
                        section,
                    )
                    if cell_container is None or not cell_added:
                        continue
                    grid.addWidget(cell_container, visual_row, start, 1, span)
                    added += cell_added
                    row_added = True
                    continue

                cell_container = QFrame()
                cell_container.setObjectName(
                    "formDocumentSheetCell" if sheet_mode else "formDocumentGridCell"
                )
                cell_layout = QVBoxLayout(cell_container)
                cell_layout.setContentsMargins(0, 0, 0, 0)
                cell_layout.setSpacing(0 if sheet_mode else 8)
                cell_added = 0

                for field in cell_fields:
                    registered = self._register_field(field, rendered_ids, section)
                    if registered is None:
                        continue
                    field_id, field_type, widget = registered
                    label = str(field.get("label", field_id)).strip() or field_id
                    required = bool(field.get("required", False)) and field_type != "checkbox"
                    display_label = f"{label} *" if required else label
                    card = self._create_field_card(
                        field_id,
                        display_label,
                        widget,
                        field_type,
                        field,
                        suppress_label=sheet_mode,
                    )
                    self.field_containers[field_id] = card
                    cell_layout.addWidget(card)
                    cell_added += 1
                    added += 1

                if not cell_added:
                    cell_container.deleteLater()
                    continue
                grid.addWidget(cell_container, visual_row, start, 1, span)
                row_added = True

            if row_added:
                visual_row += 1

        if not added:
            return None
        outer_layout.addWidget(grid_frame)
        return outer

    def _create_embedded_choice_form_grid_cell(
        self,
        fields: list[dict[str, Any]],
        rendered_ids: set[str],
        section: _CollapsibleSection,
    ) -> tuple[QFrame | None, int]:
        """Render one exclusive choice together with its original question.

        Automatic detection can find ``Question? ☐ A ☐ B`` inside a single
        Word table cell.  Layout inference then correctly embeds those fields
        into a form-grid row, but the option labels alone are not enough: the
        question itself is the semantic label of the group.
        """

        cell = QFrame()
        cell.setObjectName("formDocumentGridCell")
        root = QVBoxLayout(cell)
        root.setContentsMargins(10, 7, 10, 9)
        root.setSpacing(7)

        first = fields[0] if fields else {}
        group_label = (
            str(first.get("choice_group_label", "")).strip()
            or str(first.get("layout_group_label", "")).strip()
            or self._choice_group_label(fields)
        )
        required = any(
            bool(field.get("choice_required", False) or field.get("required", False))
            for field in fields
        )
        if group_label:
            title_row = QHBoxLayout()
            title_row.setContentsMargins(0, 0, 0, 0)
            title_row.setSpacing(6)
            title = QLabel(f"{group_label} *" if required else group_label)
            title.setObjectName("fieldLabel")
            title.setWordWrap(True)
            title_row.addWidget(title, 1)
            correction = self._create_correction_button(
                str(first.get("id", "")),
                first,
            )
            if correction is not None:
                title_row.addWidget(correction)
            root.addLayout(title_row)

        # Short alternatives such as Sim/Não read better side by side.  Long
        # legal/administrative options stay stacked so their full text remains
        # clear and the whole label is still clickable.
        option_labels = [str(field.get("label", "")).strip() for field in fields]
        use_vertical = any(len(label) > 48 for label in option_labels)
        options = QVBoxLayout() if use_vertical else QHBoxLayout()
        options.setContentsMargins(0, 0, 0, 0)
        options.setSpacing(10)

        button_group = QButtonGroup(cell)
        button_group.setExclusive(True)
        self.button_groups.append(button_group)

        group_name = str(
            first.get("group") or first.get("layout_group") or ""
        ).strip()
        added = 0
        for source_field in fields:
            field = dict(source_field)
            field["compact_choice"] = True
            registered = self._register_field(field, rendered_ids, section)
            if registered is None:
                continue
            field_id, _field_type, widget = registered
            if not isinstance(widget, ReadableCheckBox):
                continue
            button_group.addButton(widget)
            options.addWidget(widget)
            self.field_containers[field_id] = cell
            self.checkbox_groups.setdefault(group_name, []).append(field_id)
            added += 1

        if not added:
            cell.deleteLater()
            return None, 0

        if not use_vertical:
            options.addStretch(1)
        root.addLayout(options)

        error = QLabel()
        error.setObjectName("fieldValidationMessage")
        error.setWordWrap(True)
        error.hide()
        root.addWidget(error)
        for field in fields:
            field_id = str(field.get("id", "")).strip()
            if field_id in self.field_widgets:
                self.field_error_labels[field_id] = error

        return cell, added

    @staticmethod
    def _create_form_grid_static(text: str, *, sheet: bool = False) -> QFrame:
        frame = QFrame()
        frame.setObjectName(
            "formDocumentSheetStatic" if sheet else "formDocumentGridStatic"
        )
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(11, 8, 11, 8)
        layout.setSpacing(2)

        label_text = ""
        value_text = str(text).strip()
        if ":" in value_text:
            possible_label, possible_value = value_text.split(":", 1)
            if possible_label.strip() and possible_value.strip():
                label_text = possible_label.strip()
                value_text = possible_value.strip()

        if label_text:
            label = QLabel(label_text)
            label.setObjectName("formDocumentGridStaticLabel")
            label.setWordWrap(True)
            layout.addWidget(label)

        value = QLabel(value_text)
        value.setObjectName(
            "formDocumentSheetHeaderLabel" if sheet else "formDocumentGridStaticValue"
        )
        value.setWordWrap(True)
        value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(value)
        return frame

    def _build_table_block(
        self,
        block_definition: dict[str, Any],
        fields: list[dict[str, Any]],
        rendered_ids: set[str],
        section: _CollapsibleSection,
    ) -> QWidget | None:
        outer = QFrame()
        outer.setObjectName("formTableCard")
        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(6)

        group_label = str(block_definition.get("label", "")).strip()
        if group_label and group_label.casefold() != section.toggle.text().casefold():
            title = QLabel(group_label)
            title.setObjectName("fieldLabel")
            title.setWordWrap(True)
            outer_layout.addWidget(title)

        table_frame = QFrame()
        table_frame.setObjectName("formTableGrid")
        grid = QGridLayout(table_frame)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(0)
        grid.setVerticalSpacing(0)

        rows: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
        columns: dict[tuple[int, str], str] = {}
        for index, field in enumerate(fields):
            row_key = str(field.get("layout_row", f"row_{index}")).strip() or f"row_{index}"
            rows.setdefault(row_key, []).append(field)
            column_index = self._safe_int(field.get("layout_column_index"), index + 1)
            column_label = str(
                field.get("layout_column") or field.get("label") or field.get("id")
            ).strip()
            columns[(column_index, column_label.casefold())] = column_label

        ordered_columns = sorted(columns.items(), key=lambda item: (item[0][0], item[0][1]))
        column_keys = [key for key, _label in ordered_columns]
        column_labels = [label for _key, label in ordered_columns]
        has_row_labels = any(
            str(field.get("layout_row_label", "")).strip()
            for row_fields in rows.values()
            for field in row_fields
        )
        column_offset = 1 if has_row_labels else 0

        row_header_label = next(
            (
                str(field.get("layout_row_header_label", "")).strip()
                for row_fields in rows.values()
                for field in row_fields
                if str(field.get("layout_row_header_label", "")).strip()
            ),
            "Função",
        )

        if has_row_labels:
            header = QLabel(row_header_label)
            header.setObjectName("formTableHeader")
            header.setWordWrap(True)
            grid.addWidget(header, 0, 0)
            grid.setColumnStretch(0, 1)
        for index, label in enumerate(column_labels):
            header = QLabel(label)
            header.setObjectName("formTableHeader")
            header.setWordWrap(True)
            grid.addWidget(header, 0, index + column_offset)
            grid.setColumnStretch(index + column_offset, 1)

        added = 0
        for row_number, (_row_key, row_fields) in enumerate(rows.items(), start=1):
            if has_row_labels:
                row_label = next(
                    (
                        str(field.get("layout_row_label", "")).strip()
                        for field in row_fields
                        if str(field.get("layout_row_label", "")).strip()
                    ),
                    "",
                )
                label_widget = QLabel(row_label)
                label_widget.setObjectName("formTableRowHeader")
                label_widget.setWordWrap(True)
                grid.addWidget(label_widget, row_number, 0)

            by_column: dict[tuple[int, str], list[dict[str, Any]]] = {}
            for field in row_fields:
                key = (
                    self._safe_int(field.get("layout_column_index"), 0),
                    str(
                        field.get("layout_column")
                        or field.get("label")
                        or field.get("id")
                    ).strip().casefold(),
                )
                by_column.setdefault(key, []).append(field)

            for column_number, key in enumerate(column_keys, start=column_offset):
                cell_fields = by_column.get(key, [])
                if not cell_fields:
                    spacer = QFrame()
                    spacer.setObjectName("formTableEmptyCell")
                    grid.addWidget(spacer, row_number, column_number)
                    continue

                if self._is_embedded_choice_cell(cell_fields):
                    cell, cell_added = self._create_embedded_choice_table_cell(
                        cell_fields,
                        rendered_ids,
                        section,
                    )
                    added += cell_added
                else:
                    cell, cell_added = self._create_stacked_table_cell(
                        cell_fields,
                        rendered_ids,
                        section,
                    )
                    added += cell_added
                if cell is None:
                    continue
                grid.addWidget(cell, row_number, column_number)

        scroll = QScrollArea()
        scroll.setObjectName("formTableScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(table_frame)
        scroll.setMinimumHeight(table_frame.sizeHint().height() + 8)
        scroll.setMaximumHeight(table_frame.sizeHint().height() + 22)
        outer_layout.addWidget(scroll)
        return outer if added else None

    @staticmethod
    def _is_embedded_choice_cell(fields: list[dict[str, Any]]) -> bool:
        if len(fields) < 2:
            return False
        groups = {
            str(field.get("group", "")).strip()
            for field in fields
            if str(field.get("group", "")).strip()
        }
        if len(groups) != 1:
            return False
        return all(
            infer_field_type(str(field.get("id", "")), str(field.get("type", "text")))
            == "checkbox"
            and str(field.get("selection", "")).strip().casefold()
            in {"single", "exclusive", "radio"}
            for field in fields
        )

    def _create_embedded_choice_table_cell(
        self,
        fields: list[dict[str, Any]],
        rendered_ids: set[str],
        section: _CollapsibleSection,
    ) -> tuple[QFrame | None, int]:
        """Render an exclusive checkbox group inside its original table cell."""

        cell = QFrame()
        cell.setObjectName("formTableCell")
        root = QVBoxLayout(cell)
        root.setContentsMargins(7, 6, 7, 6)
        root.setSpacing(4)

        options = QHBoxLayout()
        options.setContentsMargins(0, 0, 0, 0)
        options.setSpacing(12)
        button_group = QButtonGroup(cell)
        button_group.setExclusive(True)
        self.button_groups.append(button_group)

        group_name = str(fields[0].get("group", "")).strip()
        added = 0
        for field in fields:
            field = dict(field)
            field["compact_choice"] = True
            registered = self._register_field(field, rendered_ids, section)
            if registered is None:
                continue
            field_id, _field_type, widget = registered
            if not isinstance(widget, ReadableCheckBox):
                continue
            button_group.addButton(widget)
            options.addWidget(widget)
            self.field_containers[field_id] = cell
            self.checkbox_groups.setdefault(group_name, []).append(field_id)
            added += 1

        if not added:
            cell.deleteLater()
            return None, 0

        options.addStretch(1)
        root.addLayout(options)

        error = QLabel()
        error.setObjectName("fieldValidationMessage")
        error.setWordWrap(True)
        error.hide()
        root.addWidget(error)
        for field in fields:
            field_id = str(field.get("id", "")).strip()
            if field_id in self.field_widgets:
                self.field_error_labels[field_id] = error
        return cell, added

    def _create_stacked_table_cell(
        self,
        fields: list[dict[str, Any]],
        rendered_ids: set[str],
        section: _CollapsibleSection,
    ) -> tuple[QFrame | None, int]:
        cell = QFrame()
        cell.setObjectName("formTableCell")
        layout = QVBoxLayout(cell)
        layout.setContentsMargins(7, 6, 7, 6)
        layout.setSpacing(6)

        added = 0
        for field in fields:
            registered = self._register_field(field, rendered_ids, section)
            if registered is None:
                continue
            field_id, field_type, widget = registered
            layout.addWidget(widget)
            self.field_containers[field_id] = cell
            hint = validation_hint(field)
            if hint:
                widget.setToolTip(hint)
                widget.setProperty("baseToolTip", hint)
            error = QLabel()
            error.setObjectName("fieldValidationMessage")
            error.setWordWrap(True)
            error.hide()
            layout.addWidget(error)
            self.field_error_labels[field_id] = error
            added += 1

        if not added:
            cell.deleteLater()
            return None, 0
        return cell, added

    def _create_table_cell(
        self,
        field_id: str,
        widget: QWidget,
        field_type: str,
        field: dict[str, Any],
    ) -> QFrame:
        cell = QFrame()
        cell.setObjectName("formTableCell")
        layout = QVBoxLayout(cell)
        layout.setContentsMargins(7, 6, 7, 6)
        layout.setSpacing(4)
        layout.addWidget(widget)

        hint = validation_hint(field)
        if hint:
            widget.setToolTip(hint)
            widget.setProperty("baseToolTip", hint)

        error = QLabel()
        error.setObjectName("fieldValidationMessage")
        error.setWordWrap(True)
        error.hide()
        layout.addWidget(error)
        self.field_error_labels[field_id] = error
        return cell

    @staticmethod
    def _choice_group_label(fields: list[dict[str, Any]]) -> str:
        labels = [str(field.get("label", "")).strip() for field in fields]
        tokenized = [label.split() for label in labels if label]
        common: list[str] = []
        if tokenized:
            for parts in zip(*tokenized):
                if len({part.casefold() for part in parts}) == 1:
                    common.append(parts[0])
                else:
                    break
        result = " ".join(common).strip(" :：–—-")
        return result if len(result) >= 3 else "Escolha uma opção"

    @staticmethod
    def _safe_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return int(default)

    @staticmethod
    def _is_automatic_date(field: dict[str, Any]) -> bool:
        field_id = str(field.get("id", "")).strip()
        field_type = infer_field_type(field_id, str(field.get("type", "text")))
        return field_type == "date" and bool(field.get("automatic", True))

    def labels(self) -> dict[str, str]:
        return {
            str(field.get("id", "")): str(field.get("label", field.get("id", "")))
            for field in self.fields
            if str(field.get("id", ""))
        }

    def collect_values(self) -> dict[str, Any]:
        values = self.current_values()
        for field in self.fields:
            field_id = str(field.get("id", "")).strip()
            if not field_id:
                continue
            visible = self._field_is_visible(field_id)
            field_type = infer_field_type(field_id, str(field.get("type", "text")))
            if not visible:
                values[field_id] = (
                    False
                    if field_type == "checkbox"
                    else []
                    if field_type == "repeatable_table"
                    else ""
                )

        issues = self.validation_issues(values)
        if issues:
            self.reveal_all_validation()
            errors = [str(issue.get("message", "")) for issue in issues if str(issue.get("message", ""))]
            raise ValueError("Corrija os seguintes campos:\n- " + "\n- ".join(errors))
        return values

    def current_values(self) -> dict[str, Any]:
        values: dict[str, Any] = {}
        today = date.today().strftime("%d/%m/%Y")
        for field in self.fields:
            field_id = str(field.get("id", "")).strip()
            if not field_id:
                continue
            field_type = infer_field_type(field_id, str(field.get("type", "text")))
            if field_type == "date" and bool(field.get("automatic", True)):
                values[field_id] = today
                continue

            widget = self.field_widgets.get(field_id)
            if isinstance(widget, QAbstractButton):
                values[field_id] = widget.isChecked()
            elif isinstance(widget, (SearchableDropdown, ExclusiveChoiceWidget)):
                values[field_id] = widget.current_value().strip()
            elif isinstance(widget, QPlainTextEdit):
                values[field_id] = widget.toPlainText().strip()
            elif isinstance(widget, RepeatableTableWidget):
                values[field_id] = widget.rows()
            elif isinstance(widget, SmartLineEdit):
                values[field_id] = widget.text().strip()
            elif isinstance(widget, QDateEdit):
                values[field_id] = widget.date().toString("dd/MM/yyyy")
            else:
                values[field_id] = ""
        return values

    def validation_issues(self, values: dict[str, Any] | None = None) -> list[dict[str, str]]:
        resolved_values = dict(values) if values is not None else self.current_values()
        issues: list[dict[str, str]] = []

        for field in self.fields:
            field_id = str(field.get("id", "")).strip()
            if not field_id:
                continue
            if not self._field_is_visible(field_id):
                continue
            error = validate_field(field, resolved_values.get(field_id))
            if not error:
                continue
            field_type = infer_field_type(field_id, str(field.get("type", "text")))
            value = resolved_values.get(field_id)
            empty = field_type != "checkbox" and not str(value or "").strip()
            label = str(field.get("label", field_id)).strip() or field_id
            issues.append(
                {
                    "field_id": field_id,
                    "label": label,
                    "message": str(error),
                    "kind": "missing" if bool(field.get("required", False)) and empty else "invalid",
                }
            )

        choice_groups: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
        for field in self.fields:
            if not bool(field.get("choice_required", False)):
                continue
            group = str(field.get("group") or field.get("layout_group") or "").strip()
            if group:
                choice_groups.setdefault(group, []).append(field)
        existing_ids = {issue["field_id"] for issue in issues}
        for _group, group_fields in choice_groups.items():
            visible_fields = [
                field
                for field in group_fields
                if self._field_is_visible(str(field.get("id", "")))
            ]
            if not visible_fields:
                continue
            if any(bool(resolved_values.get(str(field.get("id", "")))) for field in visible_fields):
                continue
            first = visible_fields[0]
            field_id = str(first.get("id", ""))
            if field_id in existing_ids:
                continue
            label = (
                str(first.get("choice_group_label", "")).strip()
                or str(first.get("layout_group_label", "")).strip()
                or self._choice_group_label(visible_fields)
            )
            issues.append(
                {
                    "field_id": field_id,
                    "label": label,
                    "message": f"{label} é obrigatório.",
                    "kind": "missing",
                }
            )
        return issues

    def set_validation_issues(self, issues: list[dict[str, str]]) -> None:
        self._last_validation_issues = [dict(issue) for issue in issues]
        issue_map = {
            str(issue.get("field_id", "")): issue
            for issue in issues
            if str(issue.get("field_id", ""))
        }

        fields_by_container: dict[QWidget, list[str]] = {}
        for field_id, container in self.field_containers.items():
            fields_by_container.setdefault(container, []).append(field_id)

        for container, field_ids in fields_by_container.items():
            displayed_issue: dict[str, str] | None = None
            for field_id in field_ids:
                issue = issue_map.get(field_id)
                if issue and (
                    self._show_all_validation
                    or field_id in self._touched_fields
                    or field_id in self._revealed_fields
                ):
                    displayed_issue = issue
                    break
            state = str(displayed_issue.get("kind", "invalid")) if displayed_issue else ""
            message = str(displayed_issue.get("message", "")) if displayed_issue else ""
            container.setProperty("validationState", state)
            container.setToolTip(message)
            self._repolish(container)

            for field_id in field_ids:
                error_label = self.field_error_labels.get(field_id)
                if error_label is not None:
                    error_label.setText(message)
                    error_label.setVisible(bool(message))

        for field_id, widget in self.field_widgets.items():
            issue = issue_map.get(field_id)
            should_show = bool(issue) and (
                self._show_all_validation
                or field_id in self._touched_fields
                or field_id in self._revealed_fields
            )
            state = str(issue.get("kind", "invalid")) if should_show and issue else ""
            message = str(issue.get("message", "")) if should_show and issue else ""
            widget.setProperty("validationState", state)
            widget.setToolTip(
                message
                or str(widget.property("baseToolTip") or "")
            )
            self._repolish(widget)

    def reveal_validation_for(self, field_id: str) -> None:
        field_id = str(field_id).strip()
        if not field_id:
            return
        self._revealed_fields.add(field_id)
        self.set_validation_issues(self._last_validation_issues)

    def reveal_all_validation(self) -> None:
        self._show_all_validation = True
        self.set_validation_issues(self._last_validation_issues)

    def reset_validation_visibility(self) -> None:
        self._touched_fields.clear()
        self._revealed_fields.clear()
        self._last_validation_issues = []
        self._show_all_validation = False

    def focus_field(self, field_id: str) -> QWidget | None:
        field_id = str(field_id).strip()
        section = self.field_sections.get(field_id)
        if section is not None:
            section.expand()
        widget = self.field_widgets.get(field_id)
        if widget is None:
            return self.field_containers.get(field_id)
        widget.setFocus(Qt.FocusReason.OtherFocusReason)
        if isinstance(widget, SmartLineEdit):
            widget.selectAll()
        elif isinstance(widget, QPlainTextEdit):
            widget.selectAll()
        elif isinstance(widget, (SearchableDropdown, ExclusiveChoiceWidget)):
            widget.focus_selector()
        elif isinstance(widget, RepeatableTableWidget):
            widget.focus_table()
        container = self.field_containers.get(field_id)
        return container if container is not None else widget

    def has_meaningful_values(self, values: dict[str, Any] | None = None) -> bool:
        resolved_values = dict(values) if values is not None else self.current_values()
        for field in self.fields:
            if self._is_automatic_date(field):
                continue
            field_id = str(field.get("id", "")).strip()
            if not field_id:
                continue
            value = resolved_values.get(field_id)
            if isinstance(value, bool):
                if value:
                    return True
            elif isinstance(value, list):
                if any(
                    isinstance(row, dict)
                    and any(
                        bool(cell) if isinstance(cell, bool) else bool(str(cell or "").strip())
                        for key, cell in row.items()
                        if not str(key).startswith("__")
                    )
                    for row in value
                ):
                    return True
            elif str(value or "").strip():
                return True
        return False

    def field_container(self, field_id: str) -> QWidget | None:
        return self.field_containers.get(str(field_id).strip())

    def set_values(self, values: dict[str, Any], *, emit_signal: bool = True) -> None:
        self._updating = True
        try:
            for field_id, widget in self.field_widgets.items():
                if field_id not in values:
                    continue
                value = values[field_id]
                if isinstance(widget, QAbstractButton):
                    widget.setChecked(bool(value))
                elif isinstance(widget, (SearchableDropdown, ExclusiveChoiceWidget)):
                    widget.set_value(value)
                elif isinstance(widget, QPlainTextEdit):
                    widget.setPlainText(str(value or ""))
                elif isinstance(widget, RepeatableTableWidget):
                    widget.set_rows(value if isinstance(value, list) else [], emit_signal=False)
                elif isinstance(widget, SmartLineEdit):
                    widget.set_value(value)
                elif isinstance(widget, QDateEdit):
                    parsed = QDate.fromString(str(value or ""), "dd/MM/yyyy")
                    if parsed.isValid():
                        widget.setDate(parsed)
        finally:
            self._updating = False
        self._refresh_visibility()
        self._update_progress()
        if emit_signal:
            self.values_changed.emit()

    def apply_profile(self, profile_values: dict[str, Any]) -> int:
        mapped = resolve_profile_values(self.fields, profile_values)
        self.set_values(mapped)
        return len(mapped)

    def profile_payload(self) -> dict[str, Any]:
        return build_profile_payload(self.fields, self.current_values())

    def clear_values(self) -> None:
        self._updating = True
        try:
            for widget in self.field_widgets.values():
                if isinstance(widget, QAbstractButton):
                    widget.setChecked(False)
                elif isinstance(widget, (SearchableDropdown, ExclusiveChoiceWidget)):
                    widget.clear()
                elif isinstance(widget, QPlainTextEdit):
                    widget.clear()
                elif isinstance(widget, RepeatableTableWidget):
                    widget.clear(emit_signal=False)
                elif isinstance(widget, SmartLineEdit):
                    widget.clear()
                elif isinstance(widget, QDateEdit):
                    widget.setDate(QDate.currentDate())
        finally:
            self._updating = False
        self.reset_validation_visibility()
        self._refresh_visibility()
        self._update_progress()
        self.values_changed.emit()

    def load_sample_data(self) -> None:
        values = {
            str(field.get("id", "")): sample_value(field)
            for field in self.fields
            if str(field.get("id", ""))
        }
        self.set_values(values)

    def _create_widget(self, field: dict[str, Any], *, force_choice: bool = False) -> QWidget:
        field_id = str(field.get("id", ""))
        field_type = infer_field_type(field_id, str(field.get("type", "text")))
        label = str(field.get("label", field_id))

        if field_type == "checkbox":
            if bool(field.get("compact_choice", False)):
                checkbox = ReadableCheckBox()
                checkbox.setObjectName("embeddedChoiceCheckBox")
                checkbox.setText(label)
                return checkbox
            if force_choice or str(field.get("selection", "")).casefold() in {"single", "exclusive", "radio"}:
                return ChoiceOptionCheckBox(label)
            checkbox = ReadableCheckBox()
            checkbox.setObjectName("declarationCheckBox")
            checkbox.setText(label)
            return checkbox
        if field_type == "dropdown":
            single_choice = str(field.get("selection", "")).casefold() in {
                "single", "exclusive", "radio"
            }
            if force_choice or single_choice or str(field.get("layout", "")).casefold() == "choice":
                return ExclusiveChoiceWidget(
                    field.get("options", []),
                    required=bool(field.get("required", False) or field.get("choice_required", False)),
                )
            return SearchableDropdown(field.get("options", []), title=label)
        if field_type == "repeatable_table":
            return RepeatableTableWidget(field)
        if field_type == "multiline":
            editor = QPlainTextEdit()
            editor.setMinimumHeight(int(field.get("height", 105) or 105))
            editor.setPlaceholderText(str(field.get("placeholder", "Informe os dados completos...")))
            return editor
        if field_type == "date":
            editor = QDateEdit(QDate.currentDate())
            editor.setCalendarPopup(True)
            editor.setDisplayFormat("dd/MM/yyyy")
            return editor
        editor = SmartLineEdit(field_type)
        editor.setPlaceholderText(str(field.get("placeholder", self._placeholder_for(field_id, field_type))))
        return editor

    def _create_field_card(
        self,
        field_id: str,
        label: str,
        widget: QWidget,
        field_type: str,
        field: dict[str, Any],
        *,
        suppress_label: bool = False,
    ) -> QFrame:
        card = QFrame()
        card.setObjectName("fieldCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 7, 10, 9)
        layout.setSpacing(6)
        help_text = self._field_help_text(field)
        help_title = str(field.get("help_title", label.rstrip(" *"))).strip() or label.rstrip(" *")

        if field_type != "checkbox":
            correction = self._create_correction_button(field_id, field)
            if not suppress_label:
                label_row = QHBoxLayout()
                label_row.setContentsMargins(0, 0, 0, 0)
                label_row.setSpacing(6)
                label_widget = QLabel(label)
                label_widget.setObjectName("fieldLabel")
                label_widget.setWordWrap(True)
                label_row.addWidget(label_widget, 1)
                if help_text:
                    label_row.addWidget(HelpIconButton(help_title, f"<p>{escape(help_text)}</p>"))
                if correction is not None:
                    label_row.addWidget(correction)
                layout.addLayout(label_row)
            elif help_text or correction is not None:
                control_row = QHBoxLayout()
                control_row.setContentsMargins(0, 0, 0, 0)
                control_row.setSpacing(6)
                control_row.addStretch(1)
                if help_text:
                    control_row.addWidget(HelpIconButton(help_title, f"<p>{escape(help_text)}</p>"))
                if correction is not None:
                    control_row.addWidget(correction)
                layout.addLayout(control_row)
            layout.addWidget(widget)
        else:
            checkbox_row = QHBoxLayout()
            checkbox_row.setContentsMargins(0, 0, 0, 0)
            checkbox_row.setSpacing(6)
            checkbox_row.addWidget(widget, 1)
            if help_text:
                checkbox_row.addWidget(HelpIconButton(help_title, f"<p>{escape(help_text)}</p>"))
            correction = self._create_correction_button(field_id, field)
            if correction is not None:
                checkbox_row.addWidget(correction)
            layout.addLayout(checkbox_row)

        hint_text = validation_hint(field)
        if hint_text:
            hint_label = QLabel(hint_text)
            hint_label.setObjectName("fieldFormatHint")
            hint_label.setWordWrap(True)
            layout.addWidget(hint_label)
            self.field_hint_labels[field_id] = hint_label

        error_label = QLabel()
        error_label.setObjectName("fieldValidationMessage")
        error_label.setWordWrap(True)
        error_label.hide()
        layout.addWidget(error_label)
        self.field_error_labels[field_id] = error_label
        return card

    def _create_correction_button(
        self,
        field_id: str,
        field: dict[str, Any],
    ) -> QToolButton | None:
        if not is_assisted_detection_field(field):
            return None
        target = str(field_id).strip()
        if not target:
            return None
        button = QToolButton()
        button.setObjectName("fieldCorrectionButton")
        button.setText("Corrigir")
        button.setToolTip(
            "Abrir este campo no editor do modelo. Use quando a detecção assistida "
            "identificar um rótulo, tipo ou organização incorretamente."
        )
        button.clicked.connect(
            lambda _checked=False, key=target: self.edit_field_requested.emit(key)
        )
        return button

    @staticmethod
    def _field_help_text(field: dict[str, Any]) -> str:
        for key in ("help_text", "help", "guidance", "description"):
            value = str(field.get(key, "")).strip()
            if value:
                example = str(field.get("example", "")).strip()
                return f"{value} Exemplo: {example}" if example else value
        if str(field.get("type", "")) == "repeatable_table":
            return (
                "Adicione uma linha para cada item da contratação. Também é possível "
                "duplicar, reordenar ou colar dados tabulados copiados do Excel."
            )
        return ""

    def _connect_widget(self, widget: QWidget, field_id: str) -> None:
        self._install_touch_filter(widget, field_id)
        callback = lambda *_args, key=field_id: self._widget_changed(key)
        if isinstance(widget, QAbstractButton):
            widget.toggled.connect(callback)
        elif isinstance(widget, (SearchableDropdown, ExclusiveChoiceWidget)):
            widget.value_changed.connect(callback)
        elif isinstance(widget, QPlainTextEdit):
            widget.textChanged.connect(callback)
        elif isinstance(widget, RepeatableTableWidget):
            widget.values_changed.connect(callback)
        elif isinstance(widget, SmartLineEdit):
            widget.value_changed.connect(callback)
        elif isinstance(widget, QDateEdit):
            widget.dateChanged.connect(callback)

    def _install_touch_filter(self, widget: QWidget, field_id: str) -> None:
        for target in [widget, *widget.findChildren(QWidget)]:
            target.setProperty("documentFormFieldId", field_id)
            target.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.FocusOut:
            field_id = str(watched.property("documentFormFieldId") or "").strip()
            if field_id and not self._updating:
                self._touched_fields.add(field_id)
                self.set_validation_issues(self._last_validation_issues)
        return super().eventFilter(watched, event)

    def _widget_changed(self, field_id: str) -> None:
        if self._updating:
            return
        self._touched_fields.add(str(field_id))
        self._refresh_visibility()
        self._update_progress()
        self.values_changed.emit()

    def _refresh_visibility(self) -> None:
        values = self.current_values()
        container_visibility: dict[QWidget, bool] = {}

        for field_id, field in self.field_definitions.items():
            visible = condition_matches(field.get("visible_when"), values)
            widget = self.field_widgets.get(field_id)
            if widget is not None:
                widget.setVisible(visible)
            container = self.field_containers.get(field_id)
            if container is not None:
                container_visibility[container] = (
                    container_visibility.get(container, False) or visible
                )

        for container, visible in container_visibility.items():
            container.setVisible(visible)

        for widget, field_ids in self.block_widgets:
            widget.setVisible(any(self._field_is_visible(field_id) for field_id in field_ids))
        for section, field_ids in self.section_widgets:
            section.setVisible(any(self._field_is_visible(field_id) for field_id in field_ids))
        self._update_progress()

    def _field_is_visible(self, field_id: str) -> bool:
        field_id = str(field_id).strip()
        if not field_id:
            return False
        widget = self.field_widgets.get(field_id)
        container = self.field_containers.get(field_id)
        if widget is not None and widget.isHidden():
            return False
        if container is not None and container.isHidden():
            return False
        return widget is not None or container is not None

    def _update_progress(self) -> None:
        if self.progress_bar is None or self.progress_label is None:
            return
        values = self.current_values()
        total = 0
        completed = 0
        counted_choice_groups: set[str] = set()

        for field in self.fields:
            if self._is_automatic_date(field):
                continue
            field_id = str(field.get("id", "")).strip()
            if not field_id:
                continue
            if not self._field_is_visible(field_id):
                continue
            field_type = infer_field_type(field_id, str(field.get("type", "text")))
            group = str(field.get("group") or field.get("layout_group") or "").strip()
            is_choice = field_type == "checkbox" and str(field.get("selection", "")).casefold() in {"single", "exclusive", "radio"}
            if is_choice and group:
                if group in counted_choice_groups:
                    continue
                counted_choice_groups.add(group)
                group_fields = [
                    item
                    for item in self.fields
                    if str(item.get("group") or item.get("layout_group") or "").strip() == group
                    and self._field_is_visible(str(item.get("id", "")))
                ]
                total += 1
                if any(bool(values.get(str(item.get("id", "")))) for item in group_fields):
                    completed += 1
                continue

            total += 1
            value = values.get(field_id)
            if isinstance(value, bool):
                if value:
                    completed += 1
            elif isinstance(value, list):
                if value:
                    completed += 1
            elif str(value or "").strip():
                completed += 1

        self.progress_bar.setRange(0, max(1, total))
        self.progress_bar.setValue(completed)
        self.progress_label.setText(f"{completed} de {total} preenchidos")

    def _resolved_sections(self) -> list[dict[str, Any]]:
        if self.sections:
            return self.sections
        grouped: OrderedDict[str, list[str]] = OrderedDict()
        titles = {
            "process": "Informações do processo",
            "company": "Informações da empresa",
            "proposal": "Informações da proposta",
            "representative": "Representante legal",
            "contact": "Informações de contato",
            "bank": "Informações bancárias",
            "declaration": "Declarações",
            "document": "Informações do documento",
        }
        for field in self.fields:
            field_id = str(field.get("id", ""))
            explicit = str(field.get("section", "")).strip()
            title = explicit or titles.get(field_id.split(".", 1)[0].casefold(), "Dados do documento")
            grouped.setdefault(title, []).append(field_id)
        return [{"title": title, "fields": field_ids} for title, field_ids in grouped.items()]

    @staticmethod
    def _should_span_full_width(field_id: str, field_type: str, field: dict[str, Any]) -> bool:
        layout = str(field.get("layout", "")).casefold()
        if layout == "full_width" or bool(field.get("full_width", False)):
            return True
        if field_type in {"multiline", "repeatable_table"}:
            return True
        if field_type == "dropdown":
            option_values = dropdown_option_values(field.get("options", []))
            if any(len(" ".join(value.split())) > 100 or "\n" in value for value in option_values):
                return True
        normalized = field_id.casefold()
        return any(
            keyword in normalized
            for keyword in (
                "legal_name", "razao_social", "razão_social", "address", "endereco", "endereço",
                "object", "objeto", "description", "descricao", "descrição", "justification",
                "justificativa", "review_notes", "observations",
            )
        )

    @staticmethod
    def _placeholder_for(field_id: str, field_type: str) -> str:
        if field_type == "cnpj":
            return "00.000.000/0000-00"
        if field_type == "cpf":
            return "000.000.000-00"
        if field_type == "cep":
            return "00000-000"
        if field_type == "phone":
            return "(00) 00000-0000"
        if field_type == "email":
            return "name@example.com"
        if field_type == "currency":
            return "R$ 0,00"
        if field_type == "percentage":
            return "0,00%"
        normalized = field_id.casefold()
        if "matricula" in normalized or "matrícula" in normalized:
            return "Informe a matrícula"
        if "setor" in normalized or "unidade" in normalized:
            return "Informe a unidade, o setor ou o departamento"
        if "orgao" in normalized or "órgão" in normalized:
            return "Informe o órgão"
        if "process" in normalized or "processo" in normalized or "edital" in normalized:
            return "Exemplo: 123/2026"
        if "name" in normalized or "nome" in normalized:
            return "Informe o nome completo"
        return "Preencha este campo"

    @staticmethod
    def _repolish(widget: QWidget) -> None:
        style = widget.style()
        if style is None:
            return
        style.unpolish(widget)
        style.polish(widget)
        widget.update()

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            child = item.layout()
            if child is not None:
                DocumentForm._clear_layout(child)
