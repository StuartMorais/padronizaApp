from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable
import re

from app.domain.field_types import FieldType


class TagKind(str, Enum):
    FIELD = "field"
    REPEAT = "repeat"
    ROW_NUMBER = "row_number"


@dataclass(frozen=True)
class TagDefinition:
    kind: TagKind
    field_id: str
    field_type: str = FieldType.TEXT.value
    options: tuple[Any, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    default_value: str | None = None


PLACEHOLDER_PATTERN = re.compile(r"\{\{([^{}]+)\}\}")

ROW_NUMBER_IDS = frozenset({
    "row.number",
    "row.index",
    "linha.numero",
    "linha.número",
})

TAG_PREFIXES = frozenset({
    "checkbox",
    "currency_words",
    "date",
    "dropdown",
    "single_choice",
    "default_or_text",
    "repeat",
    "repeat_list",
})


def parse_tag(
    raw_value: str,
    *,
    clean_options: Callable[[Any], list[Any]] | None = None,
    infer_type: Callable[[str], str] | None = None,
    strict: bool = True,
) -> TagDefinition:
    """Parse Padroniza's authoritative ``{{...}}`` tag syntax once.

    Scanner and generator both use this function so supported tag syntax cannot
    silently drift between reading and writing paths.
    """

    value = str(raw_value or "").strip()
    lowered = value.casefold()
    option_cleaner = clean_options or (lambda items: list(items or []))

    if lowered.startswith("repeat:"):
        field_id = value.split(":", 1)[1].strip()
        if not field_id and strict:
            raise ValueError("O marcador repeat não possui ID de tabela.")
        return TagDefinition(TagKind.REPEAT, field_id, metadata={"tag_type": "repeat"})

    if lowered in ROW_NUMBER_IDS:
        return TagDefinition(TagKind.ROW_NUMBER, value, metadata={"tag_type": "row_number"})

    if ":" not in value:
        return TagDefinition(
            TagKind.FIELD,
            value,
            (infer_type(value) if infer_type else FieldType.TEXT.value),
        )

    prefix, definition = value.split(":", 1)
    prefix = prefix.strip().casefold()
    if prefix not in TAG_PREFIXES:
        # Unknown prefixes remain ordinary field IDs for backwards
        # compatibility. Validation can still flag malformed identifiers.
        return TagDefinition(
            TagKind.FIELD,
            value,
            (infer_type(value) if infer_type else FieldType.TEXT.value),
        )

    if prefix == "checkbox":
        field_id = definition.strip()
        if not field_id and strict:
            raise ValueError("Um marcador de caixa de seleção não possui ID de campo.")
        return TagDefinition(
            TagKind.FIELD,
            field_id,
            FieldType.CHECKBOX.value,
            metadata={"tag_type": "checkbox"},
        )

    if prefix == "date":
        field_id = definition.strip()
        if not field_id and strict:
            raise ValueError("Um marcador de data não possui ID de campo.")
        return TagDefinition(
            TagKind.FIELD,
            field_id,
            FieldType.DATE.value,
            metadata={"tag_type": "date"},
        )

    if prefix == "currency_words":
        field_id = definition.strip()
        if not field_id and strict:
            raise ValueError("Um marcador de valor por extenso não possui ID de campo.")
        return TagDefinition(
            TagKind.FIELD,
            field_id,
            FieldType.CURRENCY.value,
            metadata={"render": "currency_words"},
        )

    if prefix == "repeat_list":
        parts = [part.strip() for part in definition.split("|")]
        field_id = parts[0] if parts else ""
        if not field_id and strict:
            raise ValueError("Um marcador de lista repetível não possui ID de campo.")
        list_style = (parts[1] if len(parts) > 1 else "bullet").casefold() or "bullet"
        if list_style not in {"bullet", "numbered", "plain"}:
            list_style = "bullet"
        punctuation = (parts[2] if len(parts) > 2 else "semicolon").casefold() or "semicolon"
        if punctuation not in {"semicolon", "period", "none"}:
            punctuation = "semicolon"
        return TagDefinition(
            TagKind.FIELD,
            field_id,
            FieldType.REPEATABLE_LIST.value,
            metadata={
                "tag_type": "repeat_list",
                "list_style": list_style,
                "list_punctuation": punctuation,
                "minimum_items": 1,
            },
        )

    parts = [part.strip() for part in definition.split("|")]
    field_id = parts[0] if parts else ""
    if not field_id and strict:
        label = {
            "dropdown": "lista suspensa",
            "single_choice": "escolha única",
            "default_or_text": "texto com valor padrão",
        }.get(prefix, "marcador")
        raise ValueError(f"Um marcador de {label} não possui ID de campo.")

    if prefix == "default_or_text":
        default_value = "|".join(parts[1:]).strip()
        if not default_value and strict:
            raise ValueError(
                f"O campo com valor padrão '{field_id}' não contém texto padrão.\n\n"
                "Use: {{default_or_text:campo.id|Texto padrão}}"
            )
        return TagDefinition(
            TagKind.FIELD,
            field_id,
            FieldType.MULTILINE.value,
            metadata={"tag_type": "default_or_text", "default_value": default_value},
            default_value=default_value,
        )

    options = tuple(option_cleaner(parts[1:]))
    if prefix == "single_choice":
        if len(options) < 2 and strict:
            raise ValueError(
                f"A escolha única '{field_id}' precisa de pelo menos duas opções.\n\n"
                "Use: {{single_choice:campo.id|Opção A|Opção B}}\n"
                "Para textos longos: {{single_choice:campo.id|Título curto => Texto completo}}"
            )
        group = f"single_choice_{field_id}"
        return TagDefinition(
            TagKind.FIELD,
            field_id,
            FieldType.DROPDOWN.value,
            options,
            {
                "layout": "choice",
                "layout_group": group,
                "group": group,
                "selection": "single",
                "choice_required": True,
                "tag_type": "single_choice",
            },
        )

    if not options and strict:
        raise ValueError(
            f"A lista suspensa '{field_id}' não contém opções.\n\n"
            "Use: {{dropdown:campo.id|Opção A|Opção B}}\n"
            "Para textos longos: {{dropdown:campo.id|Título curto => Texto completo}}"
        )
    return TagDefinition(
        TagKind.FIELD,
        field_id,
        FieldType.DROPDOWN.value,
        options,
        {"tag_type": "dropdown"},
    )
