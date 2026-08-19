from __future__ import annotations

"""Fail when a production module is no longer reachable from ``main.py``.

This is intentionally conservative: it detects whole Python modules that have
become orphaned after refactors. It does not try to guess whether individual Qt
slots/methods are unused, because signal wiring and callbacks make that unsafe.
"""

import ast
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "app"


def _module_name(path: Path) -> str:
    relative = path.relative_to(ROOT).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _modules() -> dict[str, Path]:
    return {
        _module_name(path): path
        for path in APP_ROOT.rglob("*.py")
    }


def _imported_modules(path: Path, known: set[str]) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
            names.extend(f"{node.module}.{alias.name}" for alias in node.names)
        else:
            continue

        for name in names:
            if name in known:
                imported.add(name)
                continue
            # ``import app.package.module.symbol`` still makes the owning
            # module reachable even when the imported name is a member.
            matches = [module for module in known if name.startswith(module + ".")]
            if matches:
                imported.add(max(matches, key=len))
    return imported


def unreachable_modules() -> list[str]:
    modules = _modules()
    known = set(modules)
    graph = {
        module: _imported_modules(path, known)
        for module, path in modules.items()
    }
    roots = _imported_modules(ROOT / "main.py", known)

    reachable = set(roots)
    queue = deque(roots)
    while queue:
        module = queue.popleft()
        for dependency in graph.get(module, set()):
            if dependency in reachable:
                continue
            reachable.add(dependency)
            queue.append(dependency)

    return sorted(
        module
        for module, path in modules.items()
        if path.name != "__init__.py" and module not in reachable
    )


def main() -> int:
    dead = unreachable_modules()
    if not dead:
        print("Dead-code module check: OK (all production modules reachable from main.py)")
        return 0

    print("Dead-code module check failed. Unreachable production modules:")
    for module in dead:
        print(f"  - {module}")
    print("Delete/reconnect these modules, or explicitly update the checker if a new runtime entry point is intentional.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
