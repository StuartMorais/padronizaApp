from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MAIN = (ROOT / "checklist_app" / "main_window.py").read_text(encoding="utf-8")
DIALOGS = (ROOT / "checklist_app" / "scanner_dialogs.py").read_text(encoding="utf-8")
EXPORTER = (ROOT / "checklist_app" / "pdf_exporter.py").read_text(encoding="utf-8")


def test_qcombobox_is_imported_for_checklist_sheet_status_cells():
    assert "    QComboBox," in MAIN
    assert "status_combo = QComboBox()" in MAIN


def test_all_scanner_entry_points_open_same_workspace():
    assert "button.clicked.connect(self.open_scanner_workspace)" in MAIN
    assert "self.btn_scan.clicked.connect(self.open_scanner_workspace)" in MAIN
    assert "scan_button.clicked.connect(self.open_scanner_workspace)" in MAIN


def test_platform_code_is_not_exposed_in_checklist_ui_or_export():
    assert '"Código\nPlataforma"' not in MAIN
    assert '"Código Plataforma"' not in EXPORTER
    assert '"Código"' not in DIALOGS.split("setHorizontalHeaderLabels", 1)[1].split("])" ,1)[0]


def test_status_combo_column_matches_six_column_sheet():
    assert 'self.checklist_table.setCellWidget(row, 3, status_combo)' in MAIN
    assert 'editable=(column != 3)' in MAIN


def test_six_column_header_does_not_reference_removed_column_seven():
    header_block = MAIN.split("header = self.checklist_table.horizontalHeader()", 1)[1].split("layout.addWidget(self.checklist_table", 1)[0]
    assert "setSectionResizeMode(6" not in header_block
    assert "setColumnWidth(6" not in header_block


def test_checklist_refresh_preserves_scroll_position():
    assert "vertical_scroll = self.checklist_table.verticalScrollBar().value()" in MAIN
    assert "self._restore_checklist_scroll(vertical_scroll, horizontal_scroll)" in MAIN
    assert "QTimer.singleShot(0" in MAIN


def test_json_import_export_is_available_from_ui():
    assert "Importar checklist JSON…" in MAIN
    assert "Exportar checklist ativo…" in MAIN
    assert "def import_checklist_json" in MAIN
    assert "def export_active_checklist_json" in MAIN


def test_sections_have_explicit_persistent_rename_action():
    assert 'self.btn_rename_section = QPushButton("Renomear seção")' in MAIN
    assert "self.btn_rename_section.clicked.connect(self.rename_section)" in MAIN
    assert "def rename_section(self)" in MAIN
    assert 'section["title"] = new_title' in MAIN
    assert 'section_text.upper()' not in MAIN
