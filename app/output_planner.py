from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from app.local_data import LocalDataStore
from app.template_loader import TemplatePackage


@dataclass(frozen=True)
class PlannedOutput:
    path: Path
    sequence: int | None = None


class OutputPlanner:
    """Build output names/folders and manage template numbering.

    The planner only *peeks* at numbering while calculating a path. The
    sequence is committed explicitly after generation succeeds, preventing a
    failed generation from consuming a document number.
    """

    def __init__(self, local_store: LocalDataStore) -> None:
        self.local_store = local_store

    def filename_preview(
        self,
        package: TemplatePackage,
        values: dict[str, Any],
    ) -> str:
        return self._filename(
            package,
            values,
            self.peek_sequence(package),
        )

    def plan(
        self,
        package: TemplatePackage,
        values: dict[str, Any],
        *,
        output_root: Path,
        override_root: Path | None = None,
    ) -> PlannedOutput:
        sequence = self.peek_sequence(package)
        filename = self._filename(package, values, sequence)

        root = Path(override_root or output_root)
        folder_pattern = str(
            package.config.get("output", {}).get("folder_pattern", "")
        ).strip()
        if folder_pattern and override_root is None:
            # Split before rendering: values such as CNPJ may contain a slash
            # and must remain within one sanitized folder name.
            for pattern_segment in re.split(r"[\\/]+", folder_pattern):
                rendered_segment = self.render_pattern(
                    pattern_segment,
                    package,
                    values,
                    sequence,
                )
                cleaned = self.sanitize_segment(rendered_segment)
                if cleaned and cleaned not in {".", ".."}:
                    root /= cleaned

        root.mkdir(parents=True, exist_ok=True)
        return PlannedOutput(path=root / filename, sequence=sequence)


    def _filename(
        self,
        package: TemplatePackage,
        values: dict[str, Any],
        sequence: int | None,
    ) -> str:
        filename = self.render_pattern(
            package.config.get("output", {}).get(
                "filename_pattern",
                package.output_filename,
            ),
            package,
            values,
            sequence,
        )
        filename = self.sanitize_filename(filename)
        if not filename.casefold().endswith(".docx"):
            filename += ".docx"
        return filename

    def peek_sequence(self, package: TemplatePackage) -> int | None:
        numbering = package.config.get("numbering", {})
        if not bool(numbering.get("enabled", False)):
            return None
        return self.local_store.peek_sequence(self._sequence_key(package))

    def commit_sequence(self, package: TemplatePackage) -> int | None:
        numbering = package.config.get("numbering", {})
        if not bool(numbering.get("enabled", False)):
            return None
        return self.local_store.next_sequence(self._sequence_key(package))

    @staticmethod
    def _sequence_key(package: TemplatePackage) -> str:
        numbering = package.config.get("numbering", {})
        return str(numbering.get("key", package.template_id)) or package.template_id

    @staticmethod
    def render_pattern(
        pattern: Any,
        package: TemplatePackage,
        values: dict[str, Any],
        sequence: int | None,
    ) -> str:
        result = str(pattern or "")
        padding = int(package.config.get("numbering", {}).get("padding", 4) or 4)
        tokens: dict[str, str] = {
            "template.name": package.name,
            "template.id": package.template_id,
            "template.version": package.version,
            "year": str(date.today().year),
            "sequence": str(sequence).zfill(padding) if sequence is not None else "",
        }
        for field_id, value in values.items():
            tokens[field_id] = (
                "Sim" if value is True else "Não" if value is False else str(value or "")
            )
        for key, value in tokens.items():
            result = result.replace(f"{{{{{key}}}}}", value)
            result = result.replace(f"{{{{date:{key}}}}}", value)
        return result

    @staticmethod
    def sanitize_filename(value: str) -> str:
        cleaned = re.sub(r'[<>:"/\\|?*]', "-", str(value))
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
        return cleaned or "generated_document.docx"

    @staticmethod
    def sanitize_segment(value: str) -> str:
        cleaned = re.sub(r'[<>:"/\\|?*]', "-", str(value))
        return re.sub(r"\s+", " ", cleaned).strip(" .")[:120]
