from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMainWindow, QMessageBox, QVBoxLayout, QWidget

from adapters.contracts import WorkspaceContext, WorkspaceFactory
from shell.catalog import ACCENT_COLORS, ModuleSpec
from shell.widgets import ScrollPage, button, icon_tile, label, page_heading, panel

logger = logging.getLogger(__name__)


class WorkspaceHost(QWidget):
    """Lazily construct a workspace once, keeping its state on navigation."""

    def __init__(self, spec: ModuleSpec, factory: WorkspaceFactory | None, context: WorkspaceContext) -> None:
        super().__init__()
        self.spec = spec
        self.factory = factory
        self.context = context
        self.workspace: QWidget | None = None
        self.loaded = False
        self.failed = False
        self.layout_box = QVBoxLayout(self)
        self.layout_box.setContentsMargins(0, 0, 0, 0)

    def ensure_loaded(self) -> None:
        if self.loaded:
            return
        self.loaded = True
        if self.factory is None:
            self.layout_box.addWidget(self._placeholder())
            return
        candidate = None
        try:
            candidate = self.factory(self.context)
            if not isinstance(candidate, QWidget) or isinstance(candidate, QMainWindow):
                raise TypeError("Workspace factories must return a QWidget, not a QMainWindow.")
            if candidate.isVisible() or candidate.parentWidget() is not None:
                raise ValueError("Return a new, unshown, unparented workspace.")
            self.workspace = candidate
            self.layout_box.addWidget(candidate)
        except Exception:
            logger.exception("Unable to load workspace %s", self.spec.key)
            if isinstance(candidate, QWidget) and candidate.parentWidget() is None:
                candidate.deleteLater()
            self.failed = True
            self.layout_box.addWidget(self._error_page())

    def _placeholder(self) -> ScrollPage:
        page = ScrollPage()
        page.body.addWidget(page_heading(self.spec.title, self.spec.subtitle))
        frame, layout = panel()
        layout.addWidget(icon_tile(self.spec.icon, ACCENT_COLORS[self.spec.accent], self.spec.accent, 68))
        layout.addWidget(label("Aguardando integração", "badge"), 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(label(f"Um espaço para o {self.spec.title}", "cardTitle", True))
        layout.addWidget(label(
            f"A navegação está pronta. As funções do {self.spec.title} serão disponibilizadas "
            "aqui após a conexão do aplicativo existente.", "body", True))
        layout.addWidget(label("  ·  ".join(self.spec.tags), "muted", True))
        home = button("←  Voltar ao início")
        home.clicked.connect(self.context.return_home)
        layout.addWidget(home, 0, Qt.AlignmentFlag.AlignLeft)
        page.body.addWidget(frame)
        page.body.addStretch(1)
        return page

    def _error_page(self) -> ScrollPage:
        page = ScrollPage()
        page.body.addWidget(page_heading(self.spec.title, "O aplicativo não pôde ser aberto."))
        frame, layout = panel()
        layout.addWidget(label("Tente abrir novamente", "cardTitle"))
        layout.addWidget(label("Ocorreu um problema ao carregar esta ferramenta. Você pode tentar novamente ou voltar ao início.", "body", True))
        retry = button("Tentar novamente", "primary")
        retry.setObjectName(f"retry_{self.spec.key}")
        retry.clicked.connect(self.retry)
        layout.addWidget(retry, 0, Qt.AlignmentFlag.AlignLeft)
        home = button("←  Voltar ao início")
        home.clicked.connect(self.context.return_home)
        layout.addWidget(home, 0, Qt.AlignmentFlag.AlignLeft)
        page.body.addWidget(frame)
        page.body.addStretch(1)
        return page

    def retry(self) -> None:
        if not self.failed:
            return
        while self.layout_box.count():
            child = self.layout_box.takeAt(0).widget()
            if child:
                child.deleteLater()
        self.loaded = False
        self.failed = False
        self.ensure_loaded()

    def allows(self, action: str) -> bool:
        if self.workspace is None:
            return True
        hook = getattr(self.workspace, action, None)
        if hook is None:
            return True
        try:
            return bool(hook())
        except Exception:
            logger.exception("Workspace %s failed during %s", self.spec.key, action)
            QMessageBox.warning(self, self.spec.title, "Não foi possível concluir a saída desta ferramenta. Tente novamente.")
            return False
