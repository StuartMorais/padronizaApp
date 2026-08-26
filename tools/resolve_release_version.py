from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path
from typing import Iterable


_VERSION_TAG = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$", re.IGNORECASE)


def parse_version_tag(value: str) -> tuple[int, int, int] | None:
    match = _VERSION_TAG.fullmatch(str(value).strip())
    if match is None:
        return None
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def latest_version(tags: Iterable[str]) -> tuple[int, int, int] | None:
    versions = [version for tag in tags if (version := parse_version_tag(tag)) is not None]
    return max(versions) if versions else None


def bump_version(
    current: tuple[int, int, int] | None,
    bump: str,
) -> tuple[int, int, int]:
    normalized = str(bump).strip().casefold()
    if normalized not in {"patch", "minor", "major"}:
        raise ValueError("O incremento deve ser patch, minor ou major.")

    # A repository without semantic release tags starts at the stable 1.0.0.
    if current is None:
        return (1, 0, 0)

    major, minor, patch = current
    if normalized == "major":
        return (major + 1, 0, 0)
    if normalized == "minor":
        return (major, minor + 1, 0)
    return (major, minor, patch + 1)


def semantic_version_text(version: tuple[int, int, int]) -> str:
    return ".".join(str(part) for part in version)


def git_tags() -> list[str]:
    completed = subprocess.run(
        ["git", "tag", "--list"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


def write_github_output(path: Path, *, version: str, tag: str) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(f"version={version}\n")
        stream.write(f"tag={tag}\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Calcula a próxima versão SemVer do Padroniza a partir das tags Git."
    )
    parser.add_argument("--bump", choices=("patch", "minor", "major"), default="patch")
    parser.add_argument("--github-output", type=Path)
    arguments = parser.parse_args()

    current = latest_version(git_tags())
    next_version = bump_version(current, arguments.bump)
    version = semantic_version_text(next_version)
    tag = f"v{version}"

    previous = semantic_version_text(current) if current is not None else "nenhuma"
    print(f"Versão anterior: {previous}")
    print(f"Próxima versão: {version}")
    print(f"Tag: {tag}")

    if arguments.github_output is not None:
        write_github_output(arguments.github_output, version=version, tag=tag)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
