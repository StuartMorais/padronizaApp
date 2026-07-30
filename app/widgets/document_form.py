from __future__ import annotations

from datetime import date
from html import escape
from typing import Any

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QGroupBox,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.field_utils import (
    condition_matches,
    dropdown_option_values,
    infer_field_type,
    sample_value,
    validate_field,
    validation_hint,
)
from app.widgets.context_help import HelpIconButton
from app.widgets.readable_checkbox import ReadableCheckBox
from app.widgets.repeatable_table import RepeatableTableWidget
from app.widgets.smart_line_edit import SmartLineEdit
from app.widgets.searchable_dropdown import SearchableDropdown


# noinspection SpellCheckingInspection
class DocumentForm(QWidget):
    """
    Dynamic form with masks, validation, sections, conditional fields,
    exclusive checkbox groups, profile mapping, and draft serialization.
    """

    values_changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.fields: list[dict[str, Any]] = []
        self.sections: list[dict[str, Any]] = []
        self.field_widgets: dict[str, QWidget] = {}
        self.field_containers: dict[str, QWidget] = {}
        self.field_definitions: dict[str, dict[str, Any]] = {}
        self.field_error_labels: dict[str, QLabel] = {}
        self.field_hint_labels: dict[str, QLabel] = {}
        self.checkbox_groups: dict[str, list[str]] = {}
        self._updating = False

        self.content_layout = QVBoxLayout(self)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(12)


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
        self.checkbox_groups.clear()

        ordered_sections = self._resolved_sections()
        rendered_ids: set[str] = set()

        for section in ordered_sections:
            title = str(
                section.get("title", "Informações")
            ).strip() or "Informações"
            field_ids = [
                str(value)
                for value in section.get("fields", [])
            ]
            section_fields = [
                field
                for field_id in field_ids
                for field in self.fields
                if (
                    str(field.get("id", "")) == field_id
                    and field_id not in rendered_ids
                )
            ]
            section_group = self._build_section_group(
                title,
                section_fields,
                rendered_ids,
            )
            if section_group is not None:
                self.content_layout.addWidget(section_group)

        # Campos não incluídos em uma seção declarada nunca são perdidos.
        remaining = [
            field
            for field in self.fields
            if str(field.get("id", "")) not in rendered_ids
            and not self._is_automatic_date(field)
        ]
        fallback_group = self._build_section_group(
            "Informações adicionais",
            remaining,
            rendered_ids,
        )
        if fallback_group is not None:
            self.content_layout.addWidget(fallback_group)

        required_note = QLabel(
            "Os campos marcados com * são obrigatórios. As caixas de seleção "
            "sempre são impressas como ☑ ou ☐ e nunca são confirmações obrigatórias."
        )
        required_note.setObjectName("mutedText")
        required_note.setWordWrap(True)
        self.content_layout.addWidget(required_note)
        self.content_layout.addStretch()
        self._refresh_visibility()

    def _build_section_group(
        self,
        title: str,
        section_fields: list[dict[str, Any]],
        rendered_ids: set[str],
    ) -> QGroupBox | None:
        visible_fields = [
            field
            for field in section_fields
            if not self._is_automatic_date(field)
        ]
        if not visible_fields:
            return None

        section_group = QGroupBox(title)
        grid = QGridLayout(section_group)
        grid.setContentsMargins(16, 20, 16, 16)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(12)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        row = 0
        column = 0
        added_count = 0
        for field in visible_fields:
            field_id = str(field.get("id", "")).strip()
            if not field_id or field_id in rendered_ids:
                continue

            rendered_ids.add(field_id)
            added_count += 1
            self.field_definitions[field_id] = field

            field_type = infer_field_type(
                field_id,
                str(field.get("type", "text")),
            )
            field["type"] = field_type

            widget = self._create_widget(field)
            self.field_widgets[field_id] = widget

            label = str(
                field.get("label", field_id)
            ).strip() or field_id
            required = (
                bool(field.get("required", False))
                and field_type != "checkbox"
            )
            display_label = f"{label} *" if required else label

            container = self._create_field_card(
                field_id,
                display_label,
                widget,
                field_type,
                field,
            )
            self.field_containers[field_id] = container

            full_width = self._should_span_full_width(
                field_id,
                field_type,
                field,
            )
            if full_width:
                if column != 0:
                    row += 1
                    column = 0
                grid.addWidget(container, row, 0, 1, 2)
                row += 1
            else:
                grid.addWidget(container, row, column)
                column = 1 if column == 0 else 0
                if column == 0:
                    row += 1

            checkbox_group = str(
                field.get("group", "")
            ).strip()
            selection = str(
                field.get("selection", "")
            ).casefold()
            if (
                field_type == "checkbox"
                and checkbox_group
                and selection in {"single", "exclusive", "radio"}
            ):
                self.checkbox_groups.setdefault(
                    checkbox_group,
                    [],
                ).append(field_id)
                if isinstance(widget, QCheckBox):
                    widget.toggled.connect(
                        lambda checked,
                        field_key=field_id,
                        exclusive_group=checkbox_group: (
                            self._exclusive_checkbox_changed(
                                field_key,
                                exclusive_group,
                                checked,
                            )
                        )
                    )

            self._connect_widget(widget)

        return section_group if added_count else None

    @staticmethod
    def _is_automatic_date(field: dict[str, Any]) -> bool:
        field_id = str(field.get("id", "")).strip()
        field_type = infer_field_type(
            field_id,
            str(field.get("type", "text")),
        )
        return (
            field_type == "date"
            and bool(field.get("automatic", True))
        )

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

            container = self.field_containers.get(field_id)
            visible = container is None or not container.isHidden()
            field_type = infer_field_type(
                field_id,
                str(field.get("type", "text")),
            )
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
            errors = [
                str(issue.get("message", ""))
                for issue in issues
                if str(issue.get("message", ""))
            ]
            raise ValueError(
                'Corrija os seguintes campos:\n- '
                + "\n- ".join(errors)
            )

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
            if isinstance(widget, QCheckBox):
                values[field_id] = widget.isChecked()
            elif isinstance(widget, SearchableDropdown):
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

    def validation_issues(
        self,
        values: dict[str, Any] | None = None,
    ) -> list[dict[str, str]]:
        resolved_values = (
            dict(values)
            if values is not None
            else self.current_values()
        )
        issues: list[dict[str, str]] = []

        for field in self.fields:
            field_id = str(field.get("id", "")).strip()
            if not field_id:
                continue

            container = self.field_containers.get(field_id)
            if container is not None and container.isHidden():
                continue

            error = validate_field(
                field,
                resolved_values.get(field_id),
            )
            if not error:
                continue

            field_type = infer_field_type(
                field_id,
                str(field.get("type", "text")),
            )
            value = resolved_values.get(field_id)
            empty = (
                field_type != "checkbox"
                and not str(value or "").strip()
            )
            label = str(
                field.get("label", field_id)
            ).strip() or field_id
            issues.append(
                {
                    "field_id": field_id,
                    "label": label,
                    "message": str(error),
                    "kind": (
                        "missing"
                        if bool(field.get("required", False))
                        and empty
                        else "invalid"
                    ),
                }
            )

        return issues

    def set_validation_issues(
        self,
        issues: list[dict[str, str]],
    ) -> None:
        issue_map = {
            str(issue.get("field_id", "")): issue
            for issue in issues
            if str(issue.get("field_id", ""))
        }

        for field_id, container in self.field_containers.items():
            issue = issue_map.get(field_id)
            state = (
                str(issue.get("kind", "invalid"))
                if issue
                else ""
            )
            message = (
                str(issue.get("message", ""))
                if issue
                else ""
            )
            container.setProperty(
                "validationState",
                state,
            )
            container.setToolTip(message)
            self._repolish(container)

            error_label = self.field_error_labels.get(field_id)
            if error_label is not None:
                error_label.setText(message)
                error_label.setVisible(bool(message))

            widget = self.field_widgets.get(field_id)
            if widget is not None:
                widget.setProperty(
                    "validationState",
                    state,
                )
                widget.setToolTip(message)
                self._repolish(widget)

    def focus_field(self, field_id: str) -> QWidget | None:
        field_id = str(field_id).strip()
        widget = self.field_widgets.get(field_id)
        if widget is None:
            return self.field_containers.get(field_id)

        widget.setFocus(
            Qt.FocusReason.OtherFocusReason
        )
        if isinstance(widget, SmartLineEdit):
            widget.selectAll()
        elif isinstance(widget, QPlainTextEdit):
            widget.selectAll()
        elif isinstance(widget, SearchableDropdown):
            widget.focus_selector()
        elif isinstance(widget, RepeatableTableWidget):
            widget.focus_table()
        container = self.field_containers.get(field_id)
        return container if container is not None else widget

    def has_meaningful_values(
        self,
        values: dict[str, Any] | None = None,
    ) -> bool:
        resolved_values = (
            dict(values)
            if values is not None
            else self.current_values()
        )
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
                        bool(cell)
                        if isinstance(cell, bool)
                        else bool(str(cell or "").strip())
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
        return self.field_containers.get(
            str(field_id).strip()
        )

    def set_values(self, values: dict[str, Any], *, emit_signal: bool = True) -> None:
        self._updating = True
        try:
            for field_id, widget in self.field_widgets.items():
                if field_id not in values:
                    continue
                value = values[field_id]
                if isinstance(widget, QCheckBox):
                    widget.setChecked(bool(value))
                elif isinstance(widget, SearchableDropdown):
                    widget.set_value(value)
                elif isinstance(widget, QPlainTextEdit):
                    widget.setPlainText(str(value or ""))
                elif isinstance(widget, RepeatableTableWidget):
                    widget.set_rows(
                        value if isinstance(value, list) else [],
                        emit_signal=False,
                    )
                elif isinstance(widget, SmartLineEdit):
                    widget.set_value(value)
                elif isinstance(widget, QDateEdit):
                    parsed = QDate.fromString(str(value or ""), "dd/MM/yyyy")
                    if parsed.isValid():
                        widget.setDate(parsed)
        finally:
            self._updating = False

        self._refresh_visibility()
        if emit_signal:
            self.values_changed.emit()

    def apply_profile(self, profile_values: dict[str, Any]) -> None:
        mapped: dict[str, Any] = {}
        for field in self.fields:
            field_id = str(field.get("id", "")).strip()
            profile_key = str(field.get("profile_key", field_id)).strip() or field_id
            if profile_key in profile_values:
                mapped[field_id] = profile_values[profile_key]
            elif field_id in profile_values:
                mapped[field_id] = profile_values[field_id]
        self.set_values(mapped)

    def profile_payload(self) -> dict[str, Any]:
        current = self.current_values()
        result: dict[str, Any] = {}
        for field in self.fields:
            field_id = str(field.get("id", "")).strip()
            if not field_id:
                continue
            profile_key = str(field.get("profile_key", "")).strip()
            if profile_key:
                result[profile_key] = current.get(field_id)
            elif field_id.startswith(("company.", "representative.", "contact.", "bank.")):
                result[field_id] = current.get(field_id)
        return result or current

    def clear_values(self) -> None:
        self._updating = True
        try:
            for widget in self.field_widgets.values():
                if isinstance(widget, QCheckBox):
                    widget.setChecked(False)
                elif isinstance(widget, SearchableDropdown):
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
        self._refresh_visibility()
        self.values_changed.emit()

    def load_sample_data(self) -> None:
        values = {
            str(field.get("id", "")): sample_value(field)
            for field in self.fields
            if str(field.get("id", ""))
        }
        self.set_values(values)

    def _create_widget(self, field: dict[str, Any]) -> QWidget:
        field_id = str(field.get("id", ""))
        field_type = infer_field_type(field_id, str(field.get("type", "text")))

        if field_type == "checkbox":
            checkbox = ReadableCheckBox()
            checkbox.setObjectName("declarationCheckBox")
            checkbox.setText(str(field.get("label", field_id)))
            return checkbox

        if field_type == "dropdown":
            return SearchableDropdown(
                field.get("options", []),
                title=str(
                    field.get(
                        "label",
                        field_id.replace(".", " ").replace("_", " ").title(),
                    )
                ),
            )

        if field_type == "repeatable_table":
            return RepeatableTableWidget(field)

        if field_type == "multiline":
            editor = QPlainTextEdit()
            editor.setMinimumHeight(int(field.get("height", 105) or 105))
            editor.setPlaceholderText(str(field.get("placeholder", 'Informe os dados completos...')))
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
    ) -> QFrame:
        card = QFrame()
        card.setObjectName("fieldCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 7, 10, 9)
        layout.setSpacing(6)

        help_text = self._field_help_text(field)
        help_title = str(
            field.get("help_title", label.rstrip(" *"))
        ).strip() or label.rstrip(" *")

        if field_type != "checkbox":
            label_row = QHBoxLayout()
            label_row.setContentsMargins(0, 0, 0, 0)
            label_row.setSpacing(6)

            label_widget = QLabel(label)
            label_widget.setObjectName("fieldLabel")
            label_widget.setWordWrap(True)
            label_widget.setAutoFillBackground(False)
            label_row.addWidget(label_widget, 1)

            if help_text:
                label_row.addWidget(
                    HelpIconButton(
                        help_title,
                        f"<p>{escape(help_text)}</p>",
                    )
                )
            layout.addLayout(label_row)
            layout.addWidget(widget)
        elif help_text:
            checkbox_row = QHBoxLayout()
            checkbox_row.setContentsMargins(0, 0, 0, 0)
            checkbox_row.setSpacing(6)
            checkbox_row.addWidget(widget, 1)
            checkbox_row.addWidget(
                HelpIconButton(
                    help_title,
                    f"<p>{escape(help_text)}</p>",
                )
            )
            layout.addLayout(checkbox_row)
        else:
            layout.addWidget(widget)

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
        error_label.setVisible(False)
        layout.addWidget(error_label)
        self.field_error_labels[field_id] = error_label

        return card

    @staticmethod
    def _field_help_text(field: dict[str, Any]) -> str:
        for key in (
            "help_text",
            "help",
            "guidance",
            "description",
        ):
            value = str(field.get(key, "")).strip()
            if value:
                example = str(field.get("example", "")).strip()
                if example:
                    return f"{value} Exemplo: {example}"
                return value
        if str(field.get("type", "")) == "repeatable_table":
            return (
                "Adicione uma linha para cada item da contratação. "
                "Também é possível duplicar, reordenar ou colar dados "
                "tabulados copiados do Excel."
            )
        return ""

    def _connect_widget(self, widget: QWidget) -> None:
        if isinstance(widget, QCheckBox):
            widget.toggled.connect(self._widget_changed)
        elif isinstance(widget, SearchableDropdown):
            widget.value_changed.connect(self._widget_changed)
        elif isinstance(widget, QPlainTextEdit):
            widget.textChanged.connect(self._widget_changed)
        elif isinstance(widget, RepeatableTableWidget):
            widget.values_changed.connect(self._widget_changed)
        elif isinstance(widget, SmartLineEdit):
            widget.value_changed.connect(self._widget_changed)
        elif isinstance(widget, QDateEdit):
            widget.dateChanged.connect(self._widget_changed)

    def _widget_changed(self, *_args) -> None:
        if self._updating:
            return
        self._refresh_visibility()
        self.values_changed.emit()

    def _exclusive_checkbox_changed(self, field_id: str, group_name: str, checked: bool) -> None:
        if not checked or self._updating:
            return
        self._updating = True
        try:
            for other_id in self.checkbox_groups.get(group_name, []):
                if other_id == field_id:
                    continue
                widget = self.field_widgets.get(other_id)
                if isinstance(widget, QCheckBox):
                    widget.setChecked(False)
        finally:
            self._updating = False
        self.values_changed.emit()

    def _refresh_visibility(self) -> None:
        values = self.current_values()
        for field_id, field in self.field_definitions.items():
            container = self.field_containers.get(field_id)
            if container is None:
                continue
            condition = field.get("visible_when")
            container.setVisible(condition_matches(condition, values))

    def _resolved_sections(self) -> list[dict[str, Any]]:
        if self.sections:
            return self.sections

        grouped: dict[str, list[str]] = {}
        order: list[str] = []
        titles = {
            "process": 'Informações do processo',
            "company": 'Informações da empresa',
            "proposal": 'Informações da proposta',
            "representative": 'Representante legal',
            "contact": 'Informações de contato',
            "bank": 'Informações bancárias',
            "declaration": 'Declarações',
            "document": 'Informações do documento',
        }

        for field in self.fields:
            field_id = str(field.get("id", ""))
            explicit = str(field.get("section", "")).strip()
            if explicit:
                title = explicit
            else:
                prefix = field_id.split(".", 1)[0].casefold()
                title = titles.get(prefix, 'Dados do documento')
            if title not in grouped:
                grouped[title] = []
                order.append(title)
            grouped[title].append(field_id)

        return [{"title": title, "fields": grouped[title]} for title in order]

    @staticmethod
    def _should_span_full_width(field_id: str, field_type: str, field: dict[str, Any]) -> bool:
        if bool(field.get("full_width", False)):
            return True
        if field_type in {"multiline", "repeatable_table"}:
            return True
        if field_type == "dropdown":
            option_values = dropdown_option_values(
                field.get("options", [])
            )
            if any(
                len(" ".join(value.split())) > 100
                or "\n" in value
                for value in option_values
            ):
                return True
        normalized = field_id.casefold()
        return any(
            keyword in normalized
            for keyword in (
                "legal_name",
                "razao_social",
                "razão_social",
                "address",
                "endereco",
                "endereço",
                "object",
                "objeto",
                "description",
                "descricao",
                "descrição",
                "justification",
                "justificativa",
                "review_notes",
                "observations",
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
        if (
            "process" in normalized
            or "processo" in normalized
            or "edital" in normalized
        ):
            return 'Exemplo: 123/2026'
        if "name" in normalized or "nome" in normalized:
            return 'Informe o nome completo'
        return 'Preencha este campo'

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
