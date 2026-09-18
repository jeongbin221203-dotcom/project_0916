"""Cargo measurement and freight unit calculations."""

from __future__ import annotations

import math
from typing import Any


class CargoValidationError(ValueError):
    """Raised when required cargo input is invalid."""


def parse_positive_number(value: Any, field_name: str, *, allow_zero: bool = False) -> float:
    """Validate and convert a finite positive numeric value."""

    if isinstance(value, bool) or value is None or value == "":
        raise CargoValidationError(f"{field_name} 값을 확인해주세요.")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise CargoValidationError(f"{field_name}에는 숫자만 입력할 수 있습니다.") from exc
    if not math.isfinite(number):
        raise CargoValidationError(f"{field_name}에는 유한한 숫자만 입력할 수 있습니다.")
    if number < 0 or (number == 0 and not allow_zero):
        raise CargoValidationError(f"{field_name}은(는) 0보다 커야 합니다.")
    return number


def parse_positive_integer(value: Any, field_name: str) -> int:
    """Validate and convert a strictly positive integer."""

    number = parse_positive_number(value, field_name)
    if not number.is_integer():
        raise CargoValidationError(f"{field_name}에는 양의 정수만 입력할 수 있습니다.")
    return int(number)


def calculate_cargo_metrics(payload: dict) -> dict:
    """Calculate CBM, weight, revenue ton, and air chargeable weight."""

    length_cm = parse_positive_number(payload.get("length_cm"), "가로")
    width_cm = parse_positive_number(payload.get("width_cm"), "세로")
    height_cm = parse_positive_number(payload.get("height_cm"), "높이")
    box_count = parse_positive_integer(payload.get("box_count"), "수량")
    weight_per_box_kg = parse_positive_number(payload.get("weight_per_box_kg"), "개당 중량")

    total_cbm = (length_cm * width_cm * height_cm / 1_000_000) * box_count
    total_weight_kg = weight_per_box_kg * box_count
    revenue_ton = max(1.0, total_cbm, total_weight_kg / 1000)
    chargeable_weight_kg = max(total_weight_kg, total_cbm * 166.67)

    return {
        "total_cbm": round(total_cbm, 4),
        "total_weight_kg": round(total_weight_kg, 2),
        "revenue_ton": round(revenue_ton, 2),
        "chargeable_weight_kg": round(chargeable_weight_kg, 2),
    }

