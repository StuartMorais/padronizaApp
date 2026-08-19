from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def staged_output(destination: Path | str, *, suffix: str | None = None) -> Iterator[Path]:
    """Yield a temporary path on the destination filesystem, then clean it up.

    Callers validate the staged artifact and explicitly publish it with
    :func:`publish_staged_output`. Keeping the temp file in the same directory
    makes the final ``os.replace`` atomic on normal local filesystems.
    """

    destination_path = Path(destination).expanduser().resolve()
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_suffix = suffix if suffix is not None else destination_path.suffix
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination_path.stem}-",
        suffix=f".staged{resolved_suffix}",
        dir=str(destination_path.parent),
    )
    os.close(fd)
    temporary_path = Path(temporary_name)
    temporary_path.unlink(missing_ok=True)
    try:
        yield temporary_path
    finally:
        temporary_path.unlink(missing_ok=True)


def publish_staged_output(staged: Path | str, destination: Path | str) -> Path:
    staged_path = Path(staged).resolve()
    destination_path = Path(destination).expanduser().resolve()
    if not staged_path.is_file():
        raise FileNotFoundError(f"Arquivo temporário não encontrado: {staged_path}")
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staged_path, destination_path)
    return destination_path
