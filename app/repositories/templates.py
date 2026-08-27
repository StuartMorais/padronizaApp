from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import unicodedata
import zipfile
from copy import deepcopy
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from app.domain.fields import FieldDefinition
from app.domain.field_metadata import (
    DYNAMIC_SCOPES,
    REPEATABLE_LIST_PUNCTUATIONS,
    REPEATABLE_LIST_STYLES,
    compact_dropdown_options,
    normalize_repeatable_columns,
    source_anchor_errors,
)
from app.domain.field_types import FIELD_TYPE_ALIASES, SUPPORTED_FIELD_TYPES
from app.domain.validation import infer_field_type
from app.core.json_io import atomic_write_json
from app.core.schema import TEMPLATE_SCHEMA_VERSION, SchemaVersionError
from app.document.diagnostics import diagnose_template
from app.document.word_package import WORD_INPUT_SUFFIXES, normalize_word_input


MAX_TEMPLATE_PACKAGE_FILES = 100
MAX_TEMPLATE_PACKAGE_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
MAX_TEMPLATE_PACKAGE_MEMBER_BYTES = 80 * 1024 * 1024


class TemplatePreflightError(ValueError):
    """Raised when a template has blocking structural/document problems."""

    def __init__(self, report: dict[str, Any]) -> None:
        self.report = report
        issues = [
            issue for issue in report.get("issues", [])
            if issue.get("severity") == "error"
        ]
        summary = "; ".join(
            (f"{issue.get('field_id')}: " if issue.get('field_id') else "")
            + str(issue.get("message", ""))
            for issue in issues[:5]
        )
        if len(issues) > 5:
            summary += f"; e mais {len(issues) - 5} problema(s)"
        super().__init__(
            "O modelo não passou pela verificação antes de ser salvo."
            + (f"\n\n{summary}" if summary else "")
        )

class DuplicateTemplateFileError(ValueError):
    """Raised when an imported package reuses an existing template DOCX."""

    def __init__(self, matches: list[dict[str, Any]]) -> None:
        self.matches = matches
        names = ", ".join(
            str(match.get("name", match.get("id", 'Modelo desconhecido')))
            for match in matches
        )
        super().__init__(
            f"O DOCX de origem já é usado por: {names}"
        )


class SimilarTemplateNameError(ValueError):
    """Raised when a template name is too similar to an existing name."""

    def __init__(
        self,
        name: str,
        matches: list[dict[str, Any]],
    ) -> None:
        self.name = str(name)
        self.matches = matches
        names = ", ".join(
            str(match.get("name", match.get("id", 'Modelo desconhecido')))
            for match in matches
        )
        super().__init__(
            f'O nome do modelo "{self.name}" é semelhante a: {names}'
        )


