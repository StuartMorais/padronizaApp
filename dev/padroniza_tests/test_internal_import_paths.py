from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = PROJECT_ROOT / "app"


def _module_exists(name: str) -> bool:
    parts = name.split(".")
    if not parts or parts[0] != "app":
        return True
    base = PROJECT_ROOT.joinpath(*parts)
    return base.with_suffix(".py").is_file() or (base / "__init__.py").is_file()


def test_all_static_app_import_modules_exist():
    missing: list[str] = []
    for path in APP_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names if alias.name.startswith("app.")]
            elif isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app"):
                modules = [node.module]
            else:
                continue
            for module in modules:
                if not _module_exists(module):
                    missing.append(f"{path.relative_to(PROJECT_ROOT)} -> {module}")

    assert not missing, "Missing internal modules:\n" + "\n".join(sorted(set(missing)))


def test_smart_template_can_be_imported_before_docx_scanner_in_fresh_python() -> None:
    """The DOCX package must not depend on import order."""
    import subprocess
    import sys
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.document.understanding.smart_template import smart_fields_from_docx; "
            "from app.document.docx.scanner import scan_docx_fields; "
            "assert callable(smart_fields_from_docx) and callable(scan_docx_fields)",
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
