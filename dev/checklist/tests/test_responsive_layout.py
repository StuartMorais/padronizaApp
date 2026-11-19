"""Exercise real Qt geometry; a scrollbar policy alone cannot prove visibility."""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QRect, QSettings, QTimer, Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QAbstractItemView

from adapters.checklist import create_checklist
from adapters.contracts import WorkspaceContext
from checklist_app.main_window import CHECKLIST_PAGE, ChecklistMainWindow
from shell.main_window import OfficeMainWindow
from shell.preferences import Preferences


@pytest.fixture(scope="module")
def app():
    application = QApplication.instance() or QApplication([])
    application.setStyle("Fusion")
    # The offscreen Windows plugin does not discover system fonts by itself.
    font_path = Path("C:/Windows/Fonts/segoeui.ttf")
    if font_path.exists():
        QFontDatabase.addApplicationFont(str(font_path))
    application.setFont(QFont("Segoe UI", 10))
    return application


def settle(app):
    for _ in range(6):
        app.processEvents()


@pytest.fixture
def isolated_data(monkeypatch):
    template = {
        "id": "layout-test", "title": "Checklist " + "com nome longo " * 12,
        "subtitle": "Subtítulo " * 30, "baseLegal": "Lei 14.133",
        "sections": [{
            "id": "section-1", "number": "1", "title": "Documentos iniciais",
            "items": [{
                "number": str(index + 1), "documento": "Documento completo " * 30,
                "normativo": "Artigo 1 da Lei 14.133", "situacao": "Não Aplicável",
                "folha": "12", "observacao": "Observação completa " * 30,
                "descricao": "Orientações", "documentosNecessarios": [],
            } for index in range(12)],
        }],
    }
    monkeypatch.setattr("checklist_app.main_window.load_templates", lambda: [template])
    monkeypatch.setattr("checklist_app.main_window.get_saved_theme", lambda: "dark")
    monkeypatch.setattr("checklist_app.main_window.save_templates", lambda *_args, **_kwargs: Path("unused.json"))
    return template


@pytest.fixture
def wrapper(app, isolated_data):
    widget = create_checklist(WorkspaceContext(return_home=lambda: None, get_theme=lambda: "dark"))
    widget.workspace.expand_all_sections()
    widget.resize(884, 578)
    widget.show()
    settle(app)
    yield widget
    widget.close()
    widget.deleteLater()
    settle(app)


def assert_inside(widget, outer):
    bounds = QRect(widget.mapTo(outer, QPoint()), widget.size())
    assert outer.rect().contains(bounds), (bounds, outer.rect())
    # Being inside the top-level window is insufficient if an intermediate
    # layout clips the table behind the footer or another panel.
    ancestor = widget.parentWidget()
    while ancestor is not None and ancestor is not outer:
        bounds = QRect(widget.mapTo(ancestor, QPoint()), widget.size())
        assert ancestor.rect().contains(bounds), (ancestor.objectName(), bounds, ancestor.rect())
        ancestor = ancestor.parentWidget()


def assert_columns_reachable(table, outer, app):
    assert table.isVisible()
    assert_inside(table, outer)
    assert table.viewport().height() >= 60
    scrollbar = table.horizontalScrollBar()
    assert scrollbar.isVisible()
    assert scrollbar.maximum() > 0
    assert_inside(scrollbar, outer)
    for column in range(table.columnCount()):
        assert not table.isColumnHidden(column)
        cell = table.item(1, column)
        table.scrollToItem(cell, QAbstractItemView.ScrollHint.PositionAtCenter)
        settle(app)
        assert table.visualItemRect(cell).intersects(table.viewport().rect())
    scrollbar.setValue(scrollbar.maximum())
    settle(app)
    assert table.columnViewportPosition(5) + table.columnWidth(5) <= table.viewport().width()


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("size", [(1500, 850), (1200, 700), (884, 578), (684, 500), (500, 500)])
def test_table_and_scrollbar_fit_without_growing_the_window(wrapper, app, theme, size):
    wrapper.set_theme(theme)
    wrapper.resize(*size)
    settle(app)
    assert wrapper.size().toTuple() == size
    assert_columns_reachable(wrapper.workspace.checklist_table, wrapper, app)


