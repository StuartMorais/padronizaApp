from __future__ import annotations

import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET


WORD_INPUT_SUFFIXES = frozenset({".docx", ".docm"})
DOCX_MAIN_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
)
DOCM_MAIN_CONTENT_TYPES = frozenset(
    {
        "application/vnd.ms-word.document.macroEnabled.main+xml",
        "application/vnd.ms-word.document.macroEnabledTemplate.main+xml",
    }
)

_CONTENT_TYPES_NAMESPACE = "http://schemas.openxmlformats.org/package/2006/content-types"
_RELATIONSHIPS_NAMESPACE = "http://schemas.openxmlformats.org/package/2006/relationships"
_MACRO_RELATIONSHIP_MARKERS = (
    "/vbaProject",
    "/vbaData",
)
_MACRO_PART_MARKERS = (
    "vbaproject",
    "vbadata",
)
MAX_WORD_PACKAGE_MEMBERS = 5000
MAX_WORD_PACKAGE_MEMBER_BYTES = 150 * 1024 * 1024
MAX_WORD_PACKAGE_UNCOMPRESSED_BYTES = 300 * 1024 * 1024


class WordPackageError(RuntimeError):
    """Raised when a DOCX/DOCM package cannot be safely prepared."""


@dataclass(frozen=True)
class NormalizedWordPackage:
    source: Path
    path: Path
    macros_removed: bool
    copied: bool


def is_word_input(path: Path | str) -> bool:
    return Path(path).suffix.casefold() in WORD_INPUT_SUFFIXES


def normalize_word_input(
    source: Path | str,
    destination: Path | str,
) -> NormalizedWordPackage:
    """Create a canonical DOCX copy from a DOCX or DOCM source.

    DOCM files are ZIP-based OOXML packages just like DOCX, but their main
    document content type is macro-enabled and they can carry VBA project
    parts.  Padroniza never needs to execute VBA to discover or fill document
    fields, so macro-enabled input is normalized into an inert DOCX working
    copy before python-docx, Word automation, or LibreOffice can open it.

    The original file is never modified. Normal Word content (document XML,
    tables, styles, images, headers/footers, content controls, etc.) is kept.
    VBA project/data/signature parts and their relationships are removed.
    """

    source_path = Path(source).expanduser().resolve()
    destination_path = Path(destination).expanduser().resolve()

    if not source_path.exists() or not source_path.is_file():
        raise WordPackageError(f"Arquivo do Word não encontrado: {source_path}")
    if source_path.suffix.casefold() not in WORD_INPUT_SUFFIXES:
        raise WordPackageError("Selecione um arquivo DOCX ou DOCM.")
    if source_path.stat().st_size <= 0:
        raise WordPackageError("O arquivo do Word selecionado está vazio.")
    if destination_path.suffix.casefold() != ".docx":
        raise WordPackageError("A cópia de trabalho deve usar a extensão .docx.")

    destination_path.parent.mkdir(parents=True, exist_ok=True)

    if source_path.suffix.casefold() == ".docx":
        if source_path != destination_path:
            shutil.copy2(source_path, destination_path)
        _validate_word_zip(destination_path)
        return NormalizedWordPackage(
            source=source_path,
            path=destination_path,
            macros_removed=False,
            copied=source_path != destination_path,
        )

    try:
        _normalize_docm_archive(source_path, destination_path)
        _validate_word_zip(destination_path)
    except WordPackageError:
        destination_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        destination_path.unlink(missing_ok=True)
        raise WordPackageError(f"Não foi possível preparar o DOCM com segurança: {exc}") from exc

    return NormalizedWordPackage(
        source=source_path,
        path=destination_path,
        macros_removed=True,
        copied=True,
    )


def _normalize_docm_archive(source: Path, destination: Path) -> None:
    try:
        archive = zipfile.ZipFile(source, "r")
    except zipfile.BadZipFile as exc:
        raise WordPackageError("O arquivo DOCM não é um pacote Word válido.") from exc

    with archive:
        _validate_archive_limits(archive)
        names = set(archive.namelist())
        if "[Content_Types].xml" not in names or "word/document.xml" not in names:
            raise WordPackageError("O arquivo DOCM não contém a estrutura principal do Word.")

        content_types = _normalize_content_types(archive.read("[Content_Types].xml"))

        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.stem}-",
            suffix=".docx",
            dir=str(destination.parent),
        )
        import os

        os.close(fd)
        Path(temporary_name).unlink(missing_ok=True)

        try:
            with zipfile.ZipFile(
                temporary_name,
                "w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=6,
            ) as output:
                for info in archive.infolist():
                    name = info.filename
                    if _is_macro_part(name):
                        continue

                    if name == "[Content_Types].xml":
                        data = content_types
                    elif name.endswith(".rels"):
                        data = _remove_macro_relationships(archive.read(name))
                    else:
                        data = archive.read(name)

                    copied_info = zipfile.ZipInfo(filename=name, date_time=info.date_time)
                    copied_info.compress_type = zipfile.ZIP_DEFLATED
                    copied_info.external_attr = info.external_attr
                    copied_info.comment = info.comment
                    copied_info.create_system = info.create_system
                    output.writestr(copied_info, data)

            Path(temporary_name).replace(destination)
        except Exception:
            Path(temporary_name).unlink(missing_ok=True)
            raise
        finally:
            Path(temporary_name).unlink(missing_ok=True)


