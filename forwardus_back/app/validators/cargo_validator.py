"""Numeric and cargo input validation."""

from __future__ import annotations

import math
from typing import Any

from app.validators import ValidationError

# Upper bounds that reject clearly abnormal input.
MAX_DIMENSION_CM = 2_000
MAX_QUANTITY = 100_000
MAX_WEIGHT_PER_PACKAGE_KG = 40_000
MAX_INVOICE_VALUE = 1_000_000_000

PACKAGE_TYPES = {
    "carton": "Carton (CTN)",
    "pallet": "Pallet (PLT)",
    "wooden_crate": "Wooden Crate (CRT)",
    "drum": "Drum (DRM)",
    "flexible_bag": "Flexible Bag (BAG)",
}

PACKAGE_UNITS = {
    "carton": "CTN",
    "pallet": "PLT",
    "wooden_crate": "CRT",
    "drum": "DRM",
    "flexible_bag": "BAG",
}


def parse_number(
    value: Any,
    field_name: str,
    *,
    allow_zero: bool = False,
    max_value: float | None = None,
    field: str | None = None,
) -> float:
    """Validate and convert a finite, non-negative number."""

    if isinstance(value, bool) or value is None or (isinstance(value, str) and not value.strip()):
        raise ValidationError(f"{field_name} 값을 입력해주세요.", field)
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{field_name}에는 숫자만 입력할 수 있습니다.", field) from exc
    if not math.isfinite(number):
        raise ValidationError(f"{field_name}에는 유한한 숫자만 입력할 수 있습니다.", field)
    if number < 0 or (number == 0 and not allow_zero):
        raise ValidationError(f"{field_name}은(는) 0보다 커야 합니다.", field)
    if max_value is not None and number > max_value:
        raise ValidationError(f"{field_name} 값이 허용 범위({max_value:,.0f})를 초과했습니다.", field)
    return number


def parse_integer(value: Any, field_name: str, *, max_value: float | None = None, field: str | None = None) -> int:
    """Validate and convert a strictly positive integer."""

    number = parse_number(value, field_name, max_value=max_value, field=field)
    if not number.is_integer():
        raise ValidationError(f"{field_name}에는 양의 정수만 입력할 수 있습니다.", field)
    return int(number)


def parse_optional_number(value: Any, field_name: str, *, max_value: float | None = None, field: str | None = None) -> float | None:
    """Return None for empty input, otherwise a validated positive number."""

    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return parse_number(value, field_name, max_value=max_value, field=field)


def validate_cargo_input(payload: dict) -> dict:
    """Validate raw cargo dimensions and return typed values."""

    package_type = str(payload.get("package_type") or "carton")
    if package_type not in PACKAGE_TYPES:
        raise ValidationError("포장 유형을 확인해주세요.", "package_type")

    return {
        "length_cm": parse_number(payload.get("length_cm"), "가로(Length)", max_value=MAX_DIMENSION_CM, field="length_cm"),
        "width_cm": parse_number(payload.get("width_cm"), "세로(Width)", max_value=MAX_DIMENSION_CM, field="width_cm"),
        "height_cm": parse_number(payload.get("height_cm"), "높이(Height)", max_value=MAX_DIMENSION_CM, field="height_cm"),
        "quantity": parse_integer(payload.get("quantity"), "수량(Quantity)", max_value=MAX_QUANTITY, field="quantity"),
        "weight_per_package_kg": parse_number(
            payload.get("weight_per_package_kg"),
            "포장당 중량(Weight)",
            max_value=MAX_WEIGHT_PER_PACKAGE_KG,
            field="weight_per_package_kg",
        ),
        "package_type": package_type,
    }
