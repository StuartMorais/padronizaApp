from __future__ import annotations

import os
import tempfile
import zipfile
from copy import deepcopy
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree as ET

from app.core.paths import resolve_application_paths


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
HEADER_REL_TYPE = f"{R_NS}/header"
FOOTER_REL_TYPE = f"{R_NS}/footer"

DEFAULT_LETTERHEAD_ASSET = "Timbrado.docx"
_HEADER_PART = "word/padronizaLetterheadHeader.xml"
_FOOTER_PART = "word/padronizaLetterheadFooter.xml"
_HEADER_RELS_PART = "word/_rels/padronizaLetterheadHeader.xml.rels"
_MEDIA_PREFIX = "word/media/padroniza-letterhead-"


class LetterheadError(RuntimeError):
    """Raised when an official letterhead cannot be applied safely."""


def default_letterhead_path() -> Path:
    """Return the bundled official letterhead source."""

    return resolve_application_paths().resource_root / "assets" / DEFAULT_LETTERHEAD_ASSET


def letterhead_enabled(config: dict) -> bool:
    value = config.get("letterhead", {}) if isinstance(config, dict) else {}
    return bool(value.get("enabled", False)) if isinstance(value, dict) else False


def apply_letterhead(
    docx_path: Path,
    *,
    letterhead_path: Path | None = None,
) -> Path:
    """Replace every section header/footer with the bundled official letterhead.

    Body XML, fields, section page sizes and margins are left untouched. Header
    and footer references are attached to every section so the artwork repeats
    on every page. Existing source headers/footers remain in the package only as
    orphaned parts; they are no longer referenced by the document.
    """

    destination = Path(docx_path).expanduser().resolve()
    source = Path(letterhead_path or default_letterhead_path()).expanduser().resolve()
    if destination.suffix.lower() != ".docx":
        raise LetterheadError("O papel timbrado só pode ser aplicado a um arquivo DOCX.")
    if not destination.is_file():
        raise LetterheadError(f"DOCX de destino não encontrado: {destination}")
    if not source.is_file():
        raise LetterheadError(f"Papel timbrado não encontrado: {source}")

    try:
        with zipfile.ZipFile(source, "r") as letter_zip:
            source_names = set(letter_zip.namelist())
            required = {"word/header1.xml", "word/footer1.xml", "[Content_Types].xml"}
            missing = required - source_names
            if missing:
                raise LetterheadError(
                    "O arquivo de papel timbrado não contém cabeçalho/rodapé válidos: "
                    + ", ".join(sorted(missing))
                )
            header_xml = letter_zip.read("word/header1.xml")
            footer_xml = letter_zip.read("word/footer1.xml")
            source_content_types = ET.fromstring(letter_zip.read("[Content_Types].xml"))
            header_rels_xml, copied_media = _prepare_header_relationships(letter_zip)

        with zipfile.ZipFile(destination, "r") as target_zip:
            target_names = set(target_zip.namelist())
            if "word/document.xml" not in target_names or "word/_rels/document.xml.rels" not in target_names:
                raise LetterheadError("O DOCX de destino não possui a estrutura principal esperada.")
            document_root = ET.fromstring(target_zip.read("word/document.xml"))
            rels_root = ET.fromstring(target_zip.read("word/_rels/document.xml.rels"))
            content_types_root = ET.fromstring(target_zip.read("[Content_Types].xml"))

            header_rid, footer_rid = _attach_document_relationships(rels_root)
            _attach_letterhead_to_sections(document_root, header_rid, footer_rid)
            _merge_content_types(content_types_root, source_content_types, copied_media)

            replacements: dict[str, bytes] = {
                "word/document.xml": _xml_bytes(document_root),
                "word/_rels/document.xml.rels": _xml_bytes(rels_root),
                "[Content_Types].xml": _xml_bytes(content_types_root),
                _HEADER_PART: header_xml,
                _FOOTER_PART: footer_xml,
            }
            if header_rels_xml is not None:
                replacements[_HEADER_RELS_PART] = header_rels_xml
            replacements.update(copied_media)

            with tempfile.NamedTemporaryFile(
                prefix=f".{destination.stem}-letterhead-",
                suffix=".docx",
                dir=str(destination.parent),
                delete=False,
            ) as handle:
                temporary = Path(handle.name)

            try:
                with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as output_zip:
                    for info in target_zip.infolist():
                        name = info.filename
                        if name in replacements:
                            continue
                        if name.startswith(_MEDIA_PREFIX):
                            continue
                        if name == _HEADER_RELS_PART and header_rels_xml is None:
                            continue
                        output_zip.writestr(info, target_zip.read(name))
                    for name, payload in replacements.items():
                        output_zip.writestr(name, payload)

                with zipfile.ZipFile(temporary, "r") as check_zip:
                    broken = check_zip.testzip()
                    if broken:
                        raise LetterheadError(f"O DOCX timbrado ficou corrompido na entrada {broken}.")
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)
    except LetterheadError:
        raise
    except (OSError, zipfile.BadZipFile, ET.ParseError, KeyError) as exc:
        raise LetterheadError(f"Não foi possível aplicar o papel timbrado: {exc}") from exc

    return destination


