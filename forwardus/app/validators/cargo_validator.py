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

# 가격 단위. 단가가 "무엇 하나당" 값인지입니다.
#
# 오퍼시트와 L/C는 대개 낱개(PCS)나 무게(KG)로 값을 매깁니다. 우리 품목 줄의
# quantity는 포장 개수라, 이 칸 없이 단가를 계산하면 "100 CTN × 64.00"처럼
# 오퍼시트(2,000 PCS × 3.20)와 다른 단가가 찍힙니다. 합계는 같아도 L/C와
# 단가가 다르면 은행에서 서류 불일치로 돌아옵니다.
#
# 목록에 있는 것만 받습니다. AI나 사람이 적은 낯선 단위를 그대로 서류에
# 찍지 않습니다. 모르는 단위면 사람에게 다시 묻습니다.
PRICE_UNITS = {
    "PCS": "낱개 (pieces)", "EA": "개 (each)", "SET": "세트", "PR": "켤레 (pair)",
    "DZ": "다스 (12개)", "KG": "킬로그램", "G": "그램", "MT": "톤 (metric ton)",
    "L": "리터", "M": "미터", "M2": "제곱미터", "M3": "세제곱미터",
    "ROLL": "롤", "SHEET": "장", "BOX": "박스", "CTN": "카톤", "BTL": "병",
}
# 서류마다 같은 단위를 다르게 적습니다. 모두 위 이름 하나로 맞춥니다.
PRICE_UNIT_ALIASES = {
    "PC": "PCS", "PIECE": "PCS", "PIECES": "PCS", "PCE": "PCS",
    "EACH": "EA", "SETS": "SET", "PAIR": "PR", "PAIRS": "PR", "PRS": "PR",
    "DOZ": "DZ", "DOZEN": "DZ", "DOZENS": "DZ",
    "KGS": "KG", "KILOGRAM": "KG", "KILOGRAMS": "KG", "GRAM": "G", "GRAMS": "G",
    "TON": "MT", "TONS": "MT", "TONNE": "MT", "MTS": "MT",
    "LTR": "L", "LITER": "L", "LITRE": "L", "LITERS": "L",
    "MTR": "M", "METER": "M", "METRE": "M", "SQM": "M2", "CBM": "M3",
    "ROLLS": "ROLL", "SHEETS": "SHEET", "BOXES": "BOX", "CARTON": "CTN", "CARTONS": "CTN",
    "BOTTLE": "BTL", "BOTTLES": "BTL",
    # 한글 서류(견적서)에 흔한 단위. 뜻이 하나로 정해지는 것만 둡니다.
    # ("상자"는 박스인지 카톤인지 서류마다 달라 넣지 않았습니다. 사람에게 묻습니다)
    "개": "PCS", "세트": "SET", "켤레": "PR", "다스": "DZ", "박스": "BOX", "병": "BTL",
    "장": "SHEET", "롤": "ROLL", "킬로그램": "KG", "킬로": "KG", "그램": "G", "톤": "MT",
    "리터": "L", "미터": "M",
}
MAX_UNIT_QUANTITY = 1_000_000_000


def priced_by_units(cargo) -> bool:
    """단가를 낱개(PCS·KG 등)로 매긴 품목인지. 아니면 포장 개수가 단가의 기준입니다.

    저장된 Cargo와 초안의 임시 객체 모두 받습니다. 속성만 봅니다.
    """

    return (getattr(cargo, "unit_quantity", None) is not None
            and bool(getattr(cargo, "price_unit", "")))


def price_unit_of(value: Any) -> str:
    """적힌 단위를 우리 목록의 이름으로. 모르는 단위면 빈 값입니다."""

    code = str(value or "").strip().upper().rstrip(".")
    code = PRICE_UNIT_ALIASES.get(code, code)
    return code if code in PRICE_UNITS else ""


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

    dangerous = validate_dangerous_goods(payload, strict=strict)
    length = parse_number(payload.get("length_cm"), "가로(Length)", max_value=MAX_DIMENSION_CM, field="length_cm")
    width = parse_number(payload.get("width_cm"), "세로(Width)", max_value=MAX_DIMENSION_CM, field="width_cm")
    height = parse_number(payload.get("height_cm"), "높이(Height)", max_value=MAX_DIMENSION_CM, field="height_cm")
    units = _validate_units(payload, strict=strict)
    quantity = _package_quantity(payload, units, strict=strict)
    weight = parse_number(
        payload.get("weight_per_package_kg"),
        "포장당 중량(Weight)",
        max_value=MAX_WEIGHT_PER_PACKAGE_KG,
        field="weight_per_package_kg",
    )

    return {
        **dangerous,
        "length_cm": length,
        "width_cm": width,
        "height_cm": height,
        "quantity": quantity,
        "weight_per_package_kg": weight,
        "package_type": package_type,
        "unit_quantity": units["unit_quantity"],
        "price_unit": units["price_unit"],
        "units_per_package": units["units_per_package"],
        "units_warning": units["units_warning"],
        # 품목별 단가·금액은 선택입니다. 둘 중 하나만 적어도 나머지를 채워 줍니다.
        **_validate_money(payload, quantity, units["unit_quantity"]),
    }


