from __future__ import annotations

from copy import deepcopy
from typing import Any

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


DROPDOWN_PROMPT = "-- Selecione uma opção --"


from app.field_utils import (
    compact_dropdown_options,
    normalize_dropdown_options,
)


def _preview_text(value: str, limit: int = 180) -> str:
    collapsed = " ".join(str(value or "").split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: max(0, limit - 1)].rstrip() + "…"


class SearchableDropdownDialog(QDialog):
    def __init__(
        self,
        title: str,
        options: Any,
        current_value: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._options = normalize_dropdown_options(options)
        self._selected_value = str(current_value or "")

        self.setWindowTitle(title or "Selecionar opção")
        self.resize(780, 560)
        self.setMinimumSize(600, 430)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        heading = QLabel(title or "Selecionar opção")
        heading.setObjectName("longDropdownDialogTitle")
        root.addWidget(heading)

        explanation = QLabel(
            "Pesquise pelo título ou pelo conteúdo completo. O texto mostrado "
            "na visualização será inserido no documento."
        )
        explanation.setObjectName("mutedText")
        explanation.setWordWrap(True)
        root.addWidget(explanation)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Pesquisar nas opções...")
        self.search_input.setClearButtonEnabled(True)
        root.addWidget(self.search_input)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.options_list = QListWidget()
        self.options_list.setObjectName("longDropdownOptionsList")
        self.options_list.setWordWrap(True)
        # Alternating rows inherit the operating-system palette on some
        # Windows themes, which can produce a light row with light text.
        # Keep a single themed background and use hover/selection styling.
        self.options_list.setAlternatingRowColors(False)
        self.options_list.setSpacing(3)
        self.options_list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        splitter.addWidget(self.options_list)

        preview_panel = QFrame()
        preview_panel.setObjectName("longDropdownPreviewPanel")
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(14, 14, 14, 14)
        preview_layout.setSpacing(8)

        preview_title = QLabel("Texto completo")
        preview_title.setObjectName("longDropdownPreviewTitle")
        preview_layout.addWidget(preview_title)

        self.preview = QTextBrowser()
        self.preview.setObjectName("longDropdownPreview")
        self.preview.setOpenExternalLinks(False)
        preview_layout.addWidget(self.preview, 1)

        splitter.addWidget(preview_panel)
        splitter.setSizes([330, 430])
        root.addWidget(splitter, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(8)

        self.clear_button = QPushButton("Limpar seleção")
        self.clear_button.clicked.connect(self._clear_selection)
        footer.addWidget(self.clear_button)
        footer.addStretch()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Ok
        )
        self.select_button = buttons.button(
            QDialogButtonBox.StandardButton.Ok
        )
        self.select_button.setText("Usar opção")
        self.select_button.setObjectName("primaryButton")
        buttons.button(
            QDialogButtonBox.StandardButton.Cancel
        ).setText("Cancelar")
        buttons.accepted.connect(self._accept_selected)
        buttons.rejected.connect(self.reject)
        footer.addWidget(buttons)
        root.addLayout(footer)

        self.search_input.textChanged.connect(self._apply_filter)
        self.options_list.currentItemChanged.connect(
            self._update_preview
        )
        self.options_list.itemDoubleClicked.connect(
            lambda _item: self._accept_selected()
        )

        self._populate()
        self.search_input.setFocus(
            Qt.FocusReason.OtherFocusReason
        )

    def selected_value(self) -> str:
        return self._selected_value

    def _populate(self) -> None:
        self.options_list.clear()
        selected_item: QListWidgetItem | None = None

        for option in self._options:
            label = option["label"]
            output = option["value"]
            if label == output:
                display = _preview_text(output, 230)
            else:
                display = f"{label}\n{_preview_text(output, 190)}"

            item = QListWidgetItem(display)
            item.setData(
                Qt.ItemDataRole.UserRole,
                deepcopy(option),
            )
            line_count = max(1, display.count("\n") + 1)
            item.setSizeHint(
                QSize(300, 48 + (line_count - 1) * 24)
            )
            item.setToolTip(output)
            self.options_list.addItem(item)

            if output == self._selected_value:
                selected_item = item

        if selected_item is not None:
            self.options_list.setCurrentItem(selected_item)
            self.options_list.scrollToItem(selected_item)
        elif self.options_list.count():
            self.options_list.setCurrentRow(0)
        else:
            self.preview.setPlainText("Nenhuma opção configurada.")

        self._update_button_state()

    def _apply_filter(self, query: str) -> None:
        normalized_query = " ".join(query.casefold().split())
        first_visible: QListWidgetItem | None = None

        for row in range(self.options_list.count()):
            item = self.options_list.item(row)
            option = item.data(Qt.ItemDataRole.UserRole) or {}
            searchable = " ".join(
                (
                    str(option.get("label", "")),
                    str(option.get("value", "")),
                )
            ).casefold()
            visible = not normalized_query or normalized_query in searchable
            item.setHidden(not visible)
            if visible and first_visible is None:
                first_visible = item

        current = self.options_list.currentItem()
        if current is None or current.isHidden():
            self.options_list.setCurrentItem(first_visible)
        self._update_button_state()

    def _update_preview(
        self,
        current: QListWidgetItem | None,
        _previous: QListWidgetItem | None = None,
    ) -> None:
        if current is None or current.isHidden():
            self.preview.clear()
            self._update_button_state()
            return

        option = current.data(Qt.ItemDataRole.UserRole) or {}
        label = str(option.get("label", "")).strip()
        value = str(option.get("value", "")).strip()
        if label and label != value:
            self.preview.setHtml(
                f"<p><b>{_escape_html(label)}</b></p>"
                f"<p>{_escape_html(value).replace(chr(10), '<br>')}</p>"
            )
        else:
            self.preview.setPlainText(value)
        self._update_button_state()

    def _update_button_state(self) -> None:
        current = self.options_list.currentItem()
        self.select_button.setEnabled(
            current is not None and not current.isHidden()
        )
        self.clear_button.setEnabled(bool(self._selected_value))

    def _accept_selected(self) -> None:
        current = self.options_list.currentItem()
        if current is None or current.isHidden():
            return
        option = current.data(Qt.ItemDataRole.UserRole) or {}
        self._selected_value = str(option.get("value", "")).strip()
        self.accept()

    def _clear_selection(self) -> None:
        self._selected_value = ""
        self.accept()


class SearchableDropdown(QWidget):
    value_changed = Signal()

    def __init__(
        self,
        options: Any = None,
        *,
        title: str = "Selecionar opção",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._title = str(title or "Selecionar opção")
        self._options = normalize_dropdown_options(options)
        self._value = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        self.button = QToolButton()
        self.button.setObjectName("longDropdownButton")
        self.button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextOnly
        )
        self.button.setCursor(
            Qt.CursorShape.PointingHandCursor
        )
        self.button.setText(DROPDOWN_PROMPT + "  ▾")
        self.button.clicked.connect(self._open_dialog)
        layout.addWidget(self.button)

        self.summary = QLabel()
        self.summary.setObjectName("longDropdownSelectedText")
        self.summary.setWordWrap(True)
        self.summary.hide()
        layout.addWidget(self.summary)

    def set_options(self, options: Any) -> None:
        previous = self._value
        self._options = normalize_dropdown_options(options)
        allowed = {option["value"] for option in self._options}
        self._value = previous if previous in allowed else ""
        self._refresh_display()

    def current_value(self) -> str:
        return self._value

    def current_label(self) -> str:
        for option in self._options:
            if option["value"] == self._value:
                return option["label"]
        return ""

    def set_value(self, value: Any, *, emit_signal: bool = False) -> None:
        text = str(value or "").strip()
        allowed = {option["value"] for option in self._options}
        new_value = text if text in allowed else ""
        changed = new_value != self._value
        self._value = new_value
        self._refresh_display()
        if changed and emit_signal:
            self.value_changed.emit()

    def clear(self, *, emit_signal: bool = False) -> None:
        self.set_value("", emit_signal=emit_signal)

    def focus_selector(self) -> None:
        self.button.setFocus(
            Qt.FocusReason.OtherFocusReason
        )

    def _open_dialog(self) -> None:
        dialog = SearchableDropdownDialog(
            self._title,
            self._options,
            self._value,
            self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        selected = dialog.selected_value()
        if selected == self._value:
            return

        self._value = selected
        self._refresh_display()
        self.value_changed.emit()

    def _refresh_display(self) -> None:
        if not self._value:
            self.button.setText(DROPDOWN_PROMPT + "  ▾")
            self.button.setToolTip(
                "Clique para pesquisar e selecionar uma opção."
            )
            self.summary.clear()
            self.summary.hide()
            return

        label = self.current_label() or _preview_text(self._value, 80)
        self.button.setText(_preview_text(label, 90) + "  ▾")
        self.button.setToolTip(self._value)

        show_summary = (
            label != self._value
            or len(" ".join(self._value.split())) > 110
            or "\n" in self._value
        )
        if show_summary:
            self.summary.setText(_preview_text(self._value, 280))
            self.summary.setToolTip(self._value)
            self.summary.show()
        else:
            self.summary.clear()
            self.summary.hide()


class DropdownOptionsEditor(QWidget):
    options_changed = Signal()

    def __init__(
        self,
        options: Any = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._options = compact_dropdown_options(options)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        self.summary = QLineEdit()
        self.summary.setReadOnly(True)
        self.summary.setObjectName("dropdownOptionsSummary")
        layout.addWidget(self.summary, 1)

        self.edit_button = QPushButton("Editar...")
        self.edit_button.setObjectName("dropdownOptionsEditButton")
        self.edit_button.clicked.connect(self._edit_options)
        layout.addWidget(self.edit_button)

        self._refresh_summary()

    def options(self) -> list[str | dict[str, str]]:
        return deepcopy(self._options)

    def set_options(self, options: Any) -> None:
        self._options = compact_dropdown_options(options)
        self._refresh_summary()

    def setPlaceholderText(self, text: str) -> None:
        self.summary.setPlaceholderText(text)

    def _edit_options(self) -> None:
        dialog = DropdownOptionsDialog(self._options, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        updated = dialog.options()
        if updated == self._options:
            return
        self._options = updated
        self._refresh_summary()
        self.options_changed.emit()

    def _refresh_summary(self) -> None:
        normalized = normalize_dropdown_options(self._options)
        count = len(normalized)
        if not count:
            self.summary.clear()
            self.summary.setPlaceholderText("Nenhuma opção")
            self.summary.setToolTip("")
            return

        titles = [option["label"] for option in normalized[:3]]
        text = f"{count} opção(ões): " + "; ".join(titles)
        if count > 3:
            text += "; …"
        self.summary.setText(text)
        self.summary.setToolTip(
            "\n\n".join(
                f"{option['label']}\n{option['value']}"
                if option["label"] != option["value"]
                else option["value"]
                for option in normalized
            )
        )


class DropdownOptionsDialog(QDialog):
    def __init__(self, options: Any = None, parent=None) -> None:
        super().__init__(parent)
        self._options = normalize_dropdown_options(options)
        self._loading = False

        self.setWindowTitle("Editar opções da lista suspensa")
        self.resize(850, 580)
        self.setMinimumSize(680, 480)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        intro = QLabel(
            "Use um título curto para facilitar a escolha e escreva, abaixo, "
            "o texto completo que será inserido no documento. O título é opcional."
        )
        intro.setObjectName("mutedText")
        intro.setWordWrap(True)
        root.addWidget(intro)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        self.options_list = QListWidget()
        self.options_list.setObjectName("dropdownEditorList")
        self.options_list.setWordWrap(True)
        self.options_list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        left_layout.addWidget(self.options_list, 1)

        list_buttons = QHBoxLayout()
        list_buttons.setSpacing(6)
        add_button = QPushButton("Adicionar")
        remove_button = QPushButton("Remover")
        up_button = QPushButton("↑")
        down_button = QPushButton("↓")
        add_button.clicked.connect(self._add_option)
        remove_button.clicked.connect(self._remove_option)
        up_button.clicked.connect(lambda: self._move_option(-1))
        down_button.clicked.connect(lambda: self._move_option(1))
        list_buttons.addWidget(add_button)
        list_buttons.addWidget(remove_button)
        list_buttons.addStretch()
        list_buttons.addWidget(up_button)
        list_buttons.addWidget(down_button)
        left_layout.addLayout(list_buttons)
        splitter.addWidget(left)

        right = QFrame()
        right.setObjectName("dropdownEditorDetail")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(14, 14, 14, 14)
        right_layout.setSpacing(8)

        title_label = QLabel("Título exibido (opcional)")
        title_label.setObjectName("fieldLabel")
        right_layout.addWidget(title_label)

        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText(
            "Ex.: Continuidade dos serviços"
        )
        right_layout.addWidget(self.title_input)

        value_label = QLabel("Texto inserido no documento")
        value_label.setObjectName("fieldLabel")
        right_layout.addWidget(value_label)

        self.value_input = QPlainTextEdit()
        self.value_input.setPlaceholderText(
            "Digite o texto completo desta opção. Textos longos e várias linhas são aceitos."
        )
        right_layout.addWidget(self.value_input, 1)

        hint = QLabel(
            "Na tela Gerar, a pesquisa considera tanto o título quanto o texto completo."
        )
        hint.setObjectName("mutedText")
        hint.setWordWrap(True)
        right_layout.addWidget(hint)
        splitter.addWidget(right)
        splitter.setSizes([290, 540])
        root.addWidget(splitter, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Save
        )
        buttons.button(
            QDialogButtonBox.StandardButton.Save
        ).setText("Salvar opções")
        buttons.button(
            QDialogButtonBox.StandardButton.Save
        ).setObjectName("primaryButton")
        buttons.button(
            QDialogButtonBox.StandardButton.Cancel
        ).setText("Cancelar")
        buttons.accepted.connect(self._accept_changes)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.options_list.currentRowChanged.connect(
            self._selection_changed
        )
        self.title_input.textChanged.connect(
            self._detail_changed
        )
        self.value_input.textChanged.connect(
            self._detail_changed
        )

        self._rebuild_list()
        if self.options_list.count():
            self.options_list.setCurrentRow(0)
        else:
            self._set_detail_enabled(False)

    def options(self) -> list[str | dict[str, str]]:
        return compact_dropdown_options(self._options)

    def _rebuild_list(self, selected_row: int | None = None) -> None:
        self._loading = True
        try:
            self.options_list.clear()
            for option in self._options:
                label = option["label"] or "Nova opção"
                item = QListWidgetItem(
                    f"{label}\n{_preview_text(option['value'], 100)}"
                )
                item.setSizeHint(QSize(250, 60))
                self.options_list.addItem(item)
        finally:
            self._loading = False

        if self.options_list.count():
            row = 0 if selected_row is None else max(
                0,
                min(selected_row, self.options_list.count() - 1),
            )
            self.options_list.setCurrentRow(row)

    def _selection_changed(self, row: int) -> None:
        if self._loading:
            return
        self._loading = True
        try:
            valid = 0 <= row < len(self._options)
            self._set_detail_enabled(valid)
            if not valid:
                self.title_input.clear()
                self.value_input.clear()
                return
            option = self._options[row]
            self.title_input.setText(option["label"])
            self.value_input.setPlainText(option["value"])
        finally:
            self._loading = False

    def _detail_changed(self) -> None:
        if self._loading:
            return
        row = self.options_list.currentRow()
        if not (0 <= row < len(self._options)):
            return

        value = self.value_input.toPlainText()
        label = self.title_input.text().strip() or _preview_text(value, 70)
        self._options[row] = {
            "label": label,
            "value": value,
        }
        item = self.options_list.item(row)
        if item is not None:
            item.setText(
                f"{label or 'Nova opção'}\n{_preview_text(value, 100)}"
            )

    def _add_option(self) -> None:
        self._options.append(
            {
                "label": "Nova opção",
                "value": "",
            }
        )
        self._rebuild_list(len(self._options) - 1)
        self.value_input.setFocus(
            Qt.FocusReason.OtherFocusReason
        )
        self.value_input.selectAll()

    def _remove_option(self) -> None:
        row = self.options_list.currentRow()
        if not (0 <= row < len(self._options)):
            return
        self._options.pop(row)
        self._rebuild_list(max(0, row - 1))
        if not self._options:
            self._set_detail_enabled(False)
            self.title_input.clear()
            self.value_input.clear()

    def _move_option(self, direction: int) -> None:
        row = self.options_list.currentRow()
        target = row + direction
        if not (
            0 <= row < len(self._options)
            and 0 <= target < len(self._options)
        ):
            return
        self._options[row], self._options[target] = (
            self._options[target],
            self._options[row],
        )
        self._rebuild_list(target)

    def _set_detail_enabled(self, enabled: bool) -> None:
        self.title_input.setEnabled(enabled)
        self.value_input.setEnabled(enabled)

    def _accept_changes(self) -> None:
        normalized = normalize_dropdown_options(self._options)
        if not normalized:
            QMessageBox.warning(
                self,
                "Nenhuma opção válida",
                "Adicione pelo menos uma opção e informe o texto que será inserido no documento.",
            )
            return
        self._options = normalized
        self.accept()


def _escape_html(value: str) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )
