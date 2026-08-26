from __future__ import annotations

from pathlib import Path

from tools.resolve_release_version import bump_version, latest_version, parse_version_tag


ROOT = Path(__file__).resolve().parents[1]


def test_semver_parser_and_latest_tag_are_numeric() -> None:
    assert parse_version_tag("v1.9.9") == (1, 9, 9)
    assert parse_version_tag("2.0.0") == (2, 0, 0)
    assert parse_version_tag("release-2.0") is None
    assert latest_version(["v1.9.9", "v1.10.0", "noise", "v2.0.0"]) == (2, 0, 0)


def test_release_bumps_patch_minor_and_major() -> None:
    current = (1, 5, 9)
    assert bump_version(current, "patch") == (1, 5, 10)
    assert bump_version(current, "minor") == (1, 6, 0)
    assert bump_version(current, "major") == (2, 0, 0)
    assert bump_version(None, "patch") == (1, 0, 0)


def test_release_workflow_is_single_build_auto_version_and_github_release() -> None:
    workflow = (ROOT / ".github" / "workflows" / "build-windows.yml").read_text(encoding="utf-8")
    build_script = (ROOT / "build_github.ps1").read_text(encoding="utf-8")
    installer = (ROOT / "installer" / "Padroniza.iss").read_text(encoding="utf-8")

    assert "resolve_release_version.py" in workflow
    assert "patch" in workflow and "minor" in workflow and "major" in workflow
    assert "contents: write" in workflow
    assert "gh release create" not in workflow  # invoked through argument array for safer quoting
    assert '"release", "create"' in workflow
    assert "gh release upload" in workflow
    assert "quality_gate" not in workflow
    assert workflow.count("./build_github.ps1") == 1

    assert "pip install" not in build_script
    assert build_script.count("python -m PyInstaller") == 1
    assert "--onefile" in build_script
    assert "Padroniza-v$version.exe" in build_script
    assert "SHA256SUMS.txt" in build_script

    assert 'Source: "..\\dist\\Padroniza.exe"' in installer
    assert "Compression=lzma2/fast" in installer


def test_quality_workflow_does_not_duplicate_tag_release_build() -> None:
    workflow = (ROOT / ".github" / "workflows" / "quality.yml").read_text(encoding="utf-8")
    assert "tags-ignore:" in workflow
    assert '"v*.*.*"' in workflow
