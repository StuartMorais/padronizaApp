"""Capture the real Qt interface. Run from any working directory."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtCore import QSettings, QTimer
from shell.application import create_application
from shell.main_window import OfficeMainWindow
from shell.preferences import Preferences


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "docs" / "preview.png")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=860)
    parser.add_argument("--page", default="home", choices=("home", "padroniza", "checklist", "settings", "about"))
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="office-preview-") as directory:
        app = create_application([])
        settings = QSettings(str(Path(directory) / "settings.ini"), QSettings.Format.IniFormat)
        window = OfficeMainWindow(Preferences(settings), factories={})
        window.resize(args.width, args.height)
        window.navigate(args.page)
        window.show()
        status = [1]

        def capture() -> None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            if window.grab().save(str(args.output)):
                status[0] = 0
                print(f"Saved {args.output} ({window.width()} x {window.height()})")
            window.close()
            app.quit()

        # Allow initial wrapping, responsive layout and painting to settle.
        QTimer.singleShot(750, capture)
        app.exec()
        return status[0]


if __name__ == "__main__":
    raise SystemExit(main())
