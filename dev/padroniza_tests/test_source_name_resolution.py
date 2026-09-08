from __future__ import annotations

"""Cheap source-level guard for undefined global names.

Ruff is the authoritative static checker in the Windows quality gate.  This
built-in-Python check keeps one important class of regression visible even in
minimal/offline environments where Ruff is not installed (for example the
Linux artifact review environment).
"""

import builtins
import symtable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "app"


def _undefined_global_references(path: Path) -> list[tuple[str, str]]:
    source = path.read_text(encoding="utf-8")
    module_table = symtable.symtable(source, str(path), "exec")
    module_names = {
        symbol.get_name()
        for symbol in module_table.get_symbols()
        if symbol.is_assigned() or symbol.is_imported() or symbol.is_namespace()
    }
    module_names.update(dir(builtins))

    problems: list[tuple[str, str]] = []

    def visit(table: symtable.SymbolTable) -> None:
        for symbol in table.get_symbols():
            name = symbol.get_name()
            if (
                symbol.is_referenced()
                and symbol.is_global()
                and name not in module_names
                and not name.startswith("__")
            ):
                problems.append((table.get_name(), name))
        for child in table.get_children():
            visit(child)

    visit(module_table)
    return problems


def test_application_sources_do_not_reference_undefined_globals() -> None:
    problems: list[str] = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        for scope, name in _undefined_global_references(path):
            problems.append(f"{path.relative_to(ROOT)} :: {scope} -> {name}")

    assert not problems, "Undefined global references:\n" + "\n".join(problems)
