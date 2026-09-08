from PySide6.QtWidgets import QGridLayout

from shell import __version__
from shell.branding import APP_NAME, PRODUCT_DESCRIPTION
from shell.widgets import ScrollPage, icon_tile, label, page_heading, panel


class AboutPage(ScrollPage):
    def __init__(self) -> None:
        super().__init__()
        self.body.addWidget(page_heading("Sobre", "Duas ferramentas. Um único espaço de trabalho."))
        frame, layout = panel()
        layout.addWidget(icon_tile("grid", "#315FDB", "blue", 60))
        layout.addWidget(label(APP_NAME, "cardTitle"))
        layout.addWidget(label(f"Padroniza + Checklist  ·  Versão {__version__}", "muted"))
        layout.addWidget(label(
            PRODUCT_DESCRIPTION + " "
            "Padroniza e Checklist funcionam como módulos integrados dentro do mesmo espaço de trabalho.", "body", True))
        self.body.addWidget(frame)
        shortcuts, shortcuts_layout = panel()
        shortcuts_layout.addWidget(label("Atalhos de teclado", "sectionTitle"))
        grid = QGridLayout()
        grid.setVerticalSpacing(14)
        for row, (keys, action) in enumerate((
            ("Ctrl+1", "Ir para Início"), ("Ctrl+2", "Abrir Padroniza"),
            ("Ctrl+3", "Abrir Checklist"), ("Ctrl+,", "Abrir Configurações"), ("F1", "Abrir Sobre"),
        )):
            grid.addWidget(label(keys, "keycap"), row, 0)
            grid.addWidget(label(action), row, 1)
        grid.setColumnStretch(1, 1)
        shortcuts_layout.addLayout(grid)
        self.body.addWidget(shortcuts)
        self.body.addStretch(1)
