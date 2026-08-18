import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication

from app.template_manager.template_editor_dialog import TemplateEditorDialog
from app.template_repository import TemplateRepository


def _app():
    return QApplication.instance() or QApplication([])


def test_focus_field_opens_campos_and_selects_exact_clicked_field(tmp_path):
    app = _app()
    repository = TemplateRepository(tmp_path / "templates")
    dialog = TemplateEditorDialog(repository, None)
    dialog._load_fields_into_table(
        [
            {"id": "auto.primeiro", "label": "Primeiro", "type": "text"},
            {"id": "auto.opcao.sim", "label": "Sim", "type": "checkbox"},
            {"id": "auto.opcao.nao", "label": "Não", "type": "checkbox"},
            {"id": "auto.ultimo", "label": "Último", "type": "text"},
        ]
    )
    dialog.field_search_input.setText("Último")
    dialog.fields_tabs.setCurrentIndex(2)
    dialog.show()
    app.processEvents()

    dialog.focus_field("auto.opcao.nao")
    app.processEvents()
    app.processEvents()

    assert dialog.fields_tabs.currentIndex() == 0
    assert dialog.field_search_input.text() == ""
    assert dialog.fields_table.currentRow() == 2
    assert dialog.fields_table.currentColumn() == 1
    selected = {index.row() for index in dialog.fields_table.selectionModel().selectedRows()}
    assert selected == {2}
    assert dialog.fields_table.item(2, 0).text() == "auto.opcao.nao"
    assert not dialog.fields_table.isRowHidden(2)

    dialog.close()


def test_section_card_edit_uses_same_exact_field_focus(tmp_path):
    app = _app()
    repository = TemplateRepository(tmp_path / "templates")
    dialog = TemplateEditorDialog(repository, None)
    dialog._load_fields_into_table(
        [
            {"id": "a", "label": "Campo A", "type": "text"},
            {"id": "b", "label": "Campo B", "type": "text"},
        ]
    )
    dialog.show()
    app.processEvents()

    dialog._edit_field_from_card("b")
    app.processEvents()

    assert dialog.fields_table.currentRow() == 1
    assert dialog.fields_table.currentColumn() == 1
    assert dialog.fields_table.item(dialog.fields_table.currentRow(), 0).text() == "b"

    dialog.close()
