from __future__ import annotations

from shell.icons import ASSET_ROOT

VALID_THEMES = {"light", "dark"}


def normalize_theme(theme: str | None) -> str:
    value = str(theme or "light").strip().lower()
    return value if value in VALID_THEMES else "light"


def stylesheet(theme: str = "light") -> str:
    selected = normalize_theme(theme)
    path = ASSET_ROOT / "styles" / f"{selected}.qss"
    return path.read_text(encoding="utf-8")
