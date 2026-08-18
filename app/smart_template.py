from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from app.context_resolver import resolve_field_metadata
from app.field_utils import VALID_FIELD_ID, validation_hint
from app.layout_inference import (
    apply_layout_metadata,
    infer_docx_layout,
    layout_quality_issues,
    normalize_form_layout,
)
from app.placeholder_scanner import create_default_fields, scan_docx_fields
from app.word_control_utils import normalize_control_id

PLACEHOLDER_TOKEN = re.compile(r"\{\{([^{}]+)\}\}")
WORD_TEXT = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"
WORD_INSTRUCTION = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}instrText"


# noinspection SpellCheckingInspection
SECTION_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("company", "empresa", "supplier", "fornecedor", "vendor"), 'Empresa / Fornecedor'),
    (("address", "endereco", "endereço", "cep", "city", "cidade", "state", "uf"), 'Endereço'),
    (("process", "processo", "contract", "contrato", "procurement", "licitacao", "licitação"), 'Processo / Contrato'),
    (("document", "documento", "date", "data", "number", "numero", "número"), "Documento"),
    (("signature", "assinatura", "signatory", "responsavel", "responsável"), 'Assinaturas'),
)

PROFILE_PREFIXES = {
    "company": "company",
    "empresa": "company",
    "supplier": "supplier",
    "fornecedor": "supplier",
    "vendor": "supplier",
    "address": "address",
    "endereco": "address",
    "endereço": "address",
    "signatory": "signatory",
    "responsavel": "signatory",
    "responsável": "signatory",
}


