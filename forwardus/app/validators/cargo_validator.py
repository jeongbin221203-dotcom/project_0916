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

# 포장 유형. 해상·항공에서 쓸 수 있는 것이 다르고 주의할 점도 달라
# modes와 안내 문구를 함께 둡니다.
PACKAGE_TYPE_INFO = {
    "carton": {
        "label": "Carton (CTN) · 종이 상자",
        "modes": ("SEA", "AIR"),
        "note": "가장 많이 쓰는 포장입니다. 항공은 상자째 ULD에 싣습니다.",
    },
    "pallet": {
        "label": "Pallet (PLT) · 팔레트",
        "modes": ("SEA", "AIR"),
        "note": "목재 팔레트는 수출 전 소독(IPPC 마크)이 필요합니다. "
                "항공은 팔레트 높이가 낮은 화물기 규격(보통 160cm 이하)에 맞아야 합니다.",
    },
    "wooden_crate": {
        "label": "Wooden Crate (CRT) · 나무 상자",
        "modes": ("SEA", "AIR"),
        "note": "목재 포장재는 수출 전 소독(IPPC 마크)이 필요합니다. "
                "무거워서 항공에서는 운임이 크게 오릅니다.",
    },
    "drum": {
        "label": "Drum (DRM) · 드럼",
        "modes": ("SEA", "AIR"),
        "note": "액체·분말에 씁니다. 위험물이면 해상은 IMDG, 항공은 IATA 규정을 따르며 "
                "항공은 적재 가능 수량이 훨씬 적습니다.",
    },
    "flexible_bag": {
        "label": "Flexible Bag (BAG) · 톤백",
        "modes": ("SEA",),
        "note": "곡물·수지 같은 벌크 화물용입니다. 형태가 일정하지 않아 항공에는 쓰지 않습니다.",
    },
    "uld": {
        "label": "ULD · 항공 단위탑재용기",
        "modes": ("AIR",),
        "note": "항공사가 주는 컨테이너·팔레트에 직접 싣는 방식입니다. "
                "기종마다 규격이 달라 항공사에 확인해야 합니다.",
    },
    "bulk": {
        "label": "Bulk · 무포장 산적",
        "modes": ("SEA",),
        "note": "포장 없이 선창에 바로 싣습니다. 컨테이너가 아닌 벌크선을 씁니다.",
    },
}

PACKAGE_TYPES = {key: info["label"] for key, info in PACKAGE_TYPE_INFO.items()}


def package_types_for(transport_mode: str) -> dict:
    """운송 모드에서 쓸 수 있는 포장 유형만 골라 돌려줍니다."""

    mode = (transport_mode or "SEA").upper()
    return {key: info for key, info in PACKAGE_TYPE_INFO.items() if mode in info["modes"]}

PACKAGE_UNITS = {
    "carton": "CTN", "pallet": "PLT", "wooden_crate": "CRT", "drum": "DRM",
    "flexible_bag": "BAG", "uld": "ULD", "bulk": "BLK",
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
