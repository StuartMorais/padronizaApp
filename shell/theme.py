from shell.icons import ASSET_ROOT


def stylesheet() -> str:
    return (ASSET_ROOT / "styles" / "light.qss").read_text(encoding="utf-8")
