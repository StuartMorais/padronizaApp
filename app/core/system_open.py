from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from pathlib import Path


class SystemOpenError(RuntimeError):
    """Raised when the operating system cannot open a local path."""


_WINDOWS_SHELL_ERRORS = {
    0: "O Windows ficou sem memória ou recursos para concluir a ação.",
    2: "O arquivo informado não foi encontrado.",
    3: "O caminho informado não foi encontrado.",
    5: "O acesso ao arquivo ou à pasta foi negado.",
    8: "O Windows ficou sem memória para concluir a ação.",
    26: "O compartilhamento de arquivos não está disponível.",
    27: "A associação deste tipo de arquivo está incompleta.",
    28: "A operação excedeu o tempo limite.",
    29: "Não foi possível concluir a associação do arquivo.",
    30: "O aplicativo associado está ocupado.",
    31: "Nenhum aplicativo está associado a este tipo de arquivo.",
    32: "A biblioteca necessária para abrir o arquivo não foi encontrada.",
}


def open_file(path: str | Path) -> Path:
    """Open a file with the operating system's default application."""

    target = _normalized_path(path)
    if not target.is_file():
        raise SystemOpenError(
            "O arquivo não existe ou não está mais disponível.\n\n"
            f"Caminho: {target}"
        )

    _open_path(target, is_directory=False)
    return target


def open_folder(path: str | Path) -> Path:
    """Open a folder in the operating system's file manager."""

    target = _normalized_path(path)
    if not target.is_dir():
        raise SystemOpenError(
            "A pasta não existe ou não está mais disponível.\n\n"
            f"Caminho: {target}"
        )

    _open_path(target, is_directory=True)
    return target


def _normalized_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def _open_path(
    target: Path,
    *,
    is_directory: bool,
) -> None:
    if os.name == "nt":
        _open_windows_path(
            target,
            is_directory=is_directory,
        )
        return

    if sys.platform == "darwin":
        command = ["open", os.fspath(target)]
    else:
        command = ["xdg-open", os.fspath(target)]

    try:
        subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        raise SystemOpenError(
            "O sistema não conseguiu abrir este caminho.\n\n"
            f"Caminho: {target}\n"
            f"Detalhes: {exc}"
        ) from exc


def _open_windows_path(
    target: Path,
    *,
    is_directory: bool,
) -> None:
    errors: list[str] = []
    startfile = getattr(os, "startfile", None)

    if callable(startfile):
        try:
            startfile(os.fspath(target), "open")
            return
        except OSError as exc:
            errors.append(str(exc))

    shell_result = _windows_shell_execute(target)
    if shell_result > 32:
        return

    shell_message = _WINDOWS_SHELL_ERRORS.get(
        shell_result,
        f"Falha do Windows de código {shell_result}.",
    )
    errors.append(shell_message)

    # A pasta pode ser aberta diretamente pelo Explorer mesmo quando a
    # associação de URLs do Qt não está disponível na versão empacotada.
    if is_directory:
        try:
            creation_flags = int(
                getattr(
                    subprocess,
                    "CREATE_NO_WINDOW",
                    0,
                )
            )
            subprocess.Popen(
                ["explorer.exe", os.fspath(target)],
                close_fds=True,
                creationflags=creation_flags,
            )
            return
        except OSError as exc:
            errors.append(str(exc))

    detail = "\n".join(
        f"• {message}"
        for message in errors
        if message
    )
    raise SystemOpenError(
        "O Windows não conseguiu abrir este caminho.\n\n"
        f"Caminho: {target}"
        + (f"\n\nDetalhes:\n{detail}" if detail else "")
    )


def _windows_shell_execute(target: Path) -> int:
    try:
        shell_execute = ctypes.windll.shell32.ShellExecuteW
        shell_execute.argtypes = [
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_int,
        ]
        shell_execute.restype = ctypes.c_void_p

        working_directory = (
            target
            if target.is_dir()
            else target.parent
        )
        result = shell_execute(
            None,
            "open",
            os.fspath(target),
            None,
            os.fspath(working_directory),
            1,
        )
        return int(result or 0)
    except (AttributeError, OSError, TypeError, ValueError):
        return 0
