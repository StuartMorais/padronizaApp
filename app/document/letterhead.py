from __future__ import annotations

import os
import tempfile
import zipfile
from copy import deepcopy
from pathlib import Path, PurePosixPath
from lxml import etree as ET

from app.core.paths import resolve_application_paths


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
HEADER_REL_TYPE = f"{R_NS}/header"
FOOTER_REL_TYPE = f"{R_NS}/footer"

DEFAULT_LETTERHEAD_ASSET = "Timbrado.docx"
_MEDIA_PREFIX = "word/media/padroniza-letterhead-"
_LEGACY_HEADER_PART = "word/padronizaLetterheadHeader.xml"
_LEGACY_FOOTER_PART = "word/padronizaLetterheadFooter.xml"
_LEGACY_HEADER_RELS_PART = "word/_rels/padronizaLetterheadHeader.xml.rels"
_LEGACY_FOOTER_RELS_PART = "word/_rels/padronizaLetterheadFooter.xml.rels"
_LEGACY_PARTS = {
    _LEGACY_HEADER_PART,
    _LEGACY_FOOTER_PART,
    _LEGACY_HEADER_RELS_PART,
    _LEGACY_FOOTER_RELS_PART,
}


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

    Body XML, fields, section page sizes and margins are left untouched. Word
    header/footer parts are created with Word's conventional ``headerN.xml`` /
    ``footerN.xml`` names. Older Padroniza builds used custom part names such as
    ``padronizaLetterheadFooter.xml``; Microsoft Word can reject those packages,
    so legacy parts are removed whenever the letterhead is applied again.
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
            header_rels_xml, header_media = _prepare_part_relationships(
                letter_zip, "word/header1.xml", media_scope="header"
            )
            footer_rels_xml, footer_media = _prepare_part_relationships(
                letter_zip, "word/footer1.xml", media_scope="footer"
            )
            copied_media = {**header_media, **footer_media}

        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix=f".{destination.stem}-letterhead-",
                suffix=".docx",
                dir=str(destination.parent),
                delete=False,
            ) as handle:
                temporary = Path(handle.name)

            with zipfile.ZipFile(destination, "r") as target_zip:
                target_names = set(target_zip.namelist())
                if (
                    "word/document.xml" not in target_names
                    or "word/_rels/document.xml.rels" not in target_names
                ):
                    raise LetterheadError(
                        "O DOCX de destino não possui a estrutura principal esperada."
                    )

                header_part, footer_part = _allocate_standard_part_names(target_names)
                header_rels_part = _rels_part_name(header_part)
                footer_rels_part = _rels_part_name(footer_part)

                document_root = ET.fromstring(target_zip.read("word/document.xml"))
                rels_root = ET.fromstring(target_zip.read("word/_rels/document.xml.rels"))
                content_types_root = ET.fromstring(target_zip.read("[Content_Types].xml"))

                header_rid, footer_rid = _attach_document_relationships(
                    rels_root, header_part=header_part, footer_part=footer_part
                )
                _attach_letterhead_to_sections(document_root, header_rid, footer_rid)
                _merge_content_types(
                    content_types_root,
                    source_content_types,
                    copied_media,
                    header_part=header_part,
                    footer_part=footer_part,
                )

                replacements: dict[str, bytes] = {
                    "word/document.xml": _xml_bytes(document_root),
                    "word/_rels/document.xml.rels": _xml_bytes(rels_root),
                    "[Content_Types].xml": _xml_bytes(content_types_root),
                    header_part: header_xml,
                    footer_part: footer_xml,
                }
                if header_rels_xml is not None:
                    replacements[header_rels_part] = header_rels_xml
                if footer_rels_xml is not None:
                    replacements[footer_rels_part] = footer_rels_xml
                replacements.update(copied_media)

                with zipfile.ZipFile(
                    temporary, "w", compression=zipfile.ZIP_DEFLATED
                ) as output_zip:
                    for info in target_zip.infolist():
                        name = info.filename
                        if name in replacements or name in _LEGACY_PARTS:
                            continue
                        if name.startswith(_MEDIA_PREFIX):
                            continue
                        output_zip.writestr(info, target_zip.read(name))
                    for name, payload in replacements.items():
                        output_zip.writestr(name, payload)

            # Windows requires the source ZIP handle to be closed before replacement.
            with zipfile.ZipFile(temporary, "r") as check_zip:
                broken = check_zip.testzip()
                if broken:
                    raise LetterheadError(
                        f"O DOCX timbrado ficou corrompido na entrada {broken}."
                    )
                _validate_word_header_footer_parts(check_zip)
            os.replace(temporary, destination)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    except LetterheadError:
        raise
    except (OSError, zipfile.BadZipFile, ET.ParseError, KeyError) as exc:
        raise LetterheadError(f"Não foi possível aplicar o papel timbrado: {exc}") from exc

    return destination