def _normalize_content_types(data: bytes) -> bytes:
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise WordPackageError("[Content_Types].xml do DOCM é inválido.") from exc

    changed_main_type = False
    for child in list(root):
        part_name = str(child.attrib.get("PartName", ""))
        content_type = str(child.attrib.get("ContentType", ""))
        marker = (part_name + " " + content_type).casefold()

        if any(item in marker for item in _MACRO_PART_MARKERS):
            root.remove(child)
            continue

        if part_name == "/word/document.xml" and content_type in DOCM_MAIN_CONTENT_TYPES:
            child.set("ContentType", DOCX_MAIN_CONTENT_TYPE)
            changed_main_type = True

    # Some producers use a macro-enabled content type variant that is not in
    # the small known set above. Normalizing any macroEnabled main document
    # value keeps the conversion robust while still requiring document.xml.
    if not changed_main_type:
        for child in root:
            if str(child.attrib.get("PartName", "")) != "/word/document.xml":
                continue
            content_type = str(child.attrib.get("ContentType", ""))
            if "macroenabled" in content_type.casefold():
                child.set("ContentType", DOCX_MAIN_CONTENT_TYPE)
                changed_main_type = True
                break

    ET.register_namespace("", _CONTENT_TYPES_NAMESPACE)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _remove_macro_relationships(data: bytes) -> bytes:
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        # Preserve unrelated malformed relationship XML exactly as-is. The
        # downstream Word/package validator will surface a useful error later.
        return data

    changed = False
    for child in list(root):
        relationship_type = str(child.attrib.get("Type", ""))
        target = str(child.attrib.get("Target", ""))
        marker = f"{relationship_type} {target}".casefold()
        if any(item.casefold() in marker for item in _MACRO_RELATIONSHIP_MARKERS) or any(
            item in marker for item in _MACRO_PART_MARKERS
        ):
            root.remove(child)
            changed = True

    if not changed:
        return data

    ET.register_namespace("", _RELATIONSHIPS_NAMESPACE)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _is_macro_part(name: str) -> bool:
    normalized = name.replace("\\", "/").casefold()
    return any(marker in normalized for marker in _MACRO_PART_MARKERS)


def _validate_archive_limits(archive: zipfile.ZipFile) -> None:
    members = archive.infolist()
    if len(members) > MAX_WORD_PACKAGE_MEMBERS:
        raise WordPackageError(
            f"O pacote Word contém arquivos demais ({len(members)}; limite {MAX_WORD_PACKAGE_MEMBERS})."
        )

    total = 0
    for info in members:
        size = max(0, int(info.file_size))
        if size > MAX_WORD_PACKAGE_MEMBER_BYTES:
            raise WordPackageError(
                f"O componente '{info.filename}' excede o limite seguro de tamanho."
            )
        total += size
        if total > MAX_WORD_PACKAGE_UNCOMPRESSED_BYTES:
            raise WordPackageError("O documento Word excede o limite seguro de tamanho descompactado.")


def _validate_word_zip(path: Path) -> None:
    try:
        with zipfile.ZipFile(path, "r") as archive:
            _validate_archive_limits(archive)
            names = set(archive.namelist())
            if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                raise WordPackageError("O arquivo não contém um documento Word válido.")
            bad_member = archive.testzip()
            if bad_member:
                raise WordPackageError(f"O pacote Word está corrompido em: {bad_member}")
    except zipfile.BadZipFile as exc:
        raise WordPackageError("O arquivo selecionado não é um pacote DOCX/DOCM válido.") from exc


__all__ = [
    "DOCM_MAIN_CONTENT_TYPES",
    "DOCX_MAIN_CONTENT_TYPE",
    "MAX_WORD_PACKAGE_MEMBER_BYTES",
    "MAX_WORD_PACKAGE_MEMBERS",
    "MAX_WORD_PACKAGE_UNCOMPRESSED_BYTES",
    "NormalizedWordPackage",
    "WORD_INPUT_SUFFIXES",
    "WordPackageError",
    "is_word_input",
    "normalize_word_input",
]
