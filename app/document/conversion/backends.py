from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from app.document.conversion.pdf import (
    ConversionCancelledError,
    PdfConversionError,
    convert_docx_to_pdf,
)


class DocxToPdfBackend(Protocol):
    name: str
    priority: int

    def is_available(self) -> bool: ...
    def convert(
        self,
        source: Path,
        destination: Path,
        warnings: list[str],
        *,
        cancel_check: Callable[[], bool] | None = None,
    ) -> Path: ...


@dataclass(frozen=True)
class BackendInfo:
    name: str
    available: bool
    priority: int
    description: str


class WordComBackend:
    name = "Microsoft Word"
    priority = 300
    description = "Microsoft Word via automação COM (maior fidelidade no Windows)"

    def is_available(self) -> bool:
        if sys.platform != "win32":
            return False
        try:
            if importlib.util.find_spec("win32com.client") is None:
                return False
            import winreg
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Word.Application\CLSID"):
                return True
        except (ImportError, ModuleNotFoundError, OSError):
            return False

    def convert(
        self,
        source: Path,
        destination: Path,
        warnings: list[str],
        *,
        cancel_check: Callable[[], bool] | None = None,
    ) -> Path:
        if cancel_check is not None and cancel_check():
            raise ConversionCancelledError("Conversão cancelada pelo usuário.")
        try:
            import win32com.client  # type: ignore[import-not-found]
        except Exception as exc:
            raise PdfConversionError("A automação do Microsoft Word não está disponível.") from exc

        word = None
        document = None
        try:
            word = win32com.client.DispatchEx("Word.Application")
            word.Visible = False
            word.DisplayAlerts = 0
            document = word.Documents.Open(str(source), ReadOnly=True, AddToRecentFiles=False)
            if cancel_check is not None and cancel_check():
                raise ConversionCancelledError("Conversão cancelada pelo usuário.")
            # wdFormatPDF = 17. SaveAs2 is broadly available in supported Word versions.
            document.SaveAs2(str(destination), FileFormat=17)
            if cancel_check is not None and cancel_check():
                raise ConversionCancelledError("Conversão cancelada pelo usuário.")
        except ConversionCancelledError:
            raise
        except Exception as exc:
            raise PdfConversionError(f"O Microsoft Word não conseguiu criar o PDF: {exc}") from exc
        finally:
            if document is not None:
                try:
                    document.Close(False)
                except Exception:
                    pass
            if word is not None:
                try:
                    word.Quit()
                except Exception:
                    pass

        if not destination.exists() or destination.stat().st_size == 0:
            raise PdfConversionError("O Microsoft Word terminou sem produzir um PDF válido.")
        return destination


class LibreOfficeBackend:
    name = "LibreOffice"
    priority = 200
    description = "LibreOffice em modo headless"

    @staticmethod
    def executable() -> Path | None:
        names = ("soffice", "libreoffice")
        for name in names:
            resolved = shutil.which(name)
            if resolved:
                return Path(resolved)

        candidates: list[Path] = []
        if sys.platform == "win32":
            for env_name in ("PROGRAMFILES", "PROGRAMFILES(X86)"):
                root = os.environ.get(env_name, "").strip()
                if root:
                    candidates.append(Path(root) / "LibreOffice" / "program" / "soffice.exe")
        elif sys.platform == "darwin":
            candidates.append(Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"))
        else:
            candidates.extend((Path("/usr/bin/libreoffice"), Path("/usr/bin/soffice")))
        return next((path for path in candidates if path.is_file()), None)

    def is_available(self) -> bool:
        return self.executable() is not None

    def convert(
        self,
        source: Path,
        destination: Path,
        warnings: list[str],
        *,
        cancel_check: Callable[[], bool] | None = None,
    ) -> Path:
        if cancel_check is not None and cancel_check():
            raise ConversionCancelledError("Conversão cancelada pelo usuário.")
        executable = self.executable()
        if executable is None:
            raise PdfConversionError("O LibreOffice não está disponível.")

        with tempfile.TemporaryDirectory(prefix="padroniza-libreoffice-") as temporary:
            out_dir = Path(temporary)
            command = [
                str(executable),
                "--headless",
                "--nologo",
                "--nodefault",
                "--nofirststartwizard",
                "--convert-to",
                "pdf",
                "--outdir",
                str(out_dir),
                str(source),
            ]
            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
            process: subprocess.Popen[str] | None = None
            try:
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    creationflags=creation_flags,
                )
                deadline = time.monotonic() + 120.0
                while process.poll() is None:
                    if cancel_check is not None and cancel_check():
                        process.terminate()
                        try:
                            process.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            process.kill()
                        raise ConversionCancelledError("Conversão cancelada pelo usuário.")
                    if time.monotonic() >= deadline:
                        process.kill()
                        raise PdfConversionError("O LibreOffice excedeu o tempo limite de 120 segundos.")
                    time.sleep(0.1)
                stdout, stderr = process.communicate()
            except ConversionCancelledError:
                raise
            except OSError as exc:
                raise PdfConversionError(f"O LibreOffice não conseguiu executar a conversão: {exc}") from exc

            produced = out_dir / f"{source.stem}.pdf"
            if process.returncode != 0 or not produced.exists() or produced.stat().st_size == 0:
                details = (stderr or stdout or "erro desconhecido").strip()
                raise PdfConversionError(f"O LibreOffice não conseguiu criar o PDF: {details}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(produced, destination)
        return destination


class IntegratedBackend:
    name = "Conversor integrado"
    priority = 100
    description = "ReportLab integrado; usado como fallback sem dependências externas"

    def is_available(self) -> bool:
        try:
            return importlib.util.find_spec("reportlab") is not None
        except (ImportError, ModuleNotFoundError):
            return False

    def convert(
        self,
        source: Path,
        destination: Path,
        warnings: list[str],
        *,
        cancel_check: Callable[[], bool] | None = None,
    ) -> Path:
        if cancel_check is not None and cancel_check():
            raise ConversionCancelledError("Conversão cancelada pelo usuário.")
        warnings.append(
            "Foi usado o conversor integrado. Recursos avançados do Word podem ser simplificados; "
            "instale/use Microsoft Word ou LibreOffice para maior fidelidade."
        )
        return convert_docx_to_pdf(
            source,
            destination,
            warnings=warnings,
            cancel_check=cancel_check,
        )


def default_docx_pdf_backends() -> list[DocxToPdfBackend]:
    return sorted(
        [WordComBackend(), LibreOfficeBackend(), IntegratedBackend()],
        key=lambda backend: backend.priority,
        reverse=True,
    )
