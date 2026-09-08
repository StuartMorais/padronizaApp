from __future__ import annotations

from shell.theme import normalize_theme

THEMES = {
    "light": {
        "bg": "#F5F7FB",
        "surface": "#FFFFFF",
        "surface_alt": "#F8FAFC",
        "text": "#1E293B",
        "title": "#172033",
        "muted": "#667085",
        "border": "#DFE5EF",
        "border_strong": "#C9D3E1",
        "accent": "#4F63E8",
        "accent_hover": "#4053D1",
        "accent_soft": "#EEF1FF",
        "accent_border": "#AFB9F3",
        "teal": "#0F8F87",
        "teal_hover": "#0B766F",
        "teal_soft": "#EAF7F5",
        "teal_border": "#A9D9D4",
        "danger": "#B23A48",
        "danger_soft": "#FFF4F5",
        "disabled": "#8B98AD",
        "disabled_bg": "#F6F8FB",
        "scroll": "#C5D0DE",
        "scroll_hover": "#AEBBCB",
        "table_header": "#EEF2F7",
    },
    "dark": {
        "bg": "#0F141D",
        "surface": "#161D29",
        "surface_alt": "#1B2432",
        "text": "#E7ECF4",
        "title": "#F6F8FC",
        "muted": "#9AA8BC",
        "border": "#2A3545",
        "border_strong": "#39485D",
        "accent": "#7C8CFF",
        "accent_hover": "#93A0FF",
        "accent_soft": "#252D55",
        "accent_border": "#5664B8",
        "teal": "#2EC4B6",
        "teal_hover": "#48D3C5",
        "teal_soft": "#173B39",
        "teal_border": "#356B67",
        "danger": "#FF9AA6",
        "danger_soft": "#3A2026",
        "disabled": "#6F7E92",
        "disabled_bg": "#171E29",
        "scroll": "#4A586B",
        "scroll_hover": "#5B6B80",
        "table_header": "#202A39",
    },
}


def palette(theme: str) -> dict[str, str]:
    return THEMES[normalize_theme(theme)]