def _prepare_part_relationships(
    letter_zip: zipfile.ZipFile,
    owner_part: str,
    *,
    media_scope: str,
) -> tuple[bytes | None, dict[str, bytes]]:
    owner = PurePosixPath(owner_part)
    rels_name = str(owner.parent / "_rels" / f"{owner.name}.rels")
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
        source_part = _resolve_part(owner_part, target)
        if source_part not in letter_zip.namelist():
            raise LetterheadError(f"Recurso do papel timbrado não encontrado: {source_part}")
        suffix = PurePosixPath(source_part).suffix
        stem = PurePosixPath(source_part).stem
        new_part = f"{_MEDIA_PREFIX}{media_scope}-{stem}{suffix}"
        copied[new_part] = letter_zip.read(source_part)
        relation.set("Target", f"media/{PurePosixPath(new_part).name}")
    return _xml_bytes(root), copied


def _allocate_standard_part_names(target_names: set[str]) -> tuple[str, str]:
    """Allocate Word-compatible header/footer part names not already in the package."""

    def next_name(kind: str) -> str:
        index = 1
        while f"word/{kind}{index}.xml" in target_names:
            index += 1
        return f"word/{kind}{index}.xml"

    return next_name("header"), next_name("footer")


def _rels_part_name(owner_part: str) -> str:
    owner = PurePosixPath(owner_part)
    return str(owner.parent / "_rels" / f"{owner.name}.rels")


def _validate_word_header_footer_parts(archive: zipfile.ZipFile) -> None:
    """Reject legacy/nonstandard Padroniza header/footer relationship targets."""

    rels_root = ET.fromstring(archive.read("word/_rels/document.xml.rels"))
    relation_tag = f"{{{REL_NS}}}Relationship"
    for relation in rels_root.findall(relation_tag):
        rel_type = relation.get("Type", "")
        if rel_type not in {HEADER_REL_TYPE, FOOTER_REL_TYPE}:
            continue
        target = relation.get("Target", "")
        kind = "header" if rel_type == HEADER_REL_TYPE else "footer"
        name = PurePosixPath(target).name
        if not (name.startswith(kind) and name.endswith(".xml") and name[len(kind):-4].isdigit()):
            raise LetterheadError(
                f"Parte de {kind} incompatível com o Word: {target}"
            )

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


def _attach_document_relationships(
    root: ET._Element,
    *,
    header_part: str,
    footer_part: str,
) -> tuple[str, str]:
    relation_tag = f"{{{REL_NS}}}Relationship"
    legacy_targets = {
        PurePosixPath(_LEGACY_HEADER_PART).name,
        PurePosixPath(_LEGACY_FOOTER_PART).name,
    }
    for child in list(root):
        if child.get("Target") in legacy_targets:
            root.remove(child)

    used = {child.get("Id", "") for child in root.findall(relation_tag)}
    header_rid = _next_relationship_id(used)
    used.add(header_rid)
    footer_rid = _next_relationship_id(used)
    ET.SubElement(
        root,
        relation_tag,
        {
            "Id": header_rid,
            "Type": HEADER_REL_TYPE,
            "Target": PurePosixPath(header_part).name,
        },
    )
    ET.SubElement(
        root,
        relation_tag,
        {
            "Id": footer_rid,
            "Type": FOOTER_REL_TYPE,
            "Target": PurePosixPath(footer_part).name,
        },
    )
    return header_rid, footer_rid

def _next_relationship_id(used: set[str]) -> str:
    index = 1
    while f"rId{index}" in used:
        index += 1
    return f"rId{index}"


def _attach_letterhead_to_sections(
    document_root: ET._Element,
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

        references: list[ET._Element] = []
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
    target_root: ET._Element,
    source_root: ET._Element,
    copied_media: dict[str, bytes],
    *,
    header_part: str,
    footer_part: str,
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

    legacy_part_names = {f"/{_LEGACY_HEADER_PART}", f"/{_LEGACY_FOOTER_PART}"}
    for child in list(target_root.findall(override_tag)):
        if child.get("PartName") in legacy_part_names:
            target_root.remove(child)

    ET.SubElement(
        target_root,
        override_tag,
        {
            "PartName": f"/{header_part}",
            "ContentType": "application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml",
        },
    )
    ET.SubElement(
        target_root,
        override_tag,
        {
            "PartName": f"/{footer_part}",
            "ContentType": "application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml",
        },
    )


def _xml_bytes(root: ET._Element) -> bytes:
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)
