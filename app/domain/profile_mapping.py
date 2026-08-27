from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from copy import deepcopy
from typing import Any, Iterable, Mapping


# Stored inside the profile values dictionary for backwards compatibility with
# the existing local-data format.  ``@`` is intentionally outside Padroniza's
# valid field-ID syntax, so this key can never collide with a real template
# field.
PROFILE_IDENTITY_KEY = "@padroniza/profile_identity/v2"

_GENERIC_LEGACY_LABELS = {
    "campo",
    "data",
    "descricao",
    "descrição",
    "item",
    "nome",
    "observacao",
    "observação",
    "opcao",
    "opção",
    "quantidade",
    "responsavel",
    "responsável",
    "tipo",
    "unidade",
    "valor",
}

_STRONG_SINGLE_LABELS = {
    "cep",
    "cnpj",
    "cpf",
    "email",
    "e mail",
    "matricula",
    "matrícula",
    "telefone",
    "celular",
    "whatsapp",
}

_TEXT_LIKE_TYPES = {
    "text",
    "email",
    "phone",
    "cpf",
    "cnpj",
    "cep",
    "currency",
    "integer",
    "percentage",
}


def _field_id(field: Mapping[str, Any]) -> str:
    return str(field.get("id", "")).strip()


def _profile_key(field: Mapping[str, Any]) -> str:
    return str(field.get("profile_key", "")).strip()


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) == 0
    return False


