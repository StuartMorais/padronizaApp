from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class TemplateSectionCard(QFrame):
    rename_requested = Signal(str)
    move_requested = Signal(str, int)
    edit_field_requested = Signal(str)

    def __init__(
        self,
        model: dict[str, Any],
        *,
        type_labels: dict[str, str],
        can_move_up: bool,
        can_move_down: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.model = model
        self.section_title = str(model.get("title", "Dados do documento"))
        self.search_text = str(model.get("search_text", "")).casefold()
        self.setObjectName("templateSectionCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QFrame()
        header.setObjectName("templateSectionCardHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(12, 9, 8, 9)
        header_layout.setSpacing(8)

        self.collapse_button = QToolButton()
        self.collapse_button.setObjectName("sectionCardCollapseButton")
        self.collapse_button.setCheckable(True)
        self.collapse_button.setChecked(True)
        self.collapse_button.setArrowType(Qt.ArrowType.DownArrow)
        self.collapse_button.setToolTip("Recolher ou expandir a seção")
        self.collapse_button.toggled.connect(self._set_expanded)
        header_layout.addWidget(self.collapse_button)

        title = QLabel(self.section_title)
        title.setObjectName("templateSectionCardTitle")
        title.setWordWrap(True)
        header_layout.addWidget(title, 1)

        count = int(model.get("field_count", 0) or 0)
        count_badge = QLabel(f"{count} campo" if count == 1 else f"{count} campos")
        count_badge.setObjectName("templateSectionCountBadge")
        header_layout.addWidget(count_badge)

        up_button = QToolButton()
        up_button.setObjectName("sectionCardActionButton")
        up_button.setText("↑")
        up_button.setToolTip("Mover seção para cima")
        up_button.setEnabled(can_move_up)
        up_button.clicked.connect(lambda: self.move_requested.emit(self.section_title, -1))
        header_layout.addWidget(up_button)

        down_button = QToolButton()
        down_button.setObjectName("sectionCardActionButton")
        down_button.setText("↓")
        down_button.setToolTip("Mover seção para baixo")
        down_button.setEnabled(can_move_down)
        down_button.clicked.connect(lambda: self.move_requested.emit(self.section_title, 1))
        header_layout.addWidget(down_button)

        rename_button = QToolButton()
        rename_button.setObjectName("sectionCardActionButton")
        rename_button.setText("Renomear")
        rename_button.setToolTip("Renomear seção")
        rename_button.clicked.connect(lambda: self.rename_requested.emit(self.section_title))
        header_layout.addWidget(rename_button)

        root.addWidget(header)

        self.body = QFrame()
        self.body.setObjectName("templateSectionCardBody")
        body_layout = QVBoxLayout(self.body)
        body_layout.setContentsMargins(10, 8, 10, 10)
        body_layout.setSpacing(6)

        entries = model.get("entries", [])
        if not entries:
            empty = QLabel("Esta seção ainda não possui campos.")
            empty.setObjectName("mutedText")
            body_layout.addWidget(empty)
        else:
            for entry in entries:
                if entry.get("kind") == "group":
                    self._add_group(body_layout, entry, type_labels)
                else:
                    self._add_field_row(body_layout, entry.get("field", {}), type_labels)

        root.addWidget(self.body)

    def _add_group(
        self,
        parent_layout: QVBoxLayout,
        entry: dict[str, Any],
        type_labels: dict[str, str],
    ) -> None:
        group = QFrame()
        group.setObjectName("templateSectionGroup")
        group_layout = QVBoxLayout(group)
        group_layout.setContentsMargins(8, 7, 8, 8)
        group_layout.setSpacing(5)

        group_header = QHBoxLayout()
        group_header.setSpacing(7)
        title = QLabel(str(entry.get("title", "Grupo")))
        title.setObjectName("templateSectionGroupTitle")
        title.setWordWrap(True)
        group_header.addWidget(title, 1)
        fields = list(entry.get("fields", []))
        count = QLabel(str(len(fields)))
        count.setObjectName("templateSectionGroupCount")
        group_header.addWidget(count)
        group_layout.addLayout(group_header)

        for field in fields:
            self._add_field_row(group_layout, field, type_labels, grouped=True)

        parent_layout.addWidget(group)

    def _add_field_row(
        self,
        parent_layout: QVBoxLayout,
        field: dict[str, Any],
        type_labels: dict[str, str],
        *,
        grouped: bool = False,
    ) -> None:
        row = QFrame()
        row.setObjectName("templateSectionFieldRowGrouped" if grouped else "templateSectionFieldRow")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(9, 7, 7, 7)
        layout.setSpacing(9)

        handle = QLabel("⋮⋮")
        handle.setObjectName("templateSectionFieldHandle")
        handle.setToolTip("A ordem segue a aba Campos")
        layout.addWidget(handle)

        text_widget = QWidget()
        text_layout = QVBoxLayout(text_widget)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(1)
        label = QLabel(str(field.get("label", "Campo sem nome")))
        label.setObjectName("templateSectionFieldLabel")
        label.setWordWrap(True)
        field_id = QLabel(str(field.get("id", "")))
        field_id.setObjectName("templateSectionFieldId")
        field_id.setWordWrap(True)
        text_layout.addWidget(label)
        text_layout.addWidget(field_id)
        layout.addWidget(text_widget, 1)

        field_type = str(field.get("type", "text"))
        type_badge = QLabel(type_labels.get(field_type, field_type.replace("_", " ").title()))
        type_badge.setObjectName("templateSectionTypeBadge")
        layout.addWidget(type_badge)

        layout_name = str(field.get("layout_label", ""))
        if layout_name and layout_name not in {"Automático", "Grade"}:
            layout_badge = QLabel(layout_name)
            layout_badge.setObjectName("templateSectionLayoutBadge")
            layout.addWidget(layout_badge)

        edit_button = QPushButton("Editar")
        edit_button.setObjectName("sectionFieldEditButton")
        edit_button.setToolTip("Abrir este campo na aba Campos")
        field_id_value = str(field.get("id", ""))
        edit_button.clicked.connect(lambda: self.edit_field_requested.emit(field_id_value))
        layout.addWidget(edit_button)

        parent_layout.addWidget(row)

    def _set_expanded(self, expanded: bool) -> None:
        self.body.setVisible(expanded)
        self.collapse_button.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )

    def set_expanded(self, expanded: bool) -> None:
        self.collapse_button.setChecked(expanded)

    def matches(self, query: str) -> bool:
        return not query or query.casefold() in self.search_text
