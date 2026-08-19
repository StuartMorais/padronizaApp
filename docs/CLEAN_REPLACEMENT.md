# Replacing an existing Padroniza working folder

The clean replacement archive is intended to be a complete source-tree replacement.

## If you want the cleanest folder

1. Keep the replacement ZIP outside the Padroniza folder.
2. If you want to preserve the current local Git checkout, keep `.git/`; otherwise it is safe to remove it when the remote repository is already backed up and you plan to clone/reinitialize Git later.
3. Delete the old project contents.
4. Extract the replacement archive into the empty folder.
5. Create a new `.venv` and install `requirements-dev.txt`.
6. Run `pytest -q` before starting development.

The clean replacement intentionally does not carry old virtual environments, IDE state, Python caches, pytest caches, build/dist output, `.storage-v1`, user backups, generated output, or old runtime JSON data.

The optional preserve-state archive contains the same refactored source plus the runtime `data/` and `backups/` recovered from the supplied original project snapshot. Use that archive only if those local records are needed.
