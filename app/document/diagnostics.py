from __future__ import annotations

import re
import zipfile
from collections import defaultdict
from copy import deepcopy
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from app.document.docx.scanner import scan_docx_fields
from app.document.docx.tags import parse_tag
from app.document.understanding.smart_template import VALID_FIELD_ID, scan_docx_health
from app.domain.field_metadata import (
    dropdown_option_values,
    normalize_repeatable_columns,
    raw_dropdown_option_values,
    raw_repeatable_column_ids,
)


PLACEHOLDER_PATTERN = re.compile(r"\{\{([^{}]+)\}\}")
WORD_NAMESPACE = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
WORD14_NAMESPACE = "{http://schemas.microsoft.com/office/word/2010/wordml}"


@dataclass(frozen=True)
class DiagnosticIssue:
    code: str
    severity: str
    message: str
    field_id: str = ""
    locations: tuple[str, ...] = ()
    safe_fix: bool = False


def _source_signature(path: Path) -> tuple[str, int, int]:
    stat = path.stat()
    return str(path.resolve()), int(stat.st_mtime_ns), int(stat.st_size)


@lru_cache(maxsize=64)
def _cached_source_analysis(
    resolved_path: str,
    _mtime_ns: int,
    _size: int,
) -> tuple[tuple[dict[str, Any], ...], dict[str, Any], dict[str, list[str]]]:
    path = Path(resolved_path)
    fields = tuple(dict(field) for field in scan_docx_fields(path))
    health = deepcopy(scan_docx_health(path))
    locations = _scan_locations(path)
    return fields, health, locations


def clear_diagnostics_cache() -> None:
    _cached_source_analysis.cache_clear()


def _analyze_source(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, list[str]]]:
    fields, health, locations = _cached_source_analysis(*_source_signature(path))
    return [deepcopy(field) for field in fields], deepcopy(health), deepcopy(locations)