BOX_FIELDS = ("length_cm", "width_cm", "height_cm", "weight_per_package_kg")


def has_box(payload: dict) -> bool:
    """상자 크기와 무게가 모두 적혀 있는지. 없으면 부피·중량을 계산할 수 없습니다."""

    return isinstance(payload, dict) and not any(_blank(payload.get(key)) for key in BOX_FIELDS)


def validate_commercial_line(payload: dict) -> dict:
    """상자 크기·무게 없이, 송장에 필요한 것만 확인합니다.

    오퍼시트에는 상자 크기가 거의 없습니다. 그래도 견적송장·상업송장은
    품명·수량·단가·금액만 있으면 그릴 수 있습니다. 부피·중량은 비워 두고
    운송 계획에서 크기를 적으면 채워집니다.

    포장 개수도 모를 수 있습니다(오퍼시트에 "20 PCS/CTN"이 없을 때).
    그러면 None이고, 지어내지 않습니다. 포장명세서에서 채웁니다.
    수량 × 단가 = 금액 검사는 여기서도 똑같이 합니다.
    """

    if not isinstance(payload, dict):
        raise ValidationError("화물 정보를 입력해주세요.", "cargo")
    package_type = str(payload.get("package_type") or "carton")
    if package_type not in PACKAGE_TYPES:
        raise ValidationError("포장 유형을 확인해주세요.", "package_type")

    units = _validate_units(payload, strict=True)
    if _blank(payload.get("quantity")) and units["derived_quantity"] is None:
        quantity = None
    else:
        quantity = _package_quantity(payload, units, strict=True)
    return {
        **validate_dangerous_goods(payload, strict=False),
        "package_type": package_type,
        "quantity": quantity,
        "unit_quantity": units["unit_quantity"],
        "price_unit": units["price_unit"],
        "units_per_package": units["units_per_package"],
        "units_warning": units["units_warning"],
        **_validate_money(payload, quantity or 0, units["unit_quantity"]),
    }


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _validate_units(payload: dict, *, strict: bool) -> dict:
    """낱개 수량 · 가격 단위 · 포장당 낱개 수.

    셋 다 선택입니다. 안 적으면 예전처럼 포장 개수가 단가의 기준입니다.
    적었으면 **단가는 낱개 수량 기준**이고, 포장 개수는 포장명세서에 씁니다.

    포장당 낱개 수까지 적었으면 포장 개수를 계산합니다. 다만 정확히
    나누어떨어질 때만입니다. 2,010개를 20개씩 담으면 100.5상자인데,
    이걸 반올림해 101상자로 적으면 마지막 상자에 몇 개가 들었는지
    서류가 거짓말을 하게 됩니다. 그럴 때는 멈추고 사람에게 묻습니다.
    """

    result = {"unit_quantity": None, "price_unit": "", "units_per_package": None,
              "units_warning": "", "derived_quantity": None}
    raw_quantity = payload.get("unit_quantity")
    raw_unit = payload.get("price_unit")
    raw_per = payload.get("units_per_package")
    if _blank(raw_quantity) and _blank(raw_unit) and _blank(raw_per):
        return result

    unit_quantity = None if _blank(raw_quantity) else parse_number(
        raw_quantity, "낱개 수량", max_value=MAX_UNIT_QUANTITY, field="unit_quantity")
    price_unit = price_unit_of(raw_unit)
    if not _blank(raw_unit) and not price_unit:
        raise ValidationError(f"가격 단위 '{str(raw_unit).strip()[:20]}'을(를) 알 수 없습니다. "
                              f"PCS · KG · SET 같은 단위로 적어 주세요.", "price_unit")
    if unit_quantity is not None and not price_unit:
        raise ValidationError("낱개 수량의 단위(PCS · KG · SET 등)를 적어 주세요.", "price_unit")
    if price_unit and unit_quantity is None:
        raise ValidationError(f"{price_unit} 기준 수량(낱개 수량)을 적어 주세요.", "unit_quantity")
    per = None if _blank(raw_per) else parse_number(
        raw_per, "포장당 낱개 수", max_value=MAX_UNIT_QUANTITY, field="units_per_package")

    result.update(unit_quantity=unit_quantity, price_unit=price_unit, units_per_package=per)
    if unit_quantity is not None and per:
        ratio = unit_quantity / per
        if abs(ratio - round(ratio)) > 1e-9 or round(ratio) < 1:
            message = (f"낱개 {unit_quantity:,g} ÷ 포장당 {per:,g} = {ratio:,.2f}로 "
                       f"나누어떨어지지 않습니다. 마지막 포장이 덜 찼다면 포장당 낱개 수를 "
                       f"비우고 포장 개수를 직접 적어 주세요.")
            if strict:
                raise ValidationError(message, "units_per_package")
            result["units_warning"] = message
        else:
            result["derived_quantity"] = int(round(ratio))
    return result


