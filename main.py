"""The single application entry point for the Office Tools desktop shell."""
from __future__ import annotations

import logging
import sys


def main() -> int:
    try:
        from PySide6.QtWidgets import QMessageBox
        from shell.application import create_application
        from shell.main_window import OfficeMainWindow
    except ModuleNotFoundError as error:
        if error.name and error.name.startswith("PySide6"):
            print("Instale as dependências: python -m pip install -r requirements.txt")
            return 1
        raise

    application = create_application(sys.argv)
    try:
        window = OfficeMainWindow()
        window.show()
    except Exception:
        logging.exception("Unable to start Office Tools")
        QMessageBox.critical(
            None, "Office Tools", "Não foi possível iniciar o aplicativo. Consulte o arquivo de log."
        )
        return 1
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
