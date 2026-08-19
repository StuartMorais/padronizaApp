from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable
import threading

from app.document.conversion.backends import (
    BackendInfo,
    DocxToPdfBackend,
    default_docx_pdf_backends,
)
from app.document.conversion.pdf import (
    ConversionCancelledError,
    ConverterCapabilities,
    DocxConversionError,
    PdfConversionError,
    convert_pdf_to_docx,
    converter_capabilities,
)


class DocumentConverter:
    """Conversion boundary with fidelity-first backend selection and fallback."""

    def __init__(self, backends: Iterable[DocxToPdfBackend] | None = None) -> None:
        self._backends = list(backends) if backends is not None else default_docx_pdf_backends()
        self._state = threading.local()

    def backend_info(self) -> list[BackendInfo]:
        result: list[BackendInfo] = []
        for backend in self._backends:
            result.append(
                BackendInfo(
                    name=backend.name,
                    available=bool(backend.is_available()),
                    priority=int(backend.priority),
                    description=str(getattr(backend, "description", backend.name)),
                )
            )
        return result

    def available_backend(self) -> str:
        for backend in self._backends:
            if backend.is_available():
                return backend.name
        return "Nenhum conversor DOCX → PDF disponível"


    def last_backend(self) -> str:
        return str(getattr(self._state, "last_backend", ""))

    def capabilities(self) -> ConverterCapabilities:
        integrated = converter_capabilities()
        return ConverterCapabilities(
            docx_to_pdf=any(backend.is_available() for backend in self._backends),
            pdf_to_docx=integrated.pdf_to_docx,
            description=(
                "DOCX → PDF: seleção automática Microsoft Word → LibreOffice → conversor integrado. "
                "PDF → DOCX: conversor integrado com PyMuPDF."
            ),
        )

    def docx_to_pdf(
        self,
        source: Path | str,
        destination: Path | str,
        *,
        warnings: list[str] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> Path:
        source_path = Path(source).expanduser().resolve()
        destination_path = Path(destination).expanduser().resolve()
        warning_list = warnings if warnings is not None else []
        failures: list[str] = []
        self._state.last_backend = ""

        if cancel_check is not None and cancel_check():
            raise ConversionCancelledError("Conversão cancelada pelo usuário.")

        for backend in self._backends:
            if not backend.is_available():
                continue
            try:
                if cancel_check is None:
                    # Compatibility with custom/legacy backends that implement
                    # the original three-argument protocol.
                    result = backend.convert(source_path, destination_path, warning_list)
                else:
                    result = backend.convert(
                        source_path,
                        destination_path,
                        warning_list,
                        cancel_check=cancel_check,
                    )
                self._state.last_backend = backend.name
                return result
            except ConversionCancelledError:
                raise
            except PdfConversionError as exc:
                failures.append(f"{backend.name}: {exc}")
                warning_list.append(
                    f"Falha no backend {backend.name}; o Padroniza tentou o próximo conversor disponível."
                )

        if failures:
            raise PdfConversionError(
                "Nenhum backend conseguiu converter o DOCX para PDF.\n\n" + "\n".join(failures)
            )
        raise PdfConversionError(
            "Nenhum conversor DOCX → PDF está disponível. Instale o Microsoft Word, "
            "LibreOffice ou as dependências do conversor integrado."
        )

    def pdf_to_docx(
        self,
        source: Path | str,
        destination: Path | str,
        *,
        warnings: list[str] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> Path:
        return convert_pdf_to_docx(
            source,
            destination,
            warnings=warnings,
            cancel_check=cancel_check,
        )


DEFAULT_CONVERTER = DocumentConverter()

__all__ = [
    "BackendInfo",
    "ConversionCancelledError",
    "ConverterCapabilities",
    "DEFAULT_CONVERTER",
    "DocumentConverter",
    "DocxConversionError",
    "PdfConversionError",
]
