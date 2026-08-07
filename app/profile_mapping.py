from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable, Mapping


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


def build_profile_payload(
    fields: Iterable[Mapping[str, Any]],
    current_values: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a profile without dropping template-specific fields.

    Every field is stored under its exact field ID.  When ``profile_key`` is
    configured, the same value is also stored under that portable alias so a
    different template can reuse it.  Exact field IDs are written first and
    aliases never overwrite an exact ID, avoiding accidental collisions.
    """

    field_list = list(fields)
    payload: dict[str, Any] = {}

    # Exact IDs make a profile a complete snapshot for the template where it
    # was created.  This also covers tables, choices, checkboxes and dates.
    for field in field_list:
        field_id = _field_id(field)
        if not field_id:
            continue
        payload[field_id] = deepcopy(current_values.get(field_id))

    # Portable aliases provide conservative cross-template reuse.  Do not
    # replace an exact field ID or an already-populated alias with another
    # field's value when configurations accidentally reuse the same key.
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

    return payload


def resolve_profile_values(
    fields: Iterable[Mapping[str, Any]],
    profile_values: Mapping[str, Any],
) -> dict[str, Any]:
    """Resolve profile data for the current template.

    Exact field IDs always win.  ``profile_key`` is a fallback for profiles
    created from another template and for legacy profiles that stored only
    portable keys.
    """

    resolved: dict[str, Any] = {}
    for field in fields:
        field_id = _field_id(field)
        if not field_id:
            continue

        if field_id in profile_values:
            resolved[field_id] = deepcopy(profile_values[field_id])
            continue

        profile_key = _profile_key(field)
        if profile_key and profile_key in profile_values:
            resolved[field_id] = deepcopy(profile_values[profile_key])

    return resolved
