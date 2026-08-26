# DOCM input and GitHub release pipeline — 2026-08

## DOCM support

Padroniza accepts `.docx`, `.docm`, and `.pdf` as template source inputs. DOCX remains the canonical editable template format.

A DOCM is not opened directly by `python-docx` or by an external converter. `app/document/word_package.py` reads the OOXML package, removes VBA project/data/signature parts and macro relationships, rewrites the main document content type to standard DOCX, validates the resulting ZIP, and returns an inert `.docx` working copy. The original DOCM is untouched.

This is intentional security behavior: Padroniza scans document structure and content but does not execute or preserve VBA macros. DOCM → PDF conversion uses the normalized DOCX copy before the Microsoft Word, LibreOffice, or integrated backend is selected.

## Release workflow

`.github/workflows/build-windows.yml` is the fast packaging workflow.

For a manual run, choose one bump type:

- `patch`: `1.5.9 → 1.5.10`
- `minor`: `1.5.9 → 1.6.0`
- `major`: `1.5.9 → 2.0.0`

`tools/resolve_release_version.py` reads all Git tags matching `vMAJOR.MINOR.PATCH`, chooses the highest numeric semantic version, and calculates the next one. If the repository has no semantic version tags yet, the first release is `v1.0.0`.

The packaging path is:

```text
checkout + tags
↓
resolve version
↓
install runtime/build requirements once
↓
compileall + dead-module preflight
↓
PyInstaller --onefile exactly once
↓
portable Padroniza-vX.Y.Z.exe
↓
same dist/Padroniza.exe → Inno Setup
↓
Padroniza-Setup-vX.Y.Z.exe
↓
SHA256SUMS.txt
↓
gh release create/upload
```

The release workflow has `contents: write` permission. Manual runs may create the release tag at the selected commit through `gh release create --target`; explicit `vX.Y.Z` tag pushes are also supported.

The full Windows quality workflow deliberately ignores semantic release tags. It remains the authoritative test/type/UI gate for ordinary pushes and pull requests, while release packaging performs a short preflight instead of duplicating the entire suite.