def smart_fields_from_docx(
    docx_path: Path,
    existing_fields: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Scan a DOCX and add conservative metadata suggestions to each field."""

    scanned = scan_docx_fields(Path(docx_path))
    fields = create_default_fields(scanned, existing_fields or [])
    fields = apply_layout_metadata(
        fields,
        infer_docx_layout(Path(docx_path)),
    )

    # Detector V3: every field goes through the same conservative context
    # resolver. Explicit/manual/native metadata remains authoritative; only
    # missing or generic metadata receives contextual fallbacks.
    resolved_fields: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    for field in fields:
        resolved = resolve_field_metadata(field, used_ids=used_ids)
        resolved_fields.append(resolved)
    fields = resolved_fields

    for field in fields:
        field_id = str(field.get("id", "")).strip()
        lowered = field_id.casefold()

        field.setdefault("section", suggest_section(lowered))
        if (
            str(field.get("tag_type", "")).casefold() == "single_choice"
            and str(field.get("layout", "")).casefold() == "choice"
        ):
            current_group_label = str(field.get("layout_group_label", "")).strip()
            section_label = str(field.get("section", "")).strip()
            field_label = str(field.get("label", "")).strip()
            native_pdf_choice = (
                str(field.get("detection_source", "")).strip().casefold() == "native_pdf"
            )
            # Layout inference often uses the surrounding section as a fallback
            # group title. For native PDF radio groups that hides the real
            # printed question and the renderer falls back to the generic
            # ``Selecione uma opção`` text. Prefer the field's visible PDF
            # label whenever the inferred title is empty or merely repeats the
            # section heading.
            if not current_group_label:
                field["layout_group_label"] = (
                    (field_label or section_label)
                    if native_pdf_choice
                    else (section_label or field_label)
                ) or "Escolha uma opção"
            elif (
                native_pdf_choice
                and section_label
                and current_group_label.casefold() == section_label.casefold()
                and field_label
            ):
                field["layout_group_label"] = field_label

        profile_key = suggest_profile_key(field_id)
        if profile_key:
            field.setdefault("profile_key", profile_key)

        # Explicit Word controls keep their type. Generic text markers use
        # both the technical ID and the nearby DOCX label as context.
        current_type = str(field.get("type", "text")).casefold()
        type_source = str(field.get("type_source", "")).strip().casefold()
        if current_type == "text" and type_source != "automatic_detection":
            label = str(field.get("label", "")).strip()
            matrix_observation = (
                str(field.get("layout", "")).strip().casefold() == "table"
                and bool(str(field.get("layout_row_label", "")).strip())
                and str(field.get("layout_column", "")).strip().casefold()
                in {"observacao", "observação", "obs", "observation"}
            )
            suggested_type = (
                "text"
                if matrix_observation
                else suggest_field_type(f"{field_id} {label}")
            )
            field["type"] = suggested_type
            if suggested_type != "text":
                field["type_source"] = "automatic"

        if field.get("type") == "checkbox":
            field["required"] = False
        else:
            field.setdefault("required", True)

        if field.get("type") == "date":
            field.setdefault("automatic", True)

        if field.get("type") == "percentage":
            field.setdefault("min", 0)
            field.setdefault("max", 100)

        hint = validation_hint(field)
        if hint:
            field.setdefault("validation_hint", hint)

    return normalize_form_layout(fields)


def suggest_field_type(field_context: str) -> str:
    text = str(field_context).casefold()
    parts = {
        part
        for part in re.split(r"[._\-\s/()]+", text)
        if part
    }
    last = re.split(r"[._\-\s]+", text.strip())[-1]

    if "cnpj" in text:
        return "cnpj"
    if re.search(r"(^|[._\-\s])cpf($|[._\-\s])", text):
        return "cpf"
    if "email" in text or "e-mail" in text:
        return "email"
    if any(
        token in text
        for token in (
            "phone",
            "telefone",
            "celular",
            "mobile",
            "whatsapp",
        )
    ):
        return "phone"
    if "cep" in parts or "postal" in text or "zip_code" in text:
        return "cep"
    if (
        last in {
            "date",
            "data",
            "issued",
            "signed",
            "deadline",
            "validity",
        }
        or text.endswith(".date")
    ):
        return "date"
    if any(
        token in text
        for token in (
            "percent",
            "percentage",
            "percentual",
            "porcentagem",
            "tax_rate",
            "aliquota",
            "alíquota",
        )
    ):
        return "percentage"
    if any(
        token in text
        for token in (
            "amount",
            "total_value",
            "valor_total",
            "valor total",
            "valor_estimado",
            "valor estimado",
            "price",
            "preco",
            "preço",
            "montante",
            "custo_total",
            "custo total",
            "currency",
            "orcamento",
            "orçamento",
        )
    ):
        return "currency"
    if parts.intersection({"quantity", "qty", "count", "quantidade"}):
        return "integer"
    if any(
        token in text
        for token in (
            "description",
            "descricao",
            "descrição",
            "notes",
            "observations",
            "observation",
            "observacoes",
            "observações",
            "observacao",
            "observação",
            "justification",
            "justificativa",
            "object",
            "objeto",
            "fundamentacao",
            "fundamentação",
            "providencia",
            "providência",
        )
    ):
        return "multiline"
    if any(
        token in text
        for token in (
            "accepted",
            "approved",
            "confirmed",
            "declaration",
            "declaracao",
            "declaração",
            "checkbox",
        )
    ):
        return "checkbox"
    return "text"

def suggest_section(field_id: str) -> str:
    lowered = field_id.casefold()
    for tokens, section in SECTION_RULES:
        if any(token in lowered for token in tokens):
            return section
    return 'Dados do documento'


def suggest_profile_key(field_id: str) -> str:
    pieces = [piece for piece in re.split(r"[._-]+", field_id) if piece]
    if not pieces:
        return ""

    prefix = PROFILE_PREFIXES.get(pieces[0].casefold())
    if not prefix:
        return ""

    return ".".join([prefix, *pieces[1:]])


def scan_docx_health(docx_path: Path) -> dict[str, Any]:
    """Return structural placeholder problems that are safe to detect offline."""

    path = Path(docx_path)
    text_parts: list[str] = []

    with zipfile.ZipFile(path, "r") as archive:
        for name in archive.namelist():
            if not (name.startswith("word/") and name.endswith(".xml")):
                continue
            try:
                root = ElementTree.fromstring(archive.read(name))
            except ElementTree.ParseError:
                continue
            text_parts.append("".join(node.text or "" for node in root.iter(WORD_TEXT)))
            text_parts.append("".join(node.text or "" for node in root.iter(WORD_INSTRUCTION)))

    text = "\n".join(text_parts)
    raw_tokens = [match.group(1).strip() for match in PLACEHOLDER_TOKEN.finditer(text)]
    normalized_ids: list[str] = []
    malformed: list[str] = []

    for raw in raw_tokens:
        field_id = _field_id_from_token(raw)
        if not field_id or not VALID_FIELD_ID.match(field_id):
            malformed.append(raw)
        elif field_id not in normalized_ids:
            normalized_ids.append(field_id)

    occurrence_counts: dict[str, int] = {}
    for raw in raw_tokens:
        field_id = _field_id_from_token(raw)
        if field_id:
            occurrence_counts[field_id] = occurrence_counts.get(field_id, 0) + 1

    duplicate_occurrences = {
        field_id: count
        for field_id, count in occurrence_counts.items()
        if count > 1
    }

    unmatched_open = max(0, text.count("{{") - len(raw_tokens))
    unmatched_close = max(0, text.count("}}") - len(raw_tokens))

    return {
        "raw_tokens": raw_tokens,
        "field_ids": normalized_ids,
        "malformed_placeholders": sorted(set(malformed)),
        "duplicate_occurrences": duplicate_occurrences,
        "unmatched_open_braces": unmatched_open,
        "unmatched_close_braces": unmatched_close,
    }


def readiness_report(
    *,
    name: str,
    docx_path: Path | None,
    fields: list[dict[str, Any]],
    filename_pattern: str,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    checks.append({"label": 'Nome do modelo', "ok": bool(str(name).strip())})
    checks.append({"label": 'DOCX de origem', "ok": bool(docx_path and Path(docx_path).exists())})
    checks.append({"label": 'Campos detectados', "ok": bool(fields), "detail": f"{len(fields)} configurados"})

    ids = [str(field.get("id", "")).strip() for field in fields]
    duplicate_ids = sorted({field_id for field_id in ids if field_id and ids.count(field_id) > 1})
    invalid_ids = sorted({field_id for field_id in ids if field_id and not VALID_FIELD_ID.match(field_id)})
    checks.append({"label": 'IDs de campo exclusivos', "ok": not duplicate_ids, "detail": ", ".join(duplicate_ids)})
    checks.append({"label": 'IDs de campo válidos', "ok": not invalid_ids, "detail": ", ".join(invalid_ids)})

    invalid_dropdowns = [
        str(field.get("id", ""))
        for field in fields
        if str(field.get("type", "")) == "dropdown" and not field.get("options")
    ]
    checks.append({"label": 'Opções da lista suspensa', "ok": not invalid_dropdowns, "detail": ", ".join(invalid_dropdowns)})

    invalid_repeatable_tables = [
        str(field.get("id", ""))
        for field in fields
        if str(field.get("type", "")) == "repeatable_table"
        and not field.get("columns")
    ]
    checks.append({
        "label": 'Colunas das tabelas repetíveis',
        "ok": not invalid_repeatable_tables,
        "detail": ", ".join(invalid_repeatable_tables),
    })

    known_tokens = {"template.name", "year", "sequence", *ids}
    tokens = set(PLACEHOLDER_TOKEN.findall(str(filename_pattern)))
    unknown_tokens = sorted(token for token in tokens if token not in known_tokens)
    checks.append({"label": 'Marcadores do nome do arquivo', "ok": not unknown_tokens, "detail": ", ".join(unknown_tokens)})

    layout_issues = layout_quality_issues(fields)
    checks.append({
        "label": "Organização visual do formulário",
        "ok": not layout_issues,
        "detail": " • ".join(layout_issues),
    })

    health: dict[str, Any] = {}
    if docx_path and Path(docx_path).exists():
        try:
            health = scan_docx_health(Path(docx_path))
        except Exception as exc:
            health = {"scan_error": str(exc)}

    malformed = list(health.get("malformed_placeholders", []))
    brace_problem = bool(
        health.get("unmatched_open_braces", 0)
        or health.get("unmatched_close_braces", 0)
    )
    checks.append({"label": 'Sintaxe dos marcadores', "ok": not malformed and not brace_problem, "detail": ", ".join(malformed)})

    return {
        "checks": checks,
        "ready": all(bool(item.get("ok")) for item in checks),
        "health": health,
    }


def _field_id_from_token(raw: str) -> str:
    text = str(raw).strip()
    lowered = text.casefold()
    if lowered.startswith(("checkbox:", "date:")):
        return normalize_control_id(text.split(":", 1)[1].strip())
    if lowered.startswith(("dropdown:", "single_choice:")):
        return normalize_control_id(text.split(":", 1)[1].split("|", 1)[0].strip())
    if lowered.startswith("repeat:"):
        return normalize_control_id(text.split(":", 1)[1].strip())
    return normalize_control_id(text)