class TemplateRepository:
    """CRUD, import/export, archive, and version history for DOCX templates."""

    def __init__(self, templates_dir: Path) -> None:
        self.templates_dir = Path(templates_dir)
        self.templates_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir = self.templates_dir / "_archive"
        self._last_discovery_issues: list[dict[str, str]] = []

    # Discovery ----------------------------------------------------------------
    def list_templates(self) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        issues: list[dict[str, str]] = []
        for folder in self.templates_dir.iterdir():
            if not folder.is_dir() or folder.name.startswith(("_", ".")):
                continue
            if not (folder / "template.json").exists():
                continue
            try:
                config = self._load_normalized_config(folder)
                template = config["template"]
                source_path = folder / str(template["source_file"])
                summaries.append(
                    {
                        "id": folder.name,
                        "name": str(template["name"]),
                        "category": str(template.get("category", "")),
                        "version": str(template.get("version", "1.0")),
                        "description": str(template.get("description", "")),
                        "folder": folder,
                        "source_path": source_path,
                    }
                )
            except Exception as exc:
                issues.append(
                    {
                        "template_id": folder.name,
                        "folder": str(folder),
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                    }
                )
                continue

        self._last_discovery_issues = issues
        summaries.sort(key=lambda item: (item["name"].casefold(), item["id"].casefold()))
        return summaries

    def list_discovery_issues(self) -> list[dict[str, str]]:
        """Return structured errors from the most recent active-template scan."""

        return deepcopy(self._last_discovery_issues)

    def list_archived_templates(self) -> list[dict[str, Any]]:
        if not self.archive_dir.exists():
            return []

        result: list[dict[str, Any]] = []
        for folder in self.archive_dir.iterdir():
            if not folder.is_dir() or not (folder / "template.json").exists():
                continue
            try:
                config = self._normalize_config(
                    self._read_json(folder / "template.json"),
                    canonical_id=folder.name,
                    folder=folder,
                )
                template = config["template"]
                result.append(
                    {
                        "archive_id": folder.name,
                        "name": str(template.get("name", folder.name)),
                        "category": str(template.get("category", "")),
                        "version": str(template.get("version", "1.0")),
                        "folder": folder,
                    }
                )
            except Exception:
                continue
        result.sort(key=lambda item: item["name"].casefold())
        return result

    def template_exists(self, template_id: str) -> bool:
        return self._template_folder(template_id).is_dir()

    @staticmethod
    def normalize_template_name(name: str) -> str:
        """Normalize a template name for accent/case/punctuation comparisons."""
        normalized = unicodedata.normalize(
            "NFKD",
            str(name or ""),
        )
        normalized = "".join(
            character
            for character in normalized
            if not unicodedata.combining(character)
        ).casefold()
        normalized = re.sub(
            r"[^a-z0-9]+",
            " ",
            normalized,
        )
        return " ".join(normalized.split())

    @classmethod
    def _template_name_key(cls, name: str) -> str:
        normalized = cls.normalize_template_name(name)
        if not normalized:
            return ""

        stop_words = {
            "a",
            "an",
            "and",
            "da",
            "das",
            "de",
            "do",
            "document",
            "documento",
            "dos",
            "e",
            "for",
            "form",
            "formulario",
            "modelo",
            "of",
            "o",
            "os",
            "para",
            "template",
            "the",
        }
        removable_suffixes = {
            "copy",
            "copia",
            "copias",
            "duplicate",
            "duplicado",
            "duplicada",
            "new",
            "novo",
            "nova",
        }

        tokens = [
            token
            for token in normalized.split()
            if token not in stop_words
        ]

        while tokens:
            last = tokens[-1]
            if (
                last in removable_suffixes
                or re.fullmatch(r"v?\d+", last)
            ):
                tokens.pop()
                continue
            if (
                len(tokens) >= 2
                and tokens[-2] in {
                    "version",
                    "versao",
                    "revision",
                    "revisao",
                    "rev",
                }
                and re.fullmatch(r"\d+", last)
            ):
                tokens = tokens[:-2]
                continue
            break

        return " ".join(tokens)

    @classmethod
    def template_name_similarity(
        cls,
        first: str,
        second: str,
    ) -> float:
        """Return a conservative similarity score between zero and one."""
        first_normalized = cls.normalize_template_name(first)
        second_normalized = cls.normalize_template_name(second)
        if not first_normalized or not second_normalized:
            return 0.0
        if first_normalized == second_normalized:
            return 1.0

        first_key = cls._template_name_key(first)
        second_key = cls._template_name_key(second)
        if not first_key or not second_key:
            return 0.0
        if first_key == second_key:
            return 0.99

        first_compact = first_key.replace(" ", "")
        second_compact = second_key.replace(" ", "")
        if first_compact == second_compact:
            return 0.98

        first_tokens = set(first_key.split())
        second_tokens = set(second_key.split())
        common = first_tokens & second_tokens
        union = first_tokens | second_tokens

        sequence_score = SequenceMatcher(
            None,
            first_key,
            second_key,
        ).ratio()
        compact_score = SequenceMatcher(
            None,
            first_compact,
            second_compact,
        ).ratio()
        token_score = (
            len(common) / len(union)
            if union
            else 0.0
        )
        containment_score = (
            len(common)
            / min(
                len(first_tokens),
                len(second_tokens),
            )
            if first_tokens and second_tokens
            else 0.0
        )

        # Prevent generic short names such as "Template A" and "Template B"
        # from being marked similar merely because most characters match.
        shortest_key = min(
            len(first_compact),
            len(second_compact),
        )
        if shortest_key < 5:
            return 0.0

        candidate_scores = [
            sequence_score,
            compact_score * 0.98,
            token_score,
        ]
        if (
            containment_score == 1.0
            and min(
                len(first_tokens),
                len(second_tokens),
            ) >= 2
        ):
            candidate_scores.append(0.91)

        score = max(candidate_scores)

        # A fuzzy character match must still share meaningful content.
        if not common:
            if sequence_score < 0.92:
                return 0.0
        elif (
            len(common) == 1
            and len(first_tokens) > 1
            and len(second_tokens) > 1
            and sequence_score < 0.86
            and token_score < 0.75
        ):
            return 0.0

        return round(score, 4)

    def find_templates_with_similar_name(
        self,
        name: str,
        *,
        exclude_template_id: str | None = None,
        threshold: float = 0.84,
    ) -> list[dict[str, Any]]:
        """Find active templates with an exact, normalized, or fuzzy name."""
        candidate_name = str(name or "").strip()
        if not candidate_name:
            return []

        matches: list[dict[str, Any]] = []
        for summary in self.list_templates():
            template_id = str(summary.get("id", ""))
            if (
                exclude_template_id
                and template_id == exclude_template_id
            ):
                continue

            score = self.template_name_similarity(
                candidate_name,
                str(summary.get("name", "")),
            )
            if score < threshold:
                continue

            match = dict(summary)
            match["similarity"] = score
            if score >= 0.999:
                match["similarity_reason"] = "mesmo nome normalizado"
            elif score >= 0.98:
                match["similarity_reason"] = "mesmo nome após normalização"
            else:
                match["similarity_reason"] = "redação ou grafia semelhante"
            matches.append(match)

        matches.sort(
            key=lambda item: (
                -float(item.get("similarity", 0.0)),
                str(item.get("name", "")).casefold(),
            )
        )
        return matches

    def _ensure_template_name_available(
        self,
        name: str,
        *,
        allow_similar_name: bool,
        exclude_template_id: str | None = None,
    ) -> None:
        similar_matches = self.find_templates_with_similar_name(
            name,
            exclude_template_id=exclude_template_id,
        )
        if similar_matches and not allow_similar_name:
            raise SimilarTemplateNameError(
                name,
                similar_matches,
            )

    def find_similar_name_groups(
        self,
        *,
        threshold: float = 0.84,
    ) -> list[list[dict[str, Any]]]:
        """Return connected groups of templates with similar names."""
        templates = [
            dict(summary)
            for summary in self.list_templates()
        ]
        if len(templates) < 2:
            return []

        adjacency: dict[int, set[int]] = {
            index: set()
            for index in range(len(templates))
        }

        for first_index in range(len(templates)):
            for second_index in range(
                first_index + 1,
                len(templates),
            ):
                score = self.template_name_similarity(
                    str(templates[first_index].get("name", "")),
                    str(templates[second_index].get("name", "")),
                )
                if score < threshold:
                    continue
                adjacency[first_index].add(second_index)
                adjacency[second_index].add(first_index)

        groups: list[list[dict[str, Any]]] = []
        visited: set[int] = set()
        for start in range(len(templates)):
            if start in visited or not adjacency[start]:
                continue

            stack = [start]
            component: list[int] = []
            while stack:
                current = stack.pop()
                if current in visited:
                    continue
                visited.add(current)
                component.append(current)
                stack.extend(adjacency[current] - visited)

            members = [
                templates[index]
                for index in component
            ]
            members.sort(
                key=lambda item: str(
                    item.get("name", "")
                ).casefold()
            )
            groups.append(members)

        groups.sort(
            key=lambda members: (
                -len(members),
                str(members[0].get("name", "")).casefold(),
            )
        )
        return groups

    def docx_fingerprint(self, source_docx: Path) -> str:
        """
        Return a stable fingerprint for the actual Word-document contents.

        DOCX package metadata such as modified dates is intentionally ignored.
        This allows the app to recognize the same template after it has been
        copied, renamed, exported, or imported again.
        """
        source_docx = Path(source_docx)
        self._validate_docx(source_docx)

        digest = hashlib.sha256()
        with zipfile.ZipFile(source_docx, "r") as archive:
            names = sorted(
                name
                for name in archive.namelist()
                if not name.endswith("/")
                and (
                    name.startswith("word/")
                    or name in {"[Content_Types].xml", "_rels/.rels"}
                )
            )

            if not names:
                raise ValueError(
                    'O DOCX selecionado não contém um documento do Word válido.'
                )

            for name in names:
                encoded_name = name.encode("utf-8")
                content = archive.read(name)
                digest.update(len(encoded_name).to_bytes(4, "big"))
                digest.update(encoded_name)
                digest.update(len(content).to_bytes(8, "big"))
                digest.update(content)

        return digest.hexdigest()

    def find_templates_using_docx(
        self,
        source_docx: Path,
        *,
        exclude_template_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Find active templates whose source DOCX has the same contents."""
        source_fingerprint = self.docx_fingerprint(source_docx)
        matches: list[dict[str, Any]] = []

        for summary in self.list_templates():
            template_id = str(summary.get("id", ""))
            if exclude_template_id and template_id == exclude_template_id:
                continue

            source_path = Path(summary["source_path"])
            try:
                fingerprint = self.docx_fingerprint(source_path)
            except (OSError, ValueError, zipfile.BadZipFile):
                continue

            if fingerprint == source_fingerprint:
                matches.append(dict(summary))

        return matches

    def find_duplicate_docx_groups(self) -> list[list[dict[str, Any]]]:
        """Return groups of active templates that share the same DOCX."""
        grouped: dict[str, list[dict[str, Any]]] = {}

        for summary in self.list_templates():
            try:
                fingerprint = self.docx_fingerprint(
                    Path(summary["source_path"])
                )
            except (OSError, ValueError, zipfile.BadZipFile):
                continue
            grouped.setdefault(fingerprint, []).append(
                dict(summary)
            )

        duplicates = [
            members
            for members in grouped.values()
            if len(members) > 1
        ]
        duplicates.sort(
            key=lambda members: (
                -len(members),
                str(members[0].get("name", "")).casefold(),
            )
        )
        return duplicates

    def read_config(self, template_id: str) -> dict[str, Any]:
        return self._load_normalized_config(self._require_template_folder(template_id))

    def get_source_path(self, template_id: str) -> Path:
        folder = self._require_template_folder(template_id)
        config = self._load_normalized_config(folder)
        source_path = folder / str(config["template"]["source_file"])
        if not source_path.exists():
            raise FileNotFoundError(f"DOCX do modelo não encontrado: {source_path}")
        return source_path

    # Create/update -------------------------------------------------------------
    # noinspection DuplicatedCode
    def create_template(
        self,
        *,
        name: str,
        source_docx: Path,
        fields: list[dict[str, Any]],
        description: str = "",
        category: str = "",
        version: str = "1.0",
        filename_pattern: str = "{{template.name}}.docx",
        sections: list[dict[str, Any]] | None = None,
        output_folder_pattern: str = "",
        numbering: dict[str, Any] | None = None,
        letterhead: dict[str, Any] | None = None,
        allow_similar_name: bool = False,
    ) -> str:
        name = str(name).strip()
        if not name:
            raise ValueError('O nome do modelo não pode ficar vazio.')

        self._ensure_template_name_available(
            name,
            allow_similar_name=allow_similar_name,
        )

        source_docx = Path(source_docx)
        self._validate_docx(source_docx)
        normalized_fields = self._normalize_fields(fields, strict=True)
        normalized_sections = self._normalize_sections(sections, normalized_fields)

        template_id = self._unique_template_id(self._slugify(name) or "template")
        final_folder = self._template_folder(template_id)
        temporary_folder = Path(
            tempfile.mkdtemp(prefix=f".{template_id}-", dir=self.templates_dir)
        )

        try:
            source_name = "template.docx"
            shutil.copy2(source_docx, temporary_folder / source_name)
            config = self._build_config(
                template_id=template_id, name=name, description=description,
                category=category, version=version, source_file=source_name,
                fields=normalized_fields, sections=normalized_sections,
                filename_pattern=filename_pattern,
                output_folder_pattern=output_folder_pattern, numbering=numbering,
                letterhead=letterhead,
            )
            self._assert_preflight(config, source_docx)
            self._atomic_write_json(temporary_folder / "template.json", config)
            os.replace(temporary_folder, final_folder)
        except Exception:
            shutil.rmtree(temporary_folder, ignore_errors=True)
            raise

        return template_id

    # noinspection DuplicatedCode
    def update_template(
        self,
        *,
        template_id: str,
        name: str,
        fields: list[dict[str, Any]],
        description: str = "",
        category: str = "",
        version: str = "1.0",
        filename_pattern: str = "{{template.name}}.docx",
        replacement_docx: Path | None = None,
        sections: list[dict[str, Any]] | None = None,
        output_folder_pattern: str = "",
        numbering: dict[str, Any] | None = None,
        letterhead: dict[str, Any] | None = None,
        allow_similar_name: bool = False,
    ) -> str:
        name = str(name).strip()
        if not name:
            raise ValueError('O nome do modelo não pode ficar vazio.')

        folder = self._require_template_folder(template_id)
        existing = self._load_normalized_config(folder)
        old_name = str(existing.get("template", {}).get("name", ""))
        if self.normalize_template_name(name) != self.normalize_template_name(old_name):
            self._ensure_template_name_available(
                name,
                allow_similar_name=allow_similar_name,
                exclude_template_id=template_id,
            )

        normalized_fields = self._normalize_fields(fields, strict=True)
        normalized_sections = self._normalize_sections(sections, normalized_fields)
        source_name = str(existing["template"].get("source_file", "template.docx"))
        target_source = folder / source_name

        effective_letterhead = (
            letterhead
            if letterhead is not None
            else existing.get("letterhead", {})
        )
        updated = self._build_config(
            template_id=template_id, name=name, description=description,
            category=category, version=version, source_file=source_name,
            fields=normalized_fields, sections=normalized_sections,
            filename_pattern=filename_pattern,
            output_folder_pattern=output_folder_pattern, numbering=numbering,
            letterhead=effective_letterhead,
        )

        # Preserve future-compatible top-level values not controlled by the editor.
        for key, value in existing.items():
            if key not in updated:
                updated[key] = deepcopy(value)

        replacement: Path | None = None
        if replacement_docx is not None:
            replacement = Path(replacement_docx)
            self._validate_docx(replacement)
            try:
                if replacement.resolve() == target_source.resolve():
                    replacement = None
            except OSError:
                pass

        # Stage the complete new state before touching the live template.  The
        # staged source deliberately keeps a .docx suffix because preflight and
        # the strict scanner validate the file type from its extension.
        with tempfile.TemporaryDirectory(
            prefix=".padroniza-template-update-",
            dir=str(folder),
        ) as temporary:
            stage_root = Path(temporary)
            staged_config = stage_root / "template.json"
            staged_source: Path | None = None
            if replacement is not None:
                staged_source = stage_root / "replacement.docx"
                shutil.copy2(replacement, staged_source)

            source_for_preflight = staged_source or target_source
            self._assert_preflight(updated, source_for_preflight)
            self._atomic_write_json(staged_config, updated)

            # Snapshot only after the incoming state is fully validated/staged.
            self._snapshot_version(folder, existing)
            changes: list[tuple[Path, Path]] = [(staged_config, folder / "template.json")]
            if staged_source is not None:
                # Replace the source first; if the config publication fails, the
                # transaction helper restores the previous source automatically.
                changes.insert(0, (staged_source, target_source))
            self._publish_files_transactionally(stage_root, changes)

        return template_id

    def duplicate_template(
        self,
        template_id: str,
        new_name: str | None = None,
        *,
        allow_similar_name: bool = False,
    ) -> str:
        source_folder = self._require_template_folder(template_id)
        source_config = self._load_normalized_config(source_folder)
        old_name = str(source_config["template"]["name"])
        duplicate_name = str(new_name).strip() if new_name is not None else f"{old_name} - Cópia"
        if not duplicate_name:
            raise ValueError('O nome da cópia não pode ficar vazio.')

        self._ensure_template_name_available(
            duplicate_name,
            allow_similar_name=allow_similar_name,
        )

        new_id = self._unique_template_id(self._slugify(duplicate_name) or f"{template_id}-copy")
        destination = self._template_folder(new_id)
        destination.mkdir(parents=True)

        try:
            source_filename = str(source_config["template"]["source_file"])
            shutil.copy2(source_folder / source_filename, destination / source_filename)
            duplicate_config = deepcopy(source_config)
            duplicate_config["template"]["id"] = new_id
            duplicate_config["template"]["name"] = duplicate_name
            self._atomic_write_json(destination / "template.json", duplicate_config)
        except Exception:
            shutil.rmtree(destination, ignore_errors=True)
            raise
        return new_id

    # Archive/delete ------------------------------------------------------------
    def archive_template(self, template_id: str) -> Path:
        source_folder = self._require_template_folder(template_id)
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        destination = self.archive_dir / f"{template_id}--{timestamp}"
        counter = 2
        while destination.exists():
            destination = self.archive_dir / f"{template_id}--{timestamp}-{counter}"
            counter += 1
        shutil.move(str(source_folder), str(destination))
        return destination

    def restore_archived_template(self, archive_id: str) -> str:
        source = self.archive_dir / Path(str(archive_id)).name
        if not source.is_dir():
            raise FileNotFoundError(f"Modelo arquivado não encontrado: {archive_id}")

        raw_config = self._read_json(source / "template.json")
        original_id = str(raw_config.get("template", {}).get("id", "")).strip()
        if not original_id or original_id.startswith(("_", ".")):
            original_id = str(archive_id).split("--", 1)[0]
        restored_id = self._unique_template_id(self._slugify(original_id) or "restored-template")
        destination = self._template_folder(restored_id)
        shutil.move(str(source), str(destination))

        config = self._load_normalized_config(destination)
        config["template"]["id"] = restored_id
        self._atomic_write_json(destination / "template.json", config)
        return restored_id

    def permanently_delete_template(self, template_id: str) -> None:
        folder = self._require_template_folder(template_id)
        shutil.rmtree(folder)
        if folder.exists():
            raise OSError(f"Não foi possível excluir a pasta do modelo: {folder}")

    # Import/export -------------------------------------------------------------
    def export_template_package(self, template_id: str, destination: Path) -> Path:
        folder = self._require_template_folder(template_id)
        config = self._load_normalized_config(folder)
        source = folder / str(config["template"]["source_file"])
        destination = Path(destination)
        if destination.suffix.lower() != ".zip":
            destination = destination.with_suffix(".padroniza-template.zip")
        destination.parent.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(folder / "template.json", "template.json")
            archive.write(source, source.name)
            preview = folder / "preview.png"
            if preview.exists():
                archive.write(preview, "preview.png")
        return destination

    def import_template_package(
        self,
        package_path: Path,
        *,
        allow_duplicate: bool = False,
        allow_similar_name: bool = False,
    ) -> str:
        package_path = Path(package_path)
        if not package_path.exists():
            raise FileNotFoundError(f"Pacote de modelo não encontrado: {package_path}")

        with tempfile.TemporaryDirectory(prefix="padroniza-import-") as temporary:
            temporary_root = Path(temporary)
            try:
                with zipfile.ZipFile(package_path, "r") as archive:
                    self._safe_extract(archive, temporary_root)
            except zipfile.BadZipFile as exc:
                raise ValueError('O arquivo selecionado não é um ZIP de modelo válido.') from exc

            config_path = temporary_root / "template.json"
            if not config_path.exists():
                # Accept a package with one top-level folder.
                matches = list(temporary_root.rglob("template.json"))
                if len(matches) != 1:
                    raise ValueError('O pacote deve conter template.json e um arquivo DOCX ou DOCM.')
                config_path = matches[0]
                temporary_root = config_path.parent

            raw = self._read_json(config_path)
            template = raw.get("template", {}) if isinstance(raw.get("template", {}), dict) else {}
            name = self._first_text(template.get("name"), raw.get("name"), package_path.stem)
            self._ensure_template_name_available(
                name,
                allow_similar_name=allow_similar_name,
            )

            requested_id = self._first_text(template.get("id"), self._slugify(name), "imported-template")
            template_id = self._unique_template_id(self._slugify(requested_id) or "imported-template")

            requested_source = self._first_text(
                template.get("source_file"),
                template.get("source_docx"),
                raw.get("source_file"),
                "template.docx",
            )
            source_candidate = temporary_root / Path(requested_source).name
            if not source_candidate.exists():
                word_files = [
                    candidate
                    for candidate in temporary_root.iterdir()
                    if candidate.is_file() and candidate.suffix.casefold() in WORD_INPUT_SUFFIXES
                ]
                if len(word_files) != 1:
                    raise ValueError(
                        'O pacote deve conter exatamente um arquivo DOCX ou DOCM de origem.'
                    )
                source_candidate = word_files[0]

            normalized_source = source_candidate
            if source_candidate.suffix.casefold() == '.docm':
                normalized_source = temporary_root / '.padroniza-import-normalized.docx'
                normalize_word_input(source_candidate, normalized_source)

            duplicate_matches = self.find_templates_using_docx(
                normalized_source
            )
            if duplicate_matches and not allow_duplicate:
                raise DuplicateTemplateFileError(
                    duplicate_matches
                )

            destination = self._template_folder(template_id)
            destination.mkdir(parents=True)
            try:
                shutil.copy2(normalized_source, destination / "template.docx")
                preview = temporary_root / "preview.png"
                if preview.exists():
                    shutil.copy2(preview, destination / "preview.png")

                normalized = self._normalize_config(raw, canonical_id=template_id, folder=destination)
                normalized["template"]["id"] = template_id
                normalized["template"]["source_file"] = "template.docx"
                self._assert_preflight(normalized, destination / "template.docx")
                self._atomic_write_json(destination / "template.json", normalized)
            except Exception:
                shutil.rmtree(destination, ignore_errors=True)
                raise

        return template_id

    # Version history -----------------------------------------------------------
    def list_versions(self, template_id: str) -> list[dict[str, Any]]:
        folder = self._require_template_folder(template_id)
        versions_dir = folder / "versions"
        if not versions_dir.exists():
            return []

        result: list[dict[str, Any]] = []
        for snapshot in versions_dir.iterdir():
            if not snapshot.is_dir() or not (snapshot / "template.json").exists():
                continue
            try:
                config = self._read_json(snapshot / "template.json")
                template = config.get("template", {})
                source_name = str(template.get("source_file", "template.docx"))
                result.append(
                    {
                        "snapshot": snapshot.name,
                        "version": str(template.get("version", "")),
                        "saved_at": str(config.get("_snapshot", {}).get("saved_at", snapshot.name)),
                        "has_docx": (snapshot / source_name).exists(),
                    }
                )
            except Exception:
                continue

        result.sort(key=lambda item: item["snapshot"], reverse=True)
        return result

    def restore_version(self, template_id: str, snapshot_name: str) -> None:
        folder = self._require_template_folder(template_id)
        snapshot = folder / "versions" / Path(snapshot_name).name
        if not snapshot.is_dir():
            raise FileNotFoundError(f"Cópia de versão do modelo não encontrada: {snapshot_name}")

        current = self._load_normalized_config(folder)
        snapshot_config = self._read_json(snapshot / "template.json")
        snapshot_config.pop("_snapshot", None)
        normalized = self._normalize_config(
            snapshot_config,
            canonical_id=template_id,
            folder=snapshot,
        )
        normalized["template"]["id"] = template_id
        source_name = str(normalized["template"]["source_file"])
        snapshot_docx = snapshot / source_name
        if not snapshot_docx.exists():
            raise FileNotFoundError(
                f"DOCX da versão selecionada não encontrado: {snapshot_docx}"
            )

        with tempfile.TemporaryDirectory(
            prefix=".padroniza-template-restore-",
            dir=str(folder),
        ) as temporary:
            stage_root = Path(temporary)
            staged_source = stage_root / "replacement.docx"
            staged_config = stage_root / "template.json"
            shutil.copy2(snapshot_docx, staged_source)
            self._assert_preflight(normalized, staged_source)
            self._atomic_write_json(staged_config, normalized)

            self._snapshot_version(folder, current)
            self._publish_files_transactionally(
                stage_root,
                [
                    (staged_source, folder / source_name),
                    (staged_config, folder / "template.json"),
                ],
            )

    def _snapshot_version(self, folder: Path, config: dict[str, Any]) -> None:
        versions_dir = folder / "versions"
        versions_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        snapshot = versions_dir / timestamp
        snapshot.mkdir()

        snapshot_config = deepcopy(config)
        snapshot_config["_snapshot"] = {
            "saved_at": datetime.now().replace(microsecond=0).isoformat()
        }
        self._atomic_write_json(snapshot / "template.json", snapshot_config)
        source_name = str(config["template"].get("source_file", "template.docx"))
        source = folder / source_name
        if source.exists():
            shutil.copy2(source, snapshot / source_name)

    # Normalization -------------------------------------------------------------
    def _load_normalized_config(self, folder: Path) -> dict[str, Any]:
        config_path = folder / "template.json"
        if not config_path.exists():
            raise FileNotFoundError(f"Configuração do modelo não encontrada: {config_path}")
        return self._normalize_config(
            self._read_json(config_path),
            canonical_id=folder.name,
            folder=folder,
        )

    def _normalize_config(
        self,
        raw_config: dict[str, Any],
        *,
        canonical_id: str,
        folder: Path,
    ) -> dict[str, Any]:
        try:
            schema_version = int(raw_config.get("schema_version", 0) or 0)
        except (TypeError, ValueError) as exc:
            raise SchemaVersionError("A versão do modelo é inválida.") from exc
        if schema_version > TEMPLATE_SCHEMA_VERSION:
            raise SchemaVersionError(
                f"Este modelo usa schema {schema_version}, mas esta versão do Padroniza "
                f"suporta até schema {TEMPLATE_SCHEMA_VERSION}."
            )

        template_raw = raw_config.get("template", {})
        template = dict(template_raw) if isinstance(template_raw, dict) else {}

        name = self._first_text(template.get("name"), raw_config.get("name"), canonical_id)
        description = self._first_text(template.get("description"), raw_config.get("description"), "")
        category = self._first_text(template.get("category"), raw_config.get("category"), "")
        version = self._first_text(template.get("version"), raw_config.get("version"), "1.0")
        requested_source = self._first_text(
            template.get("source_file"),
            template.get("source_docx"),
            template.get("docx"),
            raw_config.get("source_file"),
            raw_config.get("source_docx"),
            "template.docx",
        )
        source_file = self._resolve_source_filename(folder, requested_source)

        raw_fields = raw_config.get("fields", raw_config.get("form_fields", []))
        fields = self._normalize_fields(raw_fields, strict=False)
        sections = self._normalize_sections(raw_config.get("sections", []), fields)

        output_raw = raw_config.get("output", {})
        output = dict(output_raw) if isinstance(output_raw, dict) else {}
        filename_pattern = self._first_text(
            output.get("filename_pattern"),
            output.get("filename"),
            raw_config.get("filename_pattern"),
            raw_config.get("output_filename"),
            "{{template.name}}.docx",
        )
        folder_pattern = self._first_text(
            output.get("folder_pattern"),
            output.get("output_folder_pattern"),
            raw_config.get("output_folder_pattern"),
            "",
        )
        numbering = raw_config.get("numbering", {})
        if not isinstance(numbering, dict):
            numbering = {}
        letterhead = raw_config.get("letterhead", {})
        if not isinstance(letterhead, dict):
            letterhead = {}

        normalized = {
            "schema_version": TEMPLATE_SCHEMA_VERSION,
            "template": {
                "id": canonical_id,
                "name": name,
                "description": description,
                "category": category,
                "version": version,
                "source_file": source_file,
                "adapter": "docx",
            },
            "fields": fields,
            "sections": sections,
            "output": {
                "filename_pattern": filename_pattern,
                "folder_pattern": folder_pattern,
            },
            "numbering": {
                "enabled": self._as_bool(numbering.get("enabled", False)),
                "key": self._first_text(numbering.get("key"), canonical_id),
                "padding": int(numbering.get("padding", 4) or 4),
            },
            "letterhead": {
                "enabled": self._as_bool(letterhead.get("enabled", False)),
                "source": "bundled_default",
            },
        }

        for key, value in raw_config.items():
            if key not in normalized and key != "_snapshot":
                normalized[key] = deepcopy(value)

        self._validate_config(normalized, expected_template_id=canonical_id)
        return normalized

    def _normalize_fields(self, fields: Any, *, strict: bool) -> list[FieldDefinition]:
        if fields is None:
            fields = []
        if not isinstance(fields, list):
            if strict:
                raise ValueError('Os campos devem ser uma lista.')
            fields = []

        normalized: list[FieldDefinition] = []
        seen_ids: set[str] = set()
        preserved_keys = {
            "section",
            "profile_key",
            "group",
            "selection",
            "visible_when",
            "automatic",
            "placeholder",
            "default_value",
            "full_width",
            "height",
            "validation",
            "format",
            "minimum_rows",
            "numbering_padding",
            "marker",
            "validation_hint",
            "format_hint",
            "min",
            "max",
            "min_length",
            "max_length",
            "pattern",
            "pattern_message",
            "layout",
            "layout_group",
            "layout_group_label",
            "layout_row",
            "layout_row_label",
            "layout_column",
            "layout_column_index",
            "layout_column_span",
            "layout_grid_columns",
            "layout_presentation",
            "layout_static_rows",
            "layout_row_static_cells",
            "layout_position_locked",
            "layout_order",
            "choice_required",
            "tag_type",
            "label_source",
            "section_source",
            "type_source",
            "example",
            "detection_source",
            "detection_confidence",
            "detection_confidence_band",
            "detection_evidence",
            "detection_confidence_dimensions",
            "detection_type_inference",
            "detection_review_priority",
            "detection_review_reasons",
            "detection_needs_review",
            "detection_reviewed",
            "detector_version",
            "scanner_version",
            "detection_pipeline_version",
            "detection_selection_policy_version",
            "detection_auto_apply_eligible",
            "detection_document_fingerprint",
            "detection_location_signature",
            "detection_location",
            "choice_group_label",
            "compact_choice",
            "context_evidence",
            "context_confidence",
            "context_resolver_version",
            "id_source",
            "auto_tagged",
            "profile_identity",
            "context_needs_review",
            "context_review_reason",
            "dynamic_scope",
            "semantic_concept_id",
            "semantic_prediction",
            "semantic_model_version",
            "semantic_fillable_probability",
            "semantic_concept_confidence",
            "semantic_learned_similarity",
            "source_anchor",
            "source_context",
            "family_fingerprint",
            "list_style",
            "list_punctuation",
            "minimum_items",
            "maximum_items",
        }

        for index, raw_field in enumerate(fields, start=1):
            if isinstance(raw_field, str):
                raw_field = {"id": raw_field}
            if not isinstance(raw_field, dict):
                if strict:
                    raise ValueError(f"O campo {index} deve ser um objeto.")
                continue

            field_id = self._first_text(
                raw_field.get("id"), raw_field.get("field_id"), raw_field.get("name"), ""
            )
            if not field_id:
                if strict:
                    raise ValueError(f"O campo {index} não possui ID.")
                continue
            if field_id in seen_ids:
                if strict:
                    raise ValueError(f"ID de campo duplicado: {field_id}")
                continue

            label = self._first_text(
                raw_field.get("label"), raw_field.get("title"), self._create_label(field_id)
            )
            raw_type = self._first_text(
                raw_field.get("type"), raw_field.get("field_type"), "text"
            ).lower()
            aliased_type = FIELD_TYPE_ALIASES.get(raw_type, raw_type)
            field_type = infer_field_type(field_id, aliased_type)
            if field_type not in SUPPORTED_FIELD_TYPES:
                if strict:
                    raise ValueError(f"Tipo de campo '{field_type}' não compatível para '{field_id}'.")
                field_type = "text"

            required = False if field_type == "checkbox" else self._as_bool(raw_field.get("required", False))
            field: dict[str, Any] = {
                "id": field_id,
                "label": label,
                "type": field_type,
                "required": required,
            }

            if field_type == "dropdown":
                options = self._normalize_options(
                    raw_field.get("options", raw_field.get("choices", raw_field.get("items", [])))
                )
                if not options:
                    if strict:
                        raise ValueError(f"A lista suspensa '{field_id}' deve conter pelo menos uma opção.")
                    field_type = "text"
                    field["type"] = "text"
                else:
                    field["options"] = options

            if field_type == "repeatable_table":
                columns = normalize_repeatable_columns(
                    raw_field.get("columns", [])
                )
                if not columns:
                    if strict:
                        raise ValueError(
                            f"A tabela repetível '{field_id}' deve conter pelo menos uma coluna."
                        )
                    field_type = "text"
                    field["type"] = "text"
                else:
                    field["columns"] = columns
                    field["minimum_rows"] = max(
                        0,
                        int(raw_field.get("minimum_rows", 1) or 0),
                    )
                    field["numbering_padding"] = max(
                        1,
                        int(raw_field.get("numbering_padding", 2) or 2),
                    )

            if field_type == "repeatable_list":
                default_items = raw_field.get("default_value", raw_field.get("items", []))
                if default_items not in (None, "") and not isinstance(default_items, list):
                    if strict:
                        raise ValueError(
                            f"A lista repetível '{field_id}' deve possuir uma lista de valores padrão."
                        )
                    default_items = [str(default_items)]
                if isinstance(default_items, list):
                    field["default_value"] = [
                        str(item).strip() for item in default_items if str(item).strip()
                    ]
                try:
                    minimum_items = int(raw_field.get("minimum_items", 1) or 0)
                except (TypeError, ValueError):
                    if strict:
                        raise ValueError(
                            f"A quantidade mínima da lista repetível '{field_id}' é inválida."
                        )
                    minimum_items = 1
                field["minimum_items"] = max(0, minimum_items)
                maximum_items = raw_field.get("maximum_items")
                if maximum_items not in (None, ""):
                    try:
                        maximum_value = int(maximum_items)
                    except (TypeError, ValueError):
                        if strict:
                            raise ValueError(
                                f"A quantidade máxima da lista repetível '{field_id}' é inválida."
                            )
                        maximum_value = 0
                    if maximum_value > 0:
                        if strict and maximum_value < field["minimum_items"]:
                            raise ValueError(
                                f"A quantidade máxima da lista repetível '{field_id}' é menor que a mínima."
                            )
                        field["maximum_items"] = max(field["minimum_items"], maximum_value)
                list_style = str(raw_field.get("list_style", "bullet") or "bullet").casefold()
                if list_style not in REPEATABLE_LIST_STYLES:
                    if strict:
                        raise ValueError(
                            f"O estilo da lista repetível '{field_id}' não é compatível: {list_style}."
                        )
                    list_style = "bullet"
                punctuation = str(
                    raw_field.get("list_punctuation", "semicolon") or "semicolon"
                ).casefold()
                if punctuation not in REPEATABLE_LIST_PUNCTUATIONS:
                    if strict:
                        raise ValueError(
                            f"A pontuação da lista repetível '{field_id}' não é compatível: {punctuation}."
                        )
                    punctuation = "semicolon"
                field["list_style"] = list_style
                field["list_punctuation"] = punctuation

            for key in preserved_keys:
                if key in raw_field and raw_field[key] not in (None, "", [], {}):
                    field[key] = deepcopy(raw_field[key])

            dynamic_scope = str(field.get("dynamic_scope", "") or "").casefold()
            if dynamic_scope and dynamic_scope not in DYNAMIC_SCOPES:
                if strict:
                    raise ValueError(
                        f"O campo '{field_id}' possui escopo dinâmico inválido: {dynamic_scope}."
                    )
                field.pop("dynamic_scope", None)
                dynamic_scope = ""
            anchor_problems = source_anchor_errors(
                field.get("source_anchor"), expected_scope=dynamic_scope
            )
            if anchor_problems and strict:
                raise ValueError(
                    f"A âncora semântica do campo '{field_id}' é inválida: "
                    + "; ".join(anchor_problems)
                )

            if field_type == "date" and "automatic" not in field:
                field["automatic"] = True
            if field_type == "checkbox" and field.get("selection") in {"single", "exclusive", "radio"}:
                field["required"] = False

            seen_ids.add(field_id)
            normalized.append(FieldDefinition(field))

        return normalized

    def _normalize_sections(
        self,
        sections: Any,
        fields: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        field_ids = [str(field.get("id", "")) for field in fields if str(field.get("id", ""))]
        result: list[dict[str, Any]] = []
        assigned: set[str] = set()

        if isinstance(sections, list):
            for section in sections:
                if not isinstance(section, dict):
                    continue
                title = self._first_text(section.get("title"), section.get("name"), 'Informações')
                ids = [
                    str(value).strip()
                    for value in section.get("fields", [])
                    if str(value).strip() in field_ids and str(value).strip() not in assigned
                ]
                if ids:
                    result.append({"title": title, "fields": ids})
                    assigned.update(ids)

        # Section metadata on fields is also accepted and is easier to edit.
        section_map: dict[str, list[str]] = {}
        section_order: list[str] = []
        for field in fields:
            field_id = str(field.get("id", ""))
            if field_id in assigned:
                continue
            title = str(field.get("section", "")).strip()
            if not title:
                continue
            if title not in section_map:
                section_map[title] = []
                section_order.append(title)
            section_map[title].append(field_id)
            assigned.add(field_id)
        result.extend({"title": title, "fields": section_map[title]} for title in section_order)

        remaining = [field_id for field_id in field_ids if field_id not in assigned]
        if remaining:
            result.append({"title": 'Dados do documento', "fields": remaining})
        return result

    @staticmethod
    def _normalize_options(
        value: Any,
    ) -> list[str | dict[str, str]]:
        return compact_dropdown_options(value)

    def _build_config(
        self,
        *,
        template_id: str,
        name: str,
        description: str,
        category: str,
        version: str,
        source_file: str,
        fields: list[dict[str, Any]],
        sections: list[dict[str, Any]],
        filename_pattern: str,
        output_folder_pattern: str,
        numbering: dict[str, Any] | None,
        letterhead: dict[str, Any] | None,
    ) -> dict[str, Any]:
        numbering = numbering or {}
        letterhead = letterhead or {}
        config = {
            "schema_version": TEMPLATE_SCHEMA_VERSION,
            "template": {
                "id": template_id,
                "name": name,
                "description": str(description).strip(),
                "category": str(category).strip(),
                "version": str(version).strip() or "1.0",
                "source_file": source_file,
                "adapter": "docx",
            },
            "fields": fields,
            "sections": sections,
            "output": {
                "filename_pattern": str(filename_pattern).strip() or "{{template.name}}.docx",
                "folder_pattern": str(output_folder_pattern).strip(),
            },
            "numbering": {
                "enabled": self._as_bool(numbering.get("enabled", False)),
                "key": self._first_text(numbering.get("key"), template_id),
                "padding": max(1, min(10, int(numbering.get("padding", 4) or 4))),
            },
            "letterhead": {
                "enabled": self._as_bool(letterhead.get("enabled", False)),
                "source": "bundled_default",
            },
        }
        self._validate_config(config, expected_template_id=template_id)
        return config

    def _validate_config(self, config: dict[str, Any], *, expected_template_id: str) -> None:
        if not isinstance(config, dict):
            raise ValueError('A configuração do modelo deve ser um objeto.')
        template = config.get("template")
        if not isinstance(template, dict):
            raise ValueError("A configuração não contém o objeto 'template'.")
        if str(template.get("id", "")) != expected_template_id:
            raise ValueError('O ID do modelo não corresponde à pasta.')
        for key in ("name", "source_file", "adapter"):
            if not str(template.get(key, "")).strip():
                raise ValueError(f"A propriedade do modelo '{key}' não pode ficar vazia.")
        if template.get("adapter") != "docx":
            raise ValueError('Somente modelos DOCX são compatíveis.')
        self._normalize_fields(config.get("fields", []), strict=True)

    @staticmethod
    def _assert_preflight(config: dict[str, Any], source_path: Path) -> None:
        report = diagnose_template(config, source_path)
        if report.get("blocking"):
            raise TemplatePreflightError(report)

    # Helpers ------------------------------------------------------------------
    def _resolve_source_filename(self, folder: Path, requested_source: str) -> str:
        requested_path = Path(requested_source)
        for candidate in (folder / requested_path.name, folder / "template.docx"):
            if candidate.exists() and candidate.is_file() and candidate.suffix.lower() == ".docx":
                return candidate.name
        docx_files = sorted(folder.glob("*.docx"), key=lambda path: path.name.casefold())
        return docx_files[0].name if docx_files else requested_path.name or "template.docx"

    def _validate_docx(self, path: Path) -> None:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Arquivo DOCX não encontrado: {path}")
        if not path.is_file() or path.suffix.lower() != ".docx":
            raise ValueError('O arquivo selecionado deve ser um DOCX.')
        if path.stat().st_size == 0:
            raise ValueError('O arquivo DOCX selecionado está vazio.')

    def _template_folder(self, template_id: str) -> Path:
        template_id = str(template_id).strip()
        if not template_id or Path(template_id).name != template_id or template_id.startswith((".", "_")):
            raise ValueError('ID de modelo inválido.')
        return self.templates_dir / template_id

    def _require_template_folder(self, template_id: str) -> Path:
        folder = self._template_folder(template_id)
        if not folder.is_dir():
            raise FileNotFoundError(f"Modelo não encontrado: {template_id}")
        return folder

    def _unique_template_id(self, base_id: str) -> str:
        candidate = base_id
        counter = 2
        while self.template_exists(candidate):
            candidate = f"{base_id}-{counter}"
            counter += 1
        return candidate

    @staticmethod
    def _slugify(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value)
        ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
        return re.sub(r"[^a-zA-Z0-9]+", "-", ascii_value).strip("-").lower()

    @staticmethod
    def _create_label(field_id: str) -> str:
        return field_id.replace(".", " ").replace("_", " ").replace("-", " ").title()

    @staticmethod
    def _first_text(*values: Any) -> str:
        for value in values:
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return ""

    @staticmethod
    def _as_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        return str(value).strip().casefold() in {"1", "true", "yes", "sim", "required", "checked"}

    @staticmethod
    def _publish_files_transactionally(
        stage_root: Path,
        changes: list[tuple[Path, Path]],
    ) -> None:
        """Publish a group of staged files with rollback on any replacement error."""

        activated: list[tuple[Path, Path | None]] = []
        try:
            for index, (staged, destination) in enumerate(changes):
                if not staged.is_file():
                    raise FileNotFoundError(f"Arquivo preparado não encontrado: {staged}")
                destination.parent.mkdir(parents=True, exist_ok=True)
                previous = stage_root / f"previous-{index}-{destination.name}"
                had_previous = destination.exists()
                if had_previous:
                    os.replace(destination, previous)
                try:
                    os.replace(staged, destination)
                except Exception:
                    if had_previous and previous.exists() and not destination.exists():
                        os.replace(previous, destination)
                    raise
                activated.append((destination, previous if had_previous else None))
        except Exception:
            for destination, previous in reversed(activated):
                try:
                    destination.unlink(missing_ok=True)
                    if previous is not None and previous.exists():
                        os.replace(previous, destination)
                except OSError:
                    # Preserve the original failure. The version snapshot remains
                    # available for manual recovery even if the filesystem itself
                    # refuses a rollback operation.
                    pass
            raise

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        with path.open("r", encoding="utf-8-sig") as handle:
            value = json.load(handle)
        if not isinstance(value, dict):
            raise ValueError(f"{path}: era esperado um objeto JSON.")
        return value

    @staticmethod
    def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
        atomic_write_json(path, value)

    @staticmethod
    def _safe_extract(archive: zipfile.ZipFile, destination: Path) -> None:
        members = [item for item in archive.infolist() if not item.is_dir()]
        if len(members) > MAX_TEMPLATE_PACKAGE_FILES:
            raise ValueError('O pacote do modelo contém arquivos demais para ser importado com segurança.')
        total_size = sum(max(0, int(item.file_size)) for item in members)
        if total_size > MAX_TEMPLATE_PACKAGE_UNCOMPRESSED_BYTES:
            raise ValueError('O pacote do modelo é grande demais para ser importado com segurança.')
        oversized = next(
            (item for item in members if int(item.file_size) > MAX_TEMPLATE_PACKAGE_MEMBER_BYTES),
            None,
        )
        if oversized is not None:
            raise ValueError(
                f"O arquivo '{oversized.filename}' dentro do pacote é grande demais."
            )

        destination = destination.resolve()
        for member in archive.infolist():
            target = (destination / member.filename).resolve()
            try:
                target.relative_to(destination)
            except ValueError as exc:
                raise ValueError('O ZIP do modelo contém um caminho inseguro.') from exc
        archive.extractall(destination)