def test_narrow_panels_use_available_width_and_return_to_sheet(wrapper, app):
    inner = wrapper.workspace
    for key, panel in [("library", inner.library_panel), ("inspector", inner.inspector_panel), ("sheet", inner.sheet_panel)]:
        QTest.mouseClick(inner.responsive_panel_buttons[key], Qt.MouseButton.LeftButton)
        settle(app)
        assert panel.isVisible()
        assert panel.width() == inner.body_splitter.width()
        assert_inside(panel, wrapper)
        assert sum(p.isVisible() for p in (inner.library_panel, inner.inspector_panel, inner.sheet_panel)) == 1
    inner.responsive_panel_buttons["library"].click()
    inner.select_checklist("layout-test")
    inner.expand_all_sections()
    settle(app)
    assert inner.responsive_panel_buttons["sheet"].isChecked()
    assert_columns_reachable(inner.checklist_table, wrapper, app)


def test_resize_preserves_custom_column_widths_and_reading_position(wrapper, app):
    table = wrapper.workspace.checklist_table
    table.setColumnWidth(5, 370)
    table.horizontalScrollBar().setValue(150)
    table.verticalScrollBar().setValue(80)
    wrapper.resize(860, 578)
    settle(app)
    assert table.columnWidth(5) == 370
    assert table.horizontalScrollBar().value() == 150
    assert table.verticalScrollBar().value() == 80
    wrapper.resize(1500, 850)
    settle(app)
    wrapper.resize(884, 578)
    settle(app)
    assert table.columnWidth(5) == 370
    assert_columns_reachable(table, wrapper, app)


def test_wrapped_content_and_compact_actions_remain_available(wrapper, app):
    inner = wrapper.workspace
    table = inner.checklist_table
    before = table.rowHeight(1)
    table.setColumnWidth(1, 180)
    QTest.qWait(90)
    assert table.rowHeight(1) > before
    assert table.item(1, 1).text() in table.item(1, 1).toolTip()
    actions = inner.btn_sheet_actions.menu().actions()
    expand = next(action for action in actions if action.text() == "Expandir")
    collapse = next(action for action in actions if action.text() == "Recolher")
    collapse.trigger()
    assert table.rowCount() == 1
    expand.trigger()
    assert table.rowCount() == 13
    assert {action.text() for action in actions} >= {"Excluir seção", "Excluir item", "PDF"}
    settle(app)
    assert_columns_reachable(table, wrapper, app)


def test_metadata_dialog_keeps_edits_and_does_not_resize_sheet(wrapper, app, isolated_data):
    inner = wrapper.workspace
    original_size = wrapper.size()

    def edit():
        assert inner.metadata_dialog.isVisible()
        inner.title_input.setText("Nome alterado")
        inner.subtitle_input.setText("Novo subtítulo")
        inner.base_legal_input.setText("Nova base legal")
        inner.btn_save_metadata.click()

    QTimer.singleShot(0, edit)
    inner.btn_edit_metadata.click()
    settle(app)
    assert isolated_data["title"] == "Nome alterado"
    assert isolated_data["subtitle"] == "Novo subtítulo"
    assert isolated_data["baseLegal"] == "Nova base legal"
    assert wrapper.size() == original_size
    assert_columns_reachable(inner.checklist_table, wrapper, app)


@pytest.mark.parametrize("size", [(960, 650), (800, 600), (760, 560)])
def test_real_nexo_shell_fits_small_screen_with_either_sidebar_state(app, isolated_data, tmp_path, size):
    settings = QSettings(str(tmp_path / "preferences.ini"), QSettings.Format.IniFormat)
    settings.setValue("appearance/theme", "dark")
    shell = OfficeMainWindow(Preferences(settings), factories={"checklist": create_checklist})
    shell.resize(*size)
    shell.show()
    shell.navigate("checklist")
    settle(app)
    wrapper = shell.hosts["checklist"].workspace
    inner = wrapper.workspace
    inner.expand_all_sections()
    try:
        for _ in range(2):
            settle(app)
            assert shell.size().toTuple() == size
            assert_columns_reachable(inner.checklist_table, shell, app)
            shell.sidebar.brand_button.click()
    finally:
        shell.close()
        shell.deleteLater()
        settle(app)


@pytest.mark.parametrize("size", [(760, 620), (640, 540)])
def test_standalone_checklist_stays_within_small_window(app, isolated_data, size):
    from checklist_app.theme import build_qss

    window = ChecklistMainWindow()
    window.setStyleSheet(build_qss("light"))
    window.resize(*size)
    window.show()
    window.navigate_to(CHECKLIST_PAGE)
    window.expand_all_sections()
    settle(app)
    try:
        assert window.size().toTuple() == size
        assert_columns_reachable(window.checklist_table, window, app)
    finally:
        window.close()
        window.deleteLater()
        settle(app)
