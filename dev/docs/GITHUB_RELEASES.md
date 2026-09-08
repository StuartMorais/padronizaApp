# GitHub Windows build / release

Office Tools is configured to build Windows releases in GitHub Actions.

## Generated files

Every release build produces:

- `OfficeTools-vX.Y.Z.exe` — portable one-file executable
- `OfficeTools-Setup-vX.Y.Z.exe` — Inno Setup installer
- `SHA256SUMS.txt` — SHA-256 checksums

The same PyInstaller executable is used for the portable asset and inside the installer.

## Manual release from GitHub

1. Push the project to GitHub.
2. Open **Actions**.
3. Choose **Build and release Office Tools for Windows**.
4. Click **Run workflow**.
5. Choose `patch`, `minor`, or `major`.
6. The workflow calculates the next semantic version from existing `vX.Y.Z` Git tags, builds the EXE/installer, and creates the GitHub Release.

If the repository has no semantic release tag yet, the first manual release is `v1.0.0`.

## Release by Git tag

Pushing a tag such as:

```text
v1.2.0
```

also starts the release workflow. Tag-triggered releases use the exact tag version.

## Main build files

- `.github/workflows/build-windows.yml`
- `.github/workflows/quality.yml`
- `scripts/build_github.ps1`
- `installer/OfficeTools.iss`
- `tools/resolve_release_version.py`
- `requirements-build.txt`

## Bundled application resources

PyInstaller embeds the shared `assets/` tree, the Padroniza `templates/` seed directory, and `app/ui/styles/`. Writable Padroniza and Checklist user data are intentionally not embedded; both modules continue to use their persistent Windows data locations.
