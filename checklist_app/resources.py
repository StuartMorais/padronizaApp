from __future__ import annotations

import sys
from pathlib import Path


def project_root() -> Path:
    """Return the Nexo source root or the PyInstaller bundle root."""
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        return Path(bundle_root)
    return Path(__file__).resolve().parents[1]


def resource_path(relative_path: str) -> Path:
    """Resolve Checklist resources inside the combined Nexo assets tree."""
    relative = Path(relative_path)
    if relative.parts and relative.parts[0].lower() == "assets":
        relative = Path(*relative.parts[1:])
    return project_root() / "assets" / "checklist" / relative