def _prepare_header_relationships(
    letter_zip: zipfile.ZipFile,
) -> tuple[bytes | None, dict[str, bytes]]:
    rels_name = "word/_rels/header1.xml.rels"
    if rels_name not in letter_zip.namelist():
        return None, {}

    root = ET.fromstring(letter_zip.read(rels_name))
    copied: dict[str, bytes] = {}
    for relation in list(root):
        if relation.get("TargetMode", "").casefold() == "external":
            continue
        target = relation.get("Target", "").strip()
        if not target:
            continue
        source_part = _resolve_part("word/header1.xml", target)
        if source_part not in letter_zip.namelist():
            raise LetterheadError(f"Recurso do cabeçalho não encontrado: {source_part}")
        suffix = PurePosixPath(source_part).suffix
        stem = PurePosixPath(source_part).stem
        new_part = f"{_MEDIA_PREFIX}{stem}{suffix}"
        copied[new_part] = letter_zip.read(source_part)
        relation.set("Target", f"media/{PurePosixPath(new_part).name}")
    return _xml_bytes(root), copied


def _resolve_part(owner_part: str, target: str) -> str:
    owner_dir = PurePosixPath(owner_part).parent
    combined = owner_dir / target
    parts: list[str] = []
    for item in combined.parts:
        if item == "..":
            if parts:
                parts.pop()
        elif item not in {".", ""}:
            parts.append(item)
    return "/".join(parts)


def _attach_document_relationships(root: ET.Element) -> tuple[str, str]:
    relation_tag = f"{{{REL_NS}}}Relationship"
    for child in list(root):
        if child.get("Target") in {
            PurePosixPath(_HEADER_PART).name,
            PurePosixPath(_FOOTER_PART).name,
        }:
            root.remove(child)

    used = {child.get("Id", "") for child in root.findall(relation_tag)}
    header_rid = _next_relationship_id(used)
    used.add(header_rid)
    footer_rid = _next_relationship_id(used)
    ET.SubElement(
        root,
        relation_tag,
        {"Id": header_rid, "Type": HEADER_REL_TYPE, "Target": PurePosixPath(_HEADER_PART).name},
    )
    ET.SubElement(
        root,
        relation_tag,
        {"Id": footer_rid, "Type": FOOTER_REL_TYPE, "Target": PurePosixPath(_FOOTER_PART).name},
    )
    return header_rid, footer_rid


def _next_relationship_id(used: set[str]) -> str:
    index = 1
    while f"rId{index}" in used:
        index += 1
    return f"rId{index}"


def _attach_letterhead_to_sections(
    document_root: ET.Element,
    header_rid: str,
    footer_rid: str,
) -> None:
    section_tag = f"{{{W_NS}}}sectPr"
    header_tag = f"{{{W_NS}}}headerReference"
    footer_tag = f"{{{W_NS}}}footerReference"
    title_page_tag = f"{{{W_NS}}}titlePg"
    sections = list(document_root.iter(section_tag))
    if not sections:
        raise LetterheadError("O documento não possui nenhuma seção do Word.")

    for section in sections:
        for child in list(section):
            if child.tag in {header_tag, footer_tag, title_page_tag}:
                section.remove(child)

        references: list[ET.Element] = []
        for reference_type in ("default", "even", "first"):
            references.append(
                ET.Element(
                    header_tag,
                    {f"{{{W_NS}}}type": reference_type, f"{{{R_NS}}}id": header_rid},
                )
            )
        for reference_type in ("default", "even", "first"):
            references.append(
                ET.Element(
                    footer_tag,
                    {f"{{{W_NS}}}type": reference_type, f"{{{R_NS}}}id": footer_rid},
                )
            )
        for offset, reference in enumerate(references):
            section.insert(offset, reference)


def _merge_content_types(
    target_root: ET.Element,
    source_root: ET.Element,
    copied_media: dict[str, bytes],
) -> None:
    default_tag = f"{{{CT_NS}}}Default"
    override_tag = f"{{{CT_NS}}}Override"

    target_defaults = {
        child.get("Extension", "").casefold(): child
        for child in target_root.findall(default_tag)
    }
    source_defaults = {
        child.get("Extension", "").casefold(): child
        for child in source_root.findall(default_tag)
    }
    for name in copied_media:
        extension = PurePosixPath(name).suffix.lstrip(".").casefold()
        if extension and extension not in target_defaults and extension in source_defaults:
            target_root.append(deepcopy(source_defaults[extension]))
            target_defaults[extension] = source_defaults[extension]

    for child in list(target_root.findall(override_tag)):
        if child.get("PartName") in {f"/{_HEADER_PART}", f"/{_FOOTER_PART}"}:
            target_root.remove(child)

    ET.SubElement(
        target_root,
        override_tag,
        {
            "PartName": f"/{_HEADER_PART}",
            "ContentType": "application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml",
        },
    )
    ET.SubElement(
        target_root,
        override_tag,
        {
            "PartName": f"/{_FOOTER_PART}",
            "ContentType": "application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml",
        },
    )


def _xml_bytes(root: ET.Element) -> bytes:
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)