def diagnose_template(config: dict[str, Any], source_path: Path) -> dict[str, Any]:
    source_path = Path(source_path)
    configured_fields = [
        field
        for field in config.get("fields", [])
        if isinstance(field, dict) and str(field.get("id", "")).strip()
    ]
    configured_ids_list = [str(field.get("id", "")).strip() for field in configured_fields]
    duplicate_config_ids = sorted({field_id for field_id in configured_ids_list if configured_ids_list.count(field_id) > 1})
    invalid_config_ids = sorted({field_id for field_id in configured_ids_list if field_id and not VALID_FIELD_ID.match(field_id)})
    configured_by_id = {str(field["id"]): field for field in configured_fields}

    missing_source = not source_path.exists()
    scanned_fields: list[dict[str, Any]] = []
    health: dict[str, Any] = {}
    locations: dict[str, list[str]] = {}
    scan_error = ""
    if not missing_source:
        try:
            scanned_fields, health, locations = _analyze_source(source_path)
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
        if scanned_type in {"checkbox", "date", "dropdown", "repeatable_table"} and configured_type != scanned_type:
            type_mismatches.append({"id": field_id, "configured": configured_type, "detected": scanned_type})

    invalid_conditions, condition_cycles = _condition_problems(configured_fields)
    invalid_dropdowns = sorted(
        str(field.get("id", ""))
        for field in configured_fields
        if str(field.get("type", "")) == "dropdown"
        and len(dropdown_option_values(field.get("options", []))) < 2
    )
    duplicate_dropdown_options: dict[str, list[str]] = {}
    invalid_repeatable_tables: list[str] = []
    duplicate_table_columns: dict[str, list[str]] = {}
    for field in configured_fields:
        field_id = str(field.get("id", ""))
        field_type = str(field.get("type", ""))
        if field_type == "dropdown":
            raw_values = raw_dropdown_option_values(field.get("options", []))
            duplicates = sorted(
                {value for value in raw_values if raw_values.count(value) > 1}
            )
            if duplicates:
                duplicate_dropdown_options[field_id] = duplicates
        if field_type == "repeatable_table":
            columns = normalize_repeatable_columns(field.get("columns", []))
            if not columns:
                invalid_repeatable_tables.append(field_id)
            raw_column_ids = raw_repeatable_column_ids(field.get("columns", []))
            duplicates = sorted(
                {
                    column_id
                    for column_id in raw_column_ids
                    if raw_column_ids.count(column_id) > 1
                }
            )
            if duplicates:
                duplicate_table_columns[field_id] = duplicates
    invalid_repeatable_tables.sort()

    output = config.get("output", {}) if isinstance(config.get("output"), dict) else {}
    filename_pattern = str(output.get("filename_pattern", ""))
    filename_tokens = {match.group(1).strip() for match in PLACEHOLDER_PATTERN.finditer(filename_pattern)}
    allowed_tokens = {"template.name", "year", "sequence", *configured_ids}
    invalid_filename_tokens = sorted(filename_tokens - allowed_tokens)

    issues: list[DiagnosticIssue] = []
    def add(code: str, severity: str, message: str, field_id: str = "", safe_fix: bool = False) -> None:
        issues.append(DiagnosticIssue(code, severity, message, field_id, tuple(locations.get(field_id, ())), safe_fix))

    if missing_source:
        add("source.missing", "error", "O DOCX de origem está ausente.")
    if scan_error:
        add("source.scan_failed", "error", f"Não foi possível analisar o DOCX: {scan_error}")
    for field_id in missing_config:
        add("field.missing_config", "warning", "Campo do DOCX sem configuração no modelo.", field_id, True)
    for field_id in unused_config:
        add("field.unused_config", "warning", "Campo configurado não aparece no DOCX.", field_id)
    for mismatch in type_mismatches:
        add(
            "field.type_mismatch", "warning",
            f"Tipo configurado '{mismatch['configured']}' difere do tipo detectado '{mismatch['detected']}'.",
            mismatch["id"], True,
        )
    for field_id in duplicate_config_ids:
        add("field.duplicate_id", "error", "ID de campo configurado mais de uma vez.", field_id)
    for field_id in invalid_config_ids:
        add("field.invalid_id", "error", "ID de campo inválido.", field_id)
    for problem in invalid_conditions:
        add("condition.invalid", "error", problem)
    for cycle in condition_cycles:
        add("condition.cycle", "error", "Dependência condicional circular: " + " → ".join(cycle))
    for field_id in invalid_dropdowns:
        add("dropdown.no_options", "error", "Lista suspensa com menos de duas opções.", field_id)
    for field_id, duplicates in duplicate_dropdown_options.items():
        add("dropdown.duplicate_options", "warning", "Opções repetidas: " + ", ".join(duplicates), field_id)
    for field_id in invalid_repeatable_tables:
        add("table.no_columns", "error", "Tabela repetível sem colunas.", field_id)
    for field_id, duplicates in duplicate_table_columns.items():
        add("table.duplicate_columns", "error", "IDs de coluna repetidos: " + ", ".join(duplicates), field_id)
    for token in invalid_filename_tokens:
        add("output.unknown_token", "warning", f"Marcador desconhecido no nome do arquivo: {token}")
    for malformed in health.get("malformed_placeholders", []):
        add("tag.malformed", "error", f"Marcador malformado: {malformed}")
    if health.get("unmatched_open_braces") or health.get("unmatched_close_braces"):
        add("tag.unmatched_braces", "error", "Foram detectadas chaves de marcadores sem par no DOCX.")

    warnings = _legacy_warning_summary(
        missing_source=missing_source, scan_error=scan_error, missing_config=missing_config,
        unused_config=unused_config, type_mismatches=type_mismatches, duplicate_config_ids=duplicate_config_ids,
        invalid_config_ids=invalid_config_ids, invalid_conditions=invalid_conditions, condition_cycles=condition_cycles,
        invalid_dropdowns=invalid_dropdowns, duplicate_dropdown_options=duplicate_dropdown_options,
        invalid_repeatable_tables=invalid_repeatable_tables, duplicate_table_columns=duplicate_table_columns,
        invalid_filename_tokens=invalid_filename_tokens, health=health,
    )
    blocking_count = sum(1 for issue in issues if issue.severity == "error")
    warning_count = sum(1 for issue in issues if issue.severity == "warning")

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
        "condition_cycles": condition_cycles,
        "invalid_dropdowns": invalid_dropdowns,
        "duplicate_dropdown_options": duplicate_dropdown_options,
        "invalid_repeatable_tables": invalid_repeatable_tables,
        "duplicate_table_columns": duplicate_table_columns,
        "invalid_filename_tokens": invalid_filename_tokens,
        "malformed_placeholders": health.get("malformed_placeholders", []),
        "duplicate_occurrences": health.get("duplicate_occurrences", {}),
        "unmatched_open_braces": health.get("unmatched_open_braces", 0),
        "unmatched_close_braces": health.get("unmatched_close_braces", 0),
        "locations": locations,
        "issues": [asdict(issue) for issue in issues],
        "blocking_count": blocking_count,
        "warning_count": warning_count,
        "warnings": warnings,
        "ok": not issues,
        "blocking": blocking_count > 0,
        "safe_fix_available": any(issue.safe_fix for issue in issues),
    }


