from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def digits_only(value: Any) -> str:
    return re.sub(r"\D+", "", str(value or ""))


def decimal_from_localized(value: Any) -> Decimal:
    text = str(value or "").strip().replace("R$", "").replace("%", "").strip()
    if not text:
        return Decimal("0")
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    else:
        text = text.replace(" ", "")
    return Decimal(text)


def format_cnpj(value: Any) -> str:
    digits = digits_only(value)[:14]
    if len(digits) <= 2:
        return digits
    if len(digits) <= 5:
        return f"{digits[:2]}.{digits[2:]}"
    if len(digits) <= 8:
        return f"{digits[:2]}.{digits[2:5]}.{digits[5:]}"
    if len(digits) <= 12:
        return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:]}"
    return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"


def format_cpf(value: Any) -> str:
    digits = digits_only(value)[:11]
    if len(digits) <= 3:
        return digits
    if len(digits) <= 6:
        return f"{digits[:3]}.{digits[3:]}"
    if len(digits) <= 9:
        return f"{digits[:3]}.{digits[3:6]}.{digits[6:]}"
    return f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}"


def format_cep(value: Any) -> str:
    digits = digits_only(value)[:8]
    return f"{digits[:5]}-{digits[5:]}" if len(digits) > 5 else digits


def format_phone(value: Any) -> str:
    digits = digits_only(value)[:11]
    if len(digits) <= 2:
        return digits
    if len(digits) <= 6:
        return f"({digits[:2]}) {digits[2:]}"
    if len(digits) <= 10:
        return f"({digits[:2]}) {digits[2:6]}-{digits[6:]}"
    return f"({digits[:2]}) {digits[2:7]}-{digits[7:]}"


def format_currency(value: Any) -> str:
    digits = digits_only(value)
    if not digits:
        return ""
    decimal_value = Decimal(digits) / Decimal("100")
    formatted = f"{decimal_value:,.2f}"
    formatted = formatted.replace(",", "_").replace(".", ",").replace("_", ".")
    return f"R$ {formatted}"


def format_decimal(value: Any, places: int = 2) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        number = decimal_from_localized(text)
    except InvalidOperation:
        filtered = re.sub(r"[^0-9,.-]", "", text)
        try:
            number = decimal_from_localized(filtered)
        except InvalidOperation:
            return text
    pattern = f"{{:,.{max(0, places)}f}}"
    formatted = pattern.format(number)
    return formatted.replace(",", "_").replace(".", ",").replace("_", ".")


def format_percentage(value: Any) -> str:
    text = str(value or "").replace("%", "").strip()
    text = re.sub(r"[^0-9,.-]", "", text)
    if not text:
        return ""
    if "," in text:
        integer_part, decimal_part = text.split(",", 1)
    elif "." in text:
        integer_part, decimal_part = text.split(".", 1)
    else:
        integer_part, decimal_part = text, ""
    integer_digits = digits_only(integer_part) or "0"
    integer_digits = str(int(integer_digits))
    decimal_digits = digits_only(decimal_part)[:2]
    formatted = integer_digits
    if decimal_digits:
        formatted += f",{decimal_digits}"
    return f"{formatted}%"


def validate_cnpj(value: Any) -> bool:
    digits = digits_only(value)
    if len(digits) != 14 or len(set(digits)) == 1:
        return False

    def digit(base: str, weights: list[int]) -> str:
        total = sum(int(number) * weight for number, weight in zip(base, weights))
        remainder = total % 11
        return "0" if remainder < 2 else str(11 - remainder)

    first = digit(digits[:12], [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    second = digit(digits[:12] + first, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    return digits[-2:] == first + second


def validate_cpf(value: Any) -> bool:
    digits = digits_only(value)
    if len(digits) != 11 or len(set(digits)) == 1:
        return False
    total_1 = sum(int(digits[index]) * (10 - index) for index in range(9))
    first = (total_1 * 10) % 11
    first = 0 if first == 10 else first
    total_2 = sum(int(digits[index]) * (11 - index) for index in range(10))
    second = (total_2 * 10) % 11
    second = 0 if second == 10 else second
    return digits[-2:] == f"{first}{second}"
