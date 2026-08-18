from __future__ import annotations

import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app.docx_engine import generate_docx
from app.local_data import LocalDataStore
from app.output_planner import OutputPlanner
from app.pdf_converter import convert_docx_to_pdf
from app.template_loader import TemplatePackage


@dataclass(frozen=True)
class GenerationResult:
    document_id: str
    output_path: Path
    format: str


class GenerationService:
    """Orchestrate document generation independently from the Qt UI."""

    def __init__(
        self,
        local_store: LocalDataStore,
        output_planner: OutputPlanner | None = None,
    ) -> None:
        self.local_store = local_store
        self.output_planner = output_planner or OutputPlanner(local_store)

    def generate_docx(
        self,
        package: TemplatePackage,
        values: dict[str, Any],
        output_path: Path,
        *,
        profile_id: str = "",
        profile_name: str = "",
    ) -> GenerationResult:
        output_path = Path(output_path)
        generate_docx(package.source_path, output_path, values)

        # Commit numbering only after a real document was produced.
        self.output_planner.commit_sequence(package)
        document_id = self._record_generation(
            package,
            values,
            output_path,
            format_name="docx",
            profile_id=profile_id,
            profile_name=profile_name,
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
        output_path = Path(output_path)
        with tempfile.TemporaryDirectory(prefix="padroniza-pdf-") as temporary_folder:
            temporary_docx = Path(temporary_folder) / f"{output_path.stem}.docx"
            generate_docx(package.source_path, temporary_docx, values)
            convert_docx_to_pdf(temporary_docx, output_path)

        # PDF conversion is part of generation, so numbering is committed only
        # after both the DOCX fill and PDF conversion succeed.
        self.output_planner.commit_sequence(package)
        document_id = self._record_generation(
            package,
            values,
            output_path,
            format_name="pdf",
            profile_id=profile_id,
            profile_name=profile_name,
        )
        return GenerationResult(document_id, output_path, "pdf")

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
