#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
if [ ! -x .venv/bin/python ]; then
    python3 -m venv .venv
fi
if ! .venv/bin/python -c 'import sys, struct; print("Python " + sys.version.split()[0] + " - " + str(struct.calcsize("P") * 8) + " bits"); sys.exit(0 if (3, 10) <= sys.version_info[:2] < (3, 15) and struct.calcsize("P") == 8 else 1)'; then
    echo 'Este pacote requer Python 3.10 a 3.14 de 64 bits. Consulte o README.md.' >&2
    exit 1
fi
if ! .venv/bin/python -c 'from importlib.metadata import version; assert version("PySide6-Essentials") == "6.10.3"; assert version("shiboken6") == "6.10.3"; from PySide6.QtWidgets import QApplication; from PySide6.QtSvg import QSvgRenderer; import docx, reportlab, fitz, PIL' >/dev/null 2>&1; then
    .venv/bin/python -m pip install -r requirements.txt
fi
exec .venv/bin/python main.py
