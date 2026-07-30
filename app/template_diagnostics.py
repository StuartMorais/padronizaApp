from __future__ import annotations

import re
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from app.placeholder_scanner import scan_docx_fields
from app.smart_template import VALID_FIELD_ID, scan_docx_health


PLACEHOLDER_PATTERN = re.compile(r"\{\{([^{}]+)\}\}")
WORD_NAMESPACE = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
WORD14_NAMESPACE = "{http://schemas.microsoft.com/office/word/2010/wordml}"


def diagnose_template(config: dict[str, Any], source_path: Path) -> dict[str, Any]:
    source_path = Path(source_path)
    configured_fields = [
        field
        for field in config.get("fields", [])
        if isinstance(field, dict) and str(field.get("id", "")).strip()
    ]

    configured_ids_list = [str(field.get("id", "")).strip() for field in configured_fields]
    duplicate_config_ids = sorted(
        {
            field_id
            for field_id in configured_ids_list
            if configured_ids_list.count(field_id) > 1
        }
    )
    invalid_config_ids = sorted(
        {
            field_id
            for field_id in configured_ids_list
            if field_id and not VALID_FIELD_ID.match(field_id)
        }
    )
    configured_by_id = {str(field["id"]): field for field in configured_fields}

    missing_source = not source_path.exists()
    scanned_fields: list[dict[str, Any]] = []
    health: dict[str, Any] = {}
    scan_error = ""

    if not missing_source:
        try:
            scanned_fields = scan_docx_fields(source_path)
            health = scan_docx_health(source_path)
        except Exception as exc:
            scan_error = str(exc)

    scanned_by_id = {str(field.get("id", "")): field for field in scanned_fields}
    configured_ids = set(configured_by_id)
    scanned_ids = set(scanned_by_id)

    missing_config = sorted(scanned_ids - configured_ids)
    unused_config = sorted(configured_ids - scanned_ids)
    type_mismatches: list[dict[str, str]] = []

    for field_id in sorted(configured_ids & scanned_ids):
        configured_type = str(configured_by_id[field_id].get("type", "text"))
        scanned_type = str(scanned_by_id[field_id].get("type", "text"))
        if scanned_type in {
            "checkbox",
            "date",
            "dropdown",
            "repeatable_table",
        } and configured_type != scanned_type:
            type_mismatches.append(
                {
                    "id": field_id,
                    "configured": configured_type,
                    "detected": scanned_type,
                }
            )

    invalid_conditions: list[str] = []
    known_ids = set(configured_ids_list)
    for field in configured_fields:
        field_id = str(field.get("id", ""))
        condition = field.get("visible_when")
        if not condition:
            continue
        if not isinstance(condition, dict):
            invalid_conditions.append(f"{field_id}: a condição não é um objeto")
            continue
        dependency = str(condition.get("field", "")).strip()
        if not dependency:
            invalid_conditions.append(f"{field_id}: a condição não informa o campo")
        elif dependency not in known_ids:
            invalid_conditions.append(f"{field_id}: referencia o campo ausente {dependency}")
        if not any(key in condition for key in ("equals", "not_equals", "truthy")):
            invalid_conditions.append(f"{field_id}: a condição não possui comparação")

    invalid_dropdowns = sorted(
        str(field.get("id", ""))
        for field in configured_fields
        if str(field.get("type", "")) == "dropdown" and not field.get("options")
    )
    invalid_repeatable_tables = sorted(
        str(field.get("id", ""))
        for field in configured_fields
        if str(field.get("type", "")) == "repeatable_table"
        and not field.get("columns")
    )

    output = config.get("output", {}) if isinstance(config.get("output"), dict) else {}
    filename_pattern = str(output.get("filename_pattern", ""))
    filename_tokens = {
        match.group(1).strip()
        for match in PLACEHOLDER_PATTERN.finditer(filename_pattern)
    }
    allowed_tokens = {"template.name", "year", "sequence", *configured_ids}
    invalid_filename_tokens = sorted(filename_tokens - allowed_tokens)

    locations = _scan_locations(source_path) if source_path.exists() else {}

    warnings: list[str] = []
    if missing_source:
        warnings.append('O DOCX de origem está ausente.')
    if scan_error:
        warnings.append(f"Não foi possível analisar o DOCX: {scan_error}")
    if missing_config:
        warnings.append(f"{len(missing_config)} campo(s) do DOCX não possuem configuração.")
    if unused_config:
        warnings.append(f"{len(unused_config)} campo(s) configurados não aparecem no DOCX.")
    if type_mismatches:
        warnings.append(f"Foram detectadas {len(type_mismatches)} incompatibilidade(s) de tipo de campo.")
    if duplicate_config_ids:
        warnings.append(f"Foram detectados {len(duplicate_config_ids)} ID(s) de campo configurado duplicados.")
    if invalid_config_ids:
        warnings.append(f"{len(invalid_config_ids)} ID(s) de campo configurado são inválidos.")
    if invalid_conditions:
        warnings.append(f"Foram detectados {len(invalid_conditions)} problema(s) em regras condicionais.")
    if invalid_dropdowns:
        warnings.append(f"{len(invalid_dropdowns)} lista(s) suspensa(s) não possuem opções.")
    if invalid_repeatable_tables:
        warnings.append(
            f"{len(invalid_repeatable_tables)} tabela(s) repetível(is) não possuem colunas."
        )
    if invalid_filename_tokens:
        warnings.append(f"{len(invalid_filename_tokens)} marcador(es) do nome do arquivo são desconhecidos.")
    if health.get("malformed_placeholders"):
        warnings.append(f"Foram detectados {len(health['malformed_placeholders'])} marcador(es) malformados.")
    if health.get("unmatched_open_braces") or health.get("unmatched_close_braces"):
        warnings.append('Foram detectadas chaves de marcadores sem par no DOCX.')

    return {
        "configured_count": len(configured_fields),
        "detected_count": len(scanned_fields),
        "missing_source": missing_source,
        "scan_error": scan_error,
        "missing_config": missing_config,
        "unused_config": unused_config,
        "type_mismatches": type_mismatches,
        "duplicate_config_ids": duplicate_config_ids,
        "invalid_config_ids": invalid_config_ids,
        "invalid_conditions": invalid_conditions,
        "invalid_dropdowns": invalid_dropdowns,
        "invalid_repeatable_tables": invalid_repeatable_tables,
        "invalid_filename_tokens": invalid_filename_tokens,
        "malformed_placeholders": health.get("malformed_placeholders", []),
        "duplicate_occurrences": health.get("duplicate_occurrences", {}),
        "unmatched_open_braces": health.get("unmatched_open_braces", 0),
        "unmatched_close_braces": health.get("unmatched_close_braces", 0),
        "locations": locations,
        "warnings": warnings,
        "ok": not warnings,
        "safe_fix_available": bool(missing_config or type_mismatches),
    }


