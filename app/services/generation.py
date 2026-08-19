from __future__ import annotations

import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app.document.docx.generator import DocumentGenerationError, generate_docx
from app.document.diagnostics import diagnose_template
from app.repositories.local_data import LocalDataStore
from app.services.output_planner import OutputPlanner
from app.document.conversion.service import DocumentConverter, PdfConversionError
from app.core.atomic_output import publish_staged_output, staged_output
from app.services.templates import TemplatePackage


@dataclass(frozen=True)
class GenerationResult:
    document_id: str
    output_path: Path
    format: str
    warnings: tuple[str, ...] = ()
    conversion_backend: str = ""


class GenerationService:
    """Orchestrate document generation independently from the Qt UI."""

    def __init__(
        self,
        local_store: LocalDataStore,
        output_planner: OutputPlanner | None = None,
        converter: DocumentConverter | None = None,
    ) -> None:
        self.local_store = local_store
        self.output_planner = output_planner or OutputPlanner(local_store)
        self.converter = converter or DocumentConverter()

    def generate_docx(
        self,
        package: TemplatePackage,
        values: dict[str, Any],
        output_path: Path,
        *,
        profile_id: str = "",
        profile_name: str = "",
    ) -> GenerationResult:
        output_path = Path(output_path).expanduser().resolve()
        self._preflight(package)
        try:
            with staged_output(output_path, suffix=".docx") as staged:
                generate_docx(package.source_path, staged, values)
                self._validate_docx(staged)
                publish_staged_output(staged, output_path)
        except DocumentGenerationError:
            raise
        except Exception as exc:
            raise DocumentGenerationError(
                f"Não foi possível publicar o DOCX gerado: {exc}"
            ) from exc

        # Numbering and history are side effects only after a complete artifact
        # has been validated and atomically published.
        self.output_planner.commit_sequence(package)
        document_id = self._record_generation(
            package, values, output_path, format_name="docx",
            profile_id=profile_id, profile_name=profile_name,
        )
        return GenerationResult(document_id, output_path, "docx")

    def generate_pdf(
        self,
        package: TemplatePackage,
        values: dict[str, Any],
        output_path: Path,
        *,
        profile_id: str = "",
        profile_name: str = "",
    ) -> GenerationResult:
        output_path = Path(output_path).expanduser().resolve()
        self._preflight(package)
        warnings: list[str] = []
        backend = self.converter.available_backend()
        with tempfile.TemporaryDirectory(prefix="padroniza-pdf-") as temporary_folder:
            temporary_docx = Path(temporary_folder) / f"{output_path.stem}.docx"
            generate_docx(package.source_path, temporary_docx, values)
            self._validate_docx(temporary_docx)
            try:
                with staged_output(output_path, suffix=".pdf") as staged_pdf:
                    self.converter.docx_to_pdf(temporary_docx, staged_pdf, warnings=warnings)
                    if hasattr(self.converter, "last_backend"):
                        backend = self.converter.last_backend() or backend
                    self._validate_pdf(staged_pdf)
                    publish_staged_output(staged_pdf, output_path)
            except PdfConversionError:
                raise
            except Exception as exc:
                raise PdfConversionError(
                    f"Não foi possível publicar o PDF gerado: {exc}"
                ) from exc

        self.output_planner.commit_sequence(package)
        document_id = self._record_generation(
            package, values, output_path, format_name="pdf",
            profile_id=profile_id, profile_name=profile_name,
        )
        return GenerationResult(
            document_id, output_path, "pdf", tuple(warnings), backend
        )

    @staticmethod
    def _preflight(package: TemplatePackage) -> None:
        report = diagnose_template(package.config, package.source_path)
        if not report.get("blocking"):
            return
        blocking = [
            issue for issue in report.get("issues", [])
            if issue.get("severity") == "error"
        ]
        details = "; ".join(
            (f"{issue.get('field_id')}: " if issue.get('field_id') else "")
            + str(issue.get("message", ""))
            for issue in blocking[:5]
        )
        raise DocumentGenerationError(
            "O modelo possui problemas estruturais que impedem uma geração segura."
            + (f"\n\n{details}" if details else "")
        )

    @staticmethod
    def _validate_docx(path: Path) -> None:
        try:
            if not path.is_file() or path.stat().st_size == 0:
                raise ValueError("arquivo vazio")
            with zipfile.ZipFile(path, "r") as archive:
                names = set(archive.namelist())
                if "word/document.xml" not in names or "[Content_Types].xml" not in names:
                    raise ValueError("pacote DOCX incompleto")
                broken = archive.testzip()
                if broken:
                    raise ValueError(f"entrada ZIP corrompida: {broken}")
        except (OSError, zipfile.BadZipFile, ValueError) as exc:
            raise DocumentGenerationError(
                f"O DOCX gerado não passou pela validação final: {exc}"
            ) from exc

    @staticmethod
    def _validate_pdf(path: Path) -> None:
        try:
            if not path.is_file() or path.stat().st_size < 5:
                raise ValueError("arquivo vazio")
            with path.open("rb") as handle:
                header = handle.read(5)
            if header != b"%PDF-":
                raise ValueError("assinatura PDF inválida")
        except (OSError, ValueError) as exc:
            raise PdfConversionError(
                f"O PDF gerado não passou pela validação final: {exc}"
            ) from exc

    def _record_generation(
        self,
        package: TemplatePackage,
        values: dict[str, Any],
        output_path: Path,
        *,
        format_name: str,
        profile_id: str,
        profile_name: str,
    ) -> str:
        is_pdf = format_name == "pdf"
        record = {
            "template_id": package.template_id,
            "template_name": package.name,
            "template_version": package.version,
            "filename": output_path.name,
            "docx_path": "" if is_pdf else str(output_path),
            "pdf_path": str(output_path) if is_pdf else "",
            "zip_path": "",
            "values": values,
            "pdf_error": "",
            "created_at": datetime.now().replace(microsecond=0).isoformat(),
            **self._history_metadata(
                values,
                profile_id=profile_id,
                profile_name=profile_name,
            ),
        }
        document_id = self.local_store.add_recent(record)
        details = {
            "document_id": document_id,
            "template_id": package.template_id,
            "path": str(output_path),
        }
        if is_pdf:
            details["format"] = "pdf"
        self.local_store.add_audit(
            "document_generated",
            output_path.name,
            details,
        )
        return document_id

    @staticmethod
    def _history_metadata(
        values: dict[str, Any],
        *,
        profile_id: str,
        profile_name: str,
    ) -> dict[str, str]:
        process_number = ""
        preferred = (
            "process.number",
            "process_number",
            "processo.numero",
            "processo",
        )
        for key in preferred:
            value = values.get(key)
            if value not in (None, ""):
                process_number = str(value)
                break

        if not process_number:
            for key, value in values.items():
                normalized = str(key).casefold()
                if "process" in normalized and (
                    "number" in normalized or "numero" in normalized
                ):
                    process_number = str(value)
                    break

        return {
            "process_number": process_number,
            "profile_id": profile_id,
            "profile_name": profile_name,
        }
