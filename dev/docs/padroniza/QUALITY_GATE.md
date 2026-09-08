# Quality Gate

Padroniza now treats architecture, tests, static analysis and GUI startup as one release gate.

## Local Windows command

After installing `requirements-dev.txt`, run from the repository root:

```powershell
./tools/run_quality_gate.ps1
```

The command performs, in order:

1. Python bytecode compilation for `app`, `tests` and `tools`.
2. Production-module reachability (`tools/check_dead_code.py`).
3. Ruff correctness checks.
4. Pyright type checks for the typed core/domain/service boundary.
5. Scanner V6 semantic benchmark (`tools/check_semantic_benchmark.py`): required real-document regions, zero unexpected regions, and no fresh semantic auto-selection.
6. The complete pytest suite with core coverage and a 75% minimum baseline.
7. Offscreen PySide6 smoke tests for the main pages, dialogs, template editor and widgets.
8. A real `main.py --smoke-test` startup using isolated temporary storage.

## Coverage policy

Coverage is intentionally enforced on the non-UI application core:

- `app.core`
- `app.domain`
- `app.document`
- `app.repositories`
- `app.services`

Qt screens use constructor/navigation smoke tests instead of chasing line coverage through event-loop and painting code. The current 75% threshold is a floor, not a target; it should only move upward as meaningful regression tests are added.

## Ruff policy

Ruff currently enforces correctness-oriented rules (`F` plus `E9`). It deliberately does not impose a global formatting rewrite. This catches undefined names, unused imports/locals, duplicate definitions and syntax-level problems while preserving the existing visual coding style.

## Pyright policy

Pyright runs in `basic` mode over the most stable typed boundaries first: domain models, application services, local stores and atomic/schema helpers. The include set can be expanded as older/dynamic UI and document-inference code gains stronger annotations.

## Dead-code policy

`tools/check_dead_code.py` builds the production import graph from `main.py` and fails if a Python module under `app/` becomes unreachable. This intentionally checks whole modules only; individual Qt slots are not guessed as dead because callbacks and signals can reference them indirectly.

## CI

`.github/workflows/quality.yml` runs the full quality gate on Windows for normal pushes, pull requests, and manual quality runs. Semantic release tags (`v*.*.*`) are ignored by that workflow so packaging does not launch the same expensive test/type/UI suite a second time.

`.github/workflows/build-windows.yml` is intentionally a fast packaging/release workflow: it installs runtime/build dependencies once, runs bytecode compilation, the dead-module check and the fast semantic benchmark, invokes PyInstaller once, builds the Inno Setup installer from that same executable, and publishes the resulting assets directly to GitHub Releases. Manual runs calculate the next semantic version from existing Git tags (`patch`, `minor`, or `major`); tag-triggered runs use the pushed version. Repository branch protection/normal CI should therefore remain the authoritative full-quality gate before merging code that will be released.