def diagnostics_text(report: dict[str, Any]) -> str:
    lines = [
        f"Campos detectados no DOCX: {report.get('detected_count', 0)}",
        f"Campos configurados: {report.get('configured_count', 0)}",
        "",
    ]

    if report.get("ok"):
        lines.append('✓ A configuração do modelo corresponde aos campos do DOCX.')
    else:
        for warning in report.get("warnings", []):
            lines.append(f"⚠ {warning}")

    missing = report.get("missing_config", [])
    if missing:
        lines.extend(["", 'Campos detectados, mas não configurados:'])
        lines.extend(f"  • {field_id}" for field_id in missing)

    unused = report.get("unused_config", [])
    if unused:
        lines.extend(["", 'Campos configurados ausentes no DOCX:'])
        lines.extend(f"  • {field_id}" for field_id in unused)

    mismatches = report.get("type_mismatches", [])
    if mismatches:
        lines.extend(["", 'Tipos incompatíveis:'])
        for item in mismatches:
            lines.append(
                f"  • {item['id']}: configurado {item['configured']}, detectado {item['detected']}"
            )

    for key, title in (
        ("duplicate_config_ids", 'IDs configurados duplicados'),
        ("invalid_config_ids", 'IDs configurados inválidos'),
        ("invalid_conditions", 'Problemas nas regras condicionais'),
        ("invalid_dropdowns", 'Listas suspensas sem opções'),
        ("invalid_repeatable_tables", 'Tabelas repetíveis sem colunas'),
        ("invalid_filename_tokens", 'Marcadores desconhecidos no nome do arquivo'),
        ("malformed_placeholders", 'Marcadores malformados'),
    ):
        values = report.get(key, [])
        if values:
            lines.extend(["", f"{title}:"])
            lines.extend(f"  • {value}" for value in values)

    duplicate_occurrences = report.get("duplicate_occurrences", {})
    if duplicate_occurrences:
        lines.extend(["", 'Ocorrências repetidas de marcadores:'])
        for field_id, count in sorted(duplicate_occurrences.items()):
            lines.append(f"  • {field_id}: {count} ocorrências")

    locations = report.get("locations", {})
    if locations:
        lines.extend(["", 'Locais dos campos:'])
        for field_id in sorted(locations):
            lines.append(f"  • {field_id}: {', '.join(locations[field_id])}")

    return "\n".join(lines)


