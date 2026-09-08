from __future__ import annotations

from pathlib import Path

import pytest

from app.document.conversion.pdf import PdfConversionError
from app.document.conversion.service import DocumentConverter


class FakeBackend:
    def __init__(self, name: str, *, available: bool = True, fail: bool = False, priority: int = 1):
        self.name = name
        self.description = name
        self.priority = priority
        self._available = available
        self._fail = fail
        self.calls = 0

    def is_available(self) -> bool:
        return self._available

    def convert(self, source: Path, destination: Path, warnings: list[str]) -> Path:
        self.calls += 1
        if self._fail:
            raise PdfConversionError("falhou")
        destination.write_bytes(b"%PDF-1.4\n")
        return destination


def test_converter_uses_first_available_backend(tmp_path):
    first = FakeBackend("first", available=False, priority=2)
    second = FakeBackend("second", priority=1)
    converter = DocumentConverter([first, second])
    source = tmp_path / "a.docx"
    source.write_bytes(b"docx")
    destination = tmp_path / "a.pdf"

    converter.docx_to_pdf(source, destination)
    assert first.calls == 0
    assert second.calls == 1
    assert converter.available_backend() == "second"


def test_converter_falls_back_after_backend_failure(tmp_path):
    first = FakeBackend("Word", fail=True, priority=2)
    second = FakeBackend("fallback", priority=1)
    converter = DocumentConverter([first, second])
    source = tmp_path / "a.docx"
    source.write_bytes(b"docx")
    destination = tmp_path / "a.pdf"
    warnings: list[str] = []

    converter.docx_to_pdf(source, destination, warnings=warnings)
    assert first.calls == 1
    assert second.calls == 1
    assert any("Word" in warning for warning in warnings)


def test_converter_reports_backend_that_actually_succeeded(tmp_path):
    first = FakeBackend("Word", fail=True, priority=2)
    second = FakeBackend("LibreOffice", priority=1)
    converter = DocumentConverter([first, second])
    source = tmp_path / "a.docx"
    source.write_bytes(b"docx")
    destination = tmp_path / "a.pdf"

    converter.docx_to_pdf(source, destination)
    assert converter.last_backend() == "LibreOffice"


def test_converter_honors_cancellation_before_start(tmp_path):
    from app.document.conversion.service import ConversionCancelledError

    backend = FakeBackend("fallback")
    converter = DocumentConverter([backend])

    with pytest.raises(ConversionCancelledError):
        converter.docx_to_pdf(
            tmp_path / "missing.docx",
            tmp_path / "missing.pdf",
            cancel_check=lambda: True,
        )

    assert backend.calls == 0