def _normalize_identity_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()
    text = re.sub(r"^\s*\d+(?:\.\d+)*\.?\s*", "", text)
    text = text.replace("&", " e ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _normalized_type(field: Mapping[str, Any]) -> str:
    field_type = str(field.get("type", "text") or "text").strip().casefold()
    aliases = {
        "single_choice": "choice",
        "radio": "choice",
        "dropdown": "dropdown",
        "repeatable_table": "repeatable_table",
        "repeatable_list": "repeatable_list",
        "editable_list": "repeatable_list",
        "table": "repeatable_table",
        "multiline": "multiline",
        "checkbox": "checkbox",
        "date": "date",
    }
    return aliases.get(field_type, field_type)


def _types_compatible(source_type: str, target_type: str) -> bool:
    if source_type == target_type:
        return True
    if source_type in _TEXT_LIKE_TYPES and target_type in _TEXT_LIKE_TYPES:
        return True
    return False


def _semantic_identity(field: Mapping[str, Any]) -> str:
    """Return a conservative common-data identity when the label is strong.

    This is deliberately narrower than general NLP matching.  It helps native
    PDF fields and automatic DOCX detections reuse profiles without treating
    generic labels such as ``Data`` or ``Responsável`` as globally equivalent.
    """

    label = _normalize_identity_text(field.get("label", ""))
    field_id = _normalize_identity_text(_field_id(field))
    context = f" {label} {field_id} "

    rules = (
        ("cnpj", (" cnpj ",)),
        ("cpf", (" cpf ",)),
        ("email", (" email ", " e mail ",)),
        ("phone", (" telefone ", " celular ", " whatsapp ", " phone ",)),
        ("cep", (" cep ", " codigo postal ",)),
        ("registration", (" matricula ", " registro funcional ",)),
        ("full_name", (" nome completo ", " nome do servidor ", " nome do solicitante ",)),
        ("legal_name", (" razao social ", " legal name ",)),
        ("trade_name", (" nome fantasia ", " trade name ",)),
    )
    for semantic, needles in rules:
        if any(needle in context for needle in needles):
            return semantic
    return ""


def _identity_descriptor(field: Mapping[str, Any], *, source_id: str | None = None) -> dict[str, str]:
    field_id = source_id if source_id is not None else _field_id(field)
    return {
        "source_id": str(field_id or "").strip(),
        "label": str(field.get("label", "") or "").strip(),
        "label_norm": _normalize_identity_text(field.get("label", "")),
        "type": _normalized_type(field),
        "section": str(field.get("section", "") or "").strip(),
        "section_norm": _normalize_identity_text(field.get("section", "")),
        "profile_key": _profile_key(field),
        "semantic": _semantic_identity(field),
        "context_identity": str(field.get("profile_identity", "") or "").strip(),
        "detection_source": str(field.get("detection_source", "") or "").strip(),
        "label_source": str(field.get("label_source", "") or "").strip(),
    }


def _metadata_fields(profile_values: Mapping[str, Any]) -> list[dict[str, Any]]:
    metadata = profile_values.get(PROFILE_IDENTITY_KEY)
    if not isinstance(metadata, Mapping):
        return []
    raw_fields = metadata.get("fields")
    if not isinstance(raw_fields, list):
        return []
    return [dict(item) for item in raw_fields if isinstance(item, Mapping)]


def _descriptor_match_score(source: Mapping[str, Any], target: Mapping[str, Any]) -> int:
    source_label = _normalize_identity_text(source.get("label_norm") or source.get("label"))
    target_label = _normalize_identity_text(target.get("label_norm") or target.get("label"))
    source_type = str(source.get("type", "text") or "text").casefold()
    target_type = str(target.get("type", "text") or "text").casefold()
    source_section = _normalize_identity_text(source.get("section_norm") or source.get("section"))
    target_section = _normalize_identity_text(target.get("section_norm") or target.get("section"))
    source_semantic = str(source.get("semantic", "") or "")
    target_semantic = str(target.get("semantic", "") or "")
    source_context_identity = str(source.get("context_identity", "") or "").strip()
    target_context_identity = str(target.get("context_identity", "") or "").strip()

    compatible = _types_compatible(source_type, target_type)
    score = 0

    if source_context_identity and source_context_identity == target_context_identity and compatible:
        score = 99
    elif source_label and source_label == target_label:
        score = 96 if compatible else 82
        if source_type == target_type:
            score += 2
        if source_section and target_section and source_section == target_section:
            score += 2
    elif source_semantic and source_semantic == target_semantic and compatible:
        score = 90
        if source_section and target_section and source_section == target_section:
            score += 3
    else:
        return 0

    return min(score, 100)


def _resolve_identity_metadata(
    fields: list[Mapping[str, Any]],
    profile_values: Mapping[str, Any],
    already_resolved: set[str],
) -> dict[str, Any]:
    source_descriptors = _metadata_fields(profile_values)
    if not source_descriptors:
        return {}

    targets = [
        _identity_descriptor(field)
        for field in fields
        if _field_id(field) and _field_id(field) not in already_resolved
    ]
    if not targets:
        return {}

    proposals: list[tuple[int, str, str]] = []
    for target in targets:
        target_id = target["source_id"]
        scored: list[tuple[int, str]] = []
        for source in source_descriptors:
            source_id = str(source.get("source_id", "") or "").strip()
            if not source_id or source_id not in profile_values:
                continue
            score = _descriptor_match_score(source, target)
            if score >= 90:
                scored.append((score, source_id))
        if not scored:
            continue
        scored.sort(reverse=True)
        best_score, best_source = scored[0]
        # Equal-strength candidates are ambiguous.  Do not guess between, for
        # example, two different fields both printed simply as "E-mail".
        if len(scored) > 1 and scored[1][0] == best_score:
            continue
        proposals.append((best_score, target_id, best_source))

    # One source identity must not silently populate several unrelated target
    # fields.  Prefer the strongest unique relationship and reject same-score
    # collisions instead of depending on field order.
    by_source: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for score, target_id, source_id in proposals:
        by_source[source_id].append((score, target_id))

    result: dict[str, Any] = {}
    for source_id, matches in by_source.items():
        matches.sort(reverse=True)
        if len(matches) > 1 and matches[0][0] == matches[1][0]:
            continue
        _score, target_id = matches[0]
        result[target_id] = deepcopy(profile_values[source_id])
    return result


def _legacy_suffixes(key: str) -> set[str]:
    if key == PROFILE_IDENTITY_KEY or key.startswith("@padroniza/"):
        return set()
    normalized = _normalize_identity_text(key)
    tokens = normalized.split()
    suffixes: set[str] = set()
    for size in range(1, min(4, len(tokens)) + 1):
        suffix = " ".join(tokens[-size:])
        if suffix:
            suffixes.add(suffix)
    return suffixes


def _safe_legacy_label(label_norm: str) -> bool:
    if not label_norm:
        return False
    if label_norm in {_normalize_identity_text(value) for value in _GENERIC_LEGACY_LABELS}:
        return False
    if label_norm in {_normalize_identity_text(value) for value in _STRONG_SINGLE_LABELS}:
        return True
    # Multi-word labels are much safer than generic one-word labels.
    return len(label_norm.split()) >= 2 and len(label_norm) >= 7


def _resolve_legacy_label_fallback(
    fields: list[Mapping[str, Any]],
    profile_values: Mapping[str, Any],
    already_resolved: set[str],
) -> dict[str, Any]:
    """Conservative compatibility for profiles saved before identity metadata.

    Auto-detected IDs are normally derived from labels (``auto.nome_completo``),
    so matching a unique normalized suffix lets older profiles benefit from the
    new behaviour too. Generic labels are intentionally excluded.
    """

    unresolved = [field for field in fields if _field_id(field) not in already_resolved]
    label_counts = Counter(_normalize_identity_text(field.get("label", "")) for field in unresolved)

    suffix_to_keys: dict[str, list[str]] = defaultdict(list)
    for key in profile_values:
        if not isinstance(key, str):
            continue
        for suffix in _legacy_suffixes(key):
            suffix_to_keys[suffix].append(key)

    result: dict[str, Any] = {}
    used_keys: set[str] = set()
    for field in unresolved:
        field_id = _field_id(field)
        label_norm = _normalize_identity_text(field.get("label", ""))
        if not field_id or label_counts[label_norm] != 1 or not _safe_legacy_label(label_norm):
            continue
        keys = [key for key in suffix_to_keys.get(label_norm, []) if key not in used_keys]
        # Multiple source keys with the same suffix are ambiguous. Exact IDs
        # and explicit profile keys were already handled before this fallback.
        if len(keys) != 1:
            continue
        key = keys[0]
        result[field_id] = deepcopy(profile_values[key])
        used_keys.add(key)
    return result


def build_profile_payload(
    fields: Iterable[Mapping[str, Any]],
    current_values: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a reusable profile for tagged, native and auto-detected fields.

    Every field is stored under its exact ID. ``profile_key`` remains the
    explicit portable alias.  Version-2 profiles additionally carry a small
    identity index containing labels, field types and sections, allowing
    ``Aplicar perfil`` to safely find equivalent native/automatic fields whose
    generated IDs differ between documents.
    """

    field_list = list(fields)
    payload: dict[str, Any] = {}

    # Exact IDs make a profile a complete snapshot for the template where it
    # was created. This covers tags, native controls, automatic fields, tables,
    # choices, checkboxes and dates.
    for field in field_list:
        field_id = _field_id(field)
        if not field_id:
            continue
        payload[field_id] = deepcopy(current_values.get(field_id))

    # Explicit portable aliases keep their historical precedence and behaviour.
    for field in field_list:
        field_id = _field_id(field)
        profile_key = _profile_key(field)
        if not field_id or not profile_key or profile_key == field_id:
            continue

        value = current_values.get(field_id)
        if profile_key not in payload:
            payload[profile_key] = deepcopy(value)
        elif _is_empty(payload[profile_key]) and not _is_empty(value):
            payload[profile_key] = deepcopy(value)

    identity_fields = [
        _identity_descriptor(field)
        for field in field_list
        if _field_id(field)
    ]
    payload[PROFILE_IDENTITY_KEY] = {
        "version": 2,
        "fields": identity_fields,
    }
    return payload


def resolve_profile_values(
    fields: Iterable[Mapping[str, Any]],
    profile_values: Mapping[str, Any],
) -> dict[str, Any]:
    """Resolve profile data for any compatible current form field.

    Precedence is intentionally conservative:

    1. exact field ID;
    2. explicit ``profile_key``;
    3. V2 stable identity (normalized label + compatible type, with section and
       semantic context as supporting evidence);
    4. safe unique label suffix for legacy profiles created before V2 metadata.

    Ambiguous identity matches are skipped rather than filling the wrong field.
    """

    field_list = list(fields)
    resolved: dict[str, Any] = {}

    for field in field_list:
        field_id = _field_id(field)
        if not field_id:
            continue

        if field_id in profile_values:
            resolved[field_id] = deepcopy(profile_values[field_id])
            continue

        profile_key = _profile_key(field)
        if profile_key and profile_key in profile_values:
            resolved[field_id] = deepcopy(profile_values[profile_key])

    identity_matches = _resolve_identity_metadata(
        field_list,
        profile_values,
        set(resolved),
    )
    for field_id, value in identity_matches.items():
        if field_id not in resolved:
            resolved[field_id] = value

    legacy_matches = _resolve_legacy_label_fallback(
        field_list,
        profile_values,
        set(resolved),
    )
    for field_id, value in legacy_matches.items():
        if field_id not in resolved:
            resolved[field_id] = value

    return resolved