def _scan_locations(docx_path: Path) -> dict[str, list[str]]:
    locations: dict[str, set[str]] = defaultdict(set)

    with zipfile.ZipFile(docx_path, "r") as archive:
        xml_names = [
            name
            for name in archive.namelist()
            if name.startswith("word/") and name.endswith(".xml")
        ]

        for xml_name in xml_names:
            try:
                root = ElementTree.fromstring(archive.read(xml_name))
            except ElementTree.ParseError:
                continue

            part_name = _friendly_part_name(xml_name)
            text = "".join(node.text or "" for node in root.iter(f"{WORD_NAMESPACE}t"))
            text += "".join(node.text or "" for node in root.iter(f"{WORD_NAMESPACE}instrText"))

            for match in PLACEHOLDER_PATTERN.finditer(text):
                raw = match.group(1).strip()
                field_id = _placeholder_id(raw)
                if field_id:
                    locations[field_id].add(part_name)

            for control in root.iter(f"{WORD_NAMESPACE}sdt"):
                properties = control.find(f"{WORD_NAMESPACE}sdtPr")
                if properties is None:
                    continue

                tag = properties.find(f"{WORD_NAMESPACE}tag")
                alias = properties.find(f"{WORD_NAMESPACE}alias")
                value = ""
                if tag is not None:
                    value = tag.attrib.get(f"{WORD_NAMESPACE}val", "")
                if not value and alias is not None:
                    value = alias.attrib.get(f"{WORD_NAMESPACE}val", "")
                value = _placeholder_id(value)
                if value:
                    locations[value].add(part_name)

            for field_data in root.iter(f"{WORD_NAMESPACE}ffData"):
                name = field_data.find(f"{WORD_NAMESPACE}name")
                if name is None:
                    continue
                value = name.attrib.get(f"{WORD_NAMESPACE}val", "")
                value = _placeholder_id(value)
                if value:
                    locations[value].add(part_name)

    return {field_id: sorted(parts) for field_id, parts in locations.items()}


def _placeholder_id(raw: str) -> str:
    raw = str(raw).strip()
    lowered = raw.casefold()
    if lowered.startswith("checkbox:") or lowered.startswith("date:"):
        return raw.split(":", 1)[1].strip()
    if lowered.startswith("dropdown:"):
        return raw.split(":", 1)[1].split("|", 1)[0].strip()
    if lowered.startswith("repeat:"):
        return raw.split(":", 1)[1].strip()
    return raw


def _friendly_part_name(xml_name: str) -> str:
    filename = Path(xml_name).name
    if filename == "document.xml":
        return "Corpo / tabelas / caixas de texto"
    if filename.startswith("header"):
        return "Cabeçalho"
    if filename.startswith("footer"):
        return "Rodapé"
    if filename == "footnotes.xml":
        return "Notas de rodapé"
    if filename == "endnotes.xml":
        return "Notas finais"
    if filename == "comments.xml":
        return "Comentários"
    return filename
