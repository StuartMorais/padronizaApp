from __future__ import annotations

from typing import Any

def condition_matches(
    condition: Any,
    values: dict[str, Any],
) -> bool:
    """Evaluate a template field visibility condition."""
    if not condition:
        return True

    normalized_condition = condition
    if isinstance(normalized_condition, str):
        if "=" not in normalized_condition:
            return True
        field_id, expected = normalized_condition.split("=", 1)
        normalized_condition = {
            "field": field_id.strip(),
            "equals": expected.strip(),
        }

    if not isinstance(normalized_condition, dict):
        return True

    source_id = str(
        normalized_condition.get("field", "")
    ).strip()
    actual = values.get(source_id)

    if "equals" in normalized_condition:
        expected = normalized_condition.get("equals")
        if isinstance(actual, bool) and not isinstance(expected, bool):
            expected = str(expected).casefold() in {
                "1",
                "true",
                "yes",
                "sim",
                "checked",
            }
        return (
            actual == expected
            or str(actual).casefold() == str(expected).casefold()
        )

    if "not_equals" in normalized_condition:
        expected = normalized_condition.get("not_equals")
        return not (
            actual == expected
            or str(actual).casefold() == str(expected).casefold()
        )

    return bool(actual) if normalized_condition.get("truthy") else True