def _package_quantity(payload: dict, units: dict, *, strict: bool) -> int:
    """포장 개수. 안 적었으면 낱개 ÷ 포장당 낱개로 구하고, 적었으면 그 계산과 맞는지 봅니다."""

    derived = units["derived_quantity"]
    raw = payload.get("quantity")
    if _blank(raw) and derived is not None:
        raw = derived
    quantity = parse_integer(raw, "수량(Quantity)", max_value=MAX_QUANTITY, field="quantity")
    if derived is not None and quantity != derived:
        message = (f"포장 개수가 맞지 않습니다. 낱개 {units['unit_quantity']:,g} ÷ 포장당 "
                   f"{units['units_per_package']:,g} = {derived:,}개인데 {quantity:,}개로 적혀 있습니다.")
        if strict:
            raise ValidationError(message, "quantity")
        units["units_warning"] = message
    return quantity


def _validate_money(payload: dict, quantity: int, unit_quantity: float | None = None) -> dict:
    """단가와 금액. 한쪽만 있으면 수량으로 나머지를 구합니다.

    낱개 수량을 적었으면 그것이 단가의 기준이고, 아니면 포장 개수가 기준입니다.
    낱개 기준일 때는 셋(수량·단가·금액)이 정확히 맞아야 합니다. 서류에 찍히는
    단가가 L/C와 한 푼이라도 다르면 은행에서 돌아오기 때문입니다.
    """

    def optional(value, label, field):
        if _blank(value):
            return None
        return parse_number(value, label, max_value=MAX_INVOICE_VALUE, field=field)

    unit_price = optional(payload.get("unit_price"), "단가(Unit Price)", "unit_price")
    amount = optional(payload.get("amount"), "금액(Amount)", "amount")
    by_units = unit_quantity is not None
    basis = unit_quantity if by_units else quantity

    if amount is None and unit_price is not None and basis:
        amount = unit_price * basis
    elif unit_price is None and amount is not None and basis:
        unit_price = round(amount / basis, 4)
        # 낱개 기준에서 나누어떨어지지 않는 단가(100 ÷ 3 = 33.3333)는 지어내지 않습니다.
        # 33.3333 × 3 = 99.9999라 반올림하면 100처럼 보이지만, 송장에 찍힌 단가로
        # 되곱하면 금액이 안 나옵니다. 정확히 되곱해질 때만 채우고, 아니면 비워 둡니다.
        if by_units and abs(unit_price * basis - amount) > 1e-6:
            unit_price = None
    elif by_units and unit_price is not None and amount is not None:
        if round(unit_price * basis, 2) != round(amount, 2):
            raise ValidationError(
                f"수량 × 단가가 금액과 맞지 않습니다. {basis:,g} × {unit_price:,g} = "
                f"{unit_price * basis:,.2f} 인데 금액은 {amount:,.2f} 입니다.", "amount")
    # 금액은 줄 단위로 먼저 원 단위(소수 둘째 자리)까지 맞춥니다.
    # 그래야 송장에 적히는 품목 금액의 합과 총액이 어긋나지 않습니다.
    return {"unit_price": unit_price,
            "amount": None if amount is None else round(amount, 2)}
