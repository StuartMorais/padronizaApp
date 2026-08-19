from __future__ import annotations

import ast
from pathlib import Path


def test_mixin_methods_bind_correctly() -> None:
    mixins_dir = Path(__file__).resolve().parents[1] / "app" / "ui" / "mixins"
    failures: list[str] = []

    for path in sorted(mixins_dir.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            for method in node.body:
                if not isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                decorators = {
                    decorator.id if isinstance(decorator, ast.Name) else decorator.attr
                    for decorator in method.decorator_list
                    if isinstance(decorator, (ast.Name, ast.Attribute))
                }
                if "staticmethod" in decorators or "classmethod" in decorators:
                    continue
                if not method.args.args or method.args.args[0].arg != "self":
                    failures.append(f"{path.name}:{node.name}.{method.name}")

    assert failures == [], "Mixin methods missing self/@staticmethod: " + ", ".join(failures)