def _condition_problems(fields: list[dict[str, Any]]) -> tuple[list[str], list[list[str]]]:
    invalid: list[str] = []
    known_ids = {str(field.get("id", "")).strip() for field in fields}
    graph: dict[str, str] = {}
    for field in fields:
        field_id = str(field.get("id", "")).strip()
        condition = field.get("visible_when")
        if not condition:
            continue
        if not isinstance(condition, dict):
            invalid.append(f"{field_id}: a condição não é um objeto")
            continue
        dependency = str(condition.get("field", "")).strip()
        if not dependency:
            invalid.append(f"{field_id}: a condição não informa o campo")
        elif dependency not in known_ids:
            invalid.append(f"{field_id}: referencia o campo ausente {dependency}")
        else:
            graph[field_id] = dependency
        if not any(key in condition for key in ("equals", "not_equals", "truthy")):
            invalid.append(f"{field_id}: a condição não possui comparação")

    cycles: list[list[str]] = []
    recorded: set[frozenset[str]] = set()
    for start in graph:
        order: list[str] = []
        positions: dict[str, int] = {}
        current = start
        while current in graph:
            if current in positions:
                cycle = order[positions[current]:] + [current]
                key = frozenset(cycle)
                if key not in recorded:
                    recorded.add(key)
                    cycles.append(cycle)
                break
            positions[current] = len(order)
            order.append(current)
            current = graph[current]
    return invalid, cycles


def _legacy_warning_summary(**values: Any) -> list[str]:
    warnings: list[str] = []
    if values["missing_source"]:
        warnings.append("O DOCX de origem está ausente.")
    if values["scan_error"]:
        warnings.append(f"Não foi possível analisar o DOCX: {values['scan_error']}")
    count_messages = (
        ("missing_config", "campo(s) do DOCX não possuem configuração"),
        ("unused_config", "campo(s) configurados não aparecem no DOCX"),
        ("type_mismatches", "incompatibilidade(s) de tipo de campo"),
        ("duplicate_config_ids", "ID(s) de campo configurado duplicados"),
        ("invalid_config_ids", "ID(s) de campo configurado são inválidos"),
        ("invalid_conditions", "problema(s) em regras condicionais"),
        ("condition_cycles", "ciclo(s) em regras condicionais"),
        ("invalid_dropdowns", "lista(s) suspensa(s) não possuem opções"),
        ("duplicate_dropdown_options", "lista(s) suspensa(s) possuem opções repetidas"),
        ("invalid_repeatable_tables", "tabela(s) repetível(is) não possuem colunas"),
        ("duplicate_table_columns", "tabela(s) repetível(is) possuem IDs de coluna duplicados"),
        ("invalid_filename_tokens", "marcador(es) do nome do arquivo são desconhecidos"),
    )
    for key, label in count_messages:
        item = values[key]
        if item:
            warnings.append(f"Foram detectados {len(item)} {label}.")
    health = values["health"]
    if health.get("malformed_placeholders"):
        warnings.append(f"Foram detectados {len(health['malformed_placeholders'])} marcador(es) malformados.")
    if health.get("unmatched_open_braces") or health.get("unmatched_close_braces"):
        warnings.append("Foram detectadas chaves de marcadores sem par no DOCX.")
    return warnings


def diagnostics_text(report: dict[str, Any]) -> str:
    lines = [
        f"Campos detectados no DOCX: {report.get('detected_count', 0)}",
        f"Campos configurados: {report.get('configured_count', 0)}",
        f"Erros: {report.get('blocking_count', 0)}  •  Avisos: {report.get('warning_count', 0)}",
        "",
    ]
    issues = report.get("issues", [])
    if not issues:
        lines.append("✓ A configuração do modelo corresponde aos campos do DOCX.")
    else:
        for issue in issues:
            marker = "✕" if issue.get("severity") == "error" else "⚠"
            field_id = str(issue.get("field_id", "")).strip()
            prefix = f"{field_id}: " if field_id else ""
            lines.append(f"{marker} {prefix}{issue.get('message', '')}")
            issue_locations = issue.get("locations", [])
            if issue_locations:
                lines.append("    Local: " + ", ".join(issue_locations))

    duplicate_occurrences = report.get("duplicate_occurrences", {})
    if duplicate_occurrences:
        lines.extend(["", "Ocorrências repetidas de marcadores:"])
        for field_id, count in sorted(duplicate_occurrences.items()):
            lines.append(f"  • {field_id}: {count} ocorrências")
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
    return parse_tag(str(raw), strict=False).field_id


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
