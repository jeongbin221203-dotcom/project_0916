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

# 포장등급(Packing Group). 같은 급이라도 위험도가 갈리고 포장 기준이 달라집니다.
PACKING_GROUPS = {
    "I": "I · 위험성 큼",
    "II": "II · 위험성 보통",
    "III": "III · 위험성 낮음",
}

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
    if isinstance(value, str):
        # 화면이 천 단위 쉼표를 붙여 보여주므로 사람이 그대로 옮겨 적습니다.
        # (48,000.00 같은 값) 쉼표는 떼고 읽습니다.
        value = value.replace(",", "").replace(" ", "")
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


def validate_dangerous_goods(payload: dict, *, strict: bool = True) -> dict:
    """위험물 표시를 확인합니다. 체크했으면 UN번호와 급이 함께 있어야 합니다.

    `strict=False`는 입력하는 도중에 쓰는 모드입니다. 아직 UN번호를 안 적었다고
    해서 CBM·중량 계산까지 막으면 안 되므로, 오류 대신 `dg_warning`을 달아
    돌려주고 계산은 그대로 진행합니다. 저장할 때는 strict로 다시 확인합니다.
    """

    from app.processors.dangerous_goods import DG_CLASSES

    flag = payload.get("is_dangerous")
    is_dangerous = flag in (True, "true", "True", "on", "1", 1)
    if not is_dangerous:
        return {"is_dangerous": False, "un_number": "", "dg_class": "",
                "packing_group": "", "proper_shipping_name": "", "dg_warning": ""}

    # 정식운송품명(PSN)은 위험물 신고서·라벨에 그대로 쓰는 공식 품명입니다.
    psn = str(payload.get("proper_shipping_name") or "").strip()[:200]

    def problem(message: str, field: str) -> dict:
        if strict:
            raise ValidationError(message, field)
        return {"is_dangerous": True,
                "un_number": str(payload.get("un_number") or "").strip().upper(),
                "dg_class": str(payload.get("dg_class") or "").strip(),
                "packing_group": "", "proper_shipping_name": psn, "dg_warning": message}

    # UN번호는 "UN1234" 또는 숫자 네 자리입니다. 모든 위험물 서류의 기준이라 필수입니다.
    raw = str(payload.get("un_number") or "").strip().upper().replace(" ", "")
    digits = raw[2:] if raw.startswith("UN") else raw
    if not (digits.isdigit() and len(digits) == 4):
        return problem("UN번호는 네 자리 숫자입니다. (예: UN1263)", "un_number")

    dg_class = str(payload.get("dg_class") or "").strip()
    if dg_class not in DG_CLASSES:
        return problem("위험물 등급을 골라주세요.", "dg_class")

    # 포장등급(PG)은 위험도입니다. I 큼 / II 보통 / III 낮음. 급에 따라 없는 것도 있습니다.
    packing_group = str(payload.get("packing_group") or "").strip().upper()
    if packing_group and packing_group not in PACKING_GROUPS:
        return problem("포장등급은 I·II·III 중 하나입니다.", "packing_group")

    if not psn:
        return problem("정식운송품명(Proper Shipping Name)을 적어주세요. MSDS 14번 항목에 있습니다.",
                       "proper_shipping_name")

    return {"is_dangerous": True, "un_number": f"UN{digits}", "dg_class": dg_class,
            "packing_group": packing_group, "proper_shipping_name": psn, "dg_warning": ""}


def validate_cargo_input(payload: dict, *, strict: bool = True) -> dict:
    """Validate raw cargo dimensions and return typed values."""

    if not isinstance(payload, dict):
        raise ValidationError("화물 정보를 입력해주세요.", "cargo")
    package_type = str(payload.get("package_type") or "carton")
    if package_type not in PACKAGE_TYPES:
        raise ValidationError("포장 유형을 확인해주세요.", "package_type")

    return {
        **validate_dangerous_goods(payload, strict=strict),
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
        # 품목별 단가·금액은 선택입니다. 둘 중 하나만 적어도 나머지를 채워 줍니다.
        **_validate_money(payload),
    }


def _validate_money(payload: dict) -> dict:
    """단가와 금액. 한쪽만 있으면 수량으로 나머지를 구합니다."""

    def optional(value, label, field):
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        return parse_number(value, label, max_value=MAX_INVOICE_VALUE, field=field)

    unit_price = optional(payload.get("unit_price"), "단가(Unit Price)", "unit_price")
    amount = optional(payload.get("amount"), "금액(Amount)", "amount")
    try:
        quantity = parse_integer(payload.get("quantity"), "수량(Quantity)",
                                 max_value=MAX_QUANTITY, field="quantity")
    except ValidationError:
        quantity = 0
    if amount is None and unit_price is not None and quantity:
        amount = round(unit_price * quantity, 2)
    elif unit_price is None and amount is not None and quantity:
        unit_price = round(amount / quantity, 4)
    return {"unit_price": unit_price, "amount": amount}
