"""Cargo measurement and freight unit calculations."""

from __future__ import annotations

import math
from decimal import Decimal, ROUND_HALF_UP

from app.validators import ValidationError
from app.validators.cargo_validator import validate_cargo_input

# 항공 용적중량 환산 계수. **나누어 씁니다 — 반올림한 값을 쓰지 않습니다.**
#
# 업계 기준은 "가로×세로×높이(cm) ÷ 6,000"입니다. 1CBM을 kg으로 바꾸면
# 1,000,000 ÷ 6,000 = 166.666… 인데, 예전에는 166.67로 적어 두었습니다.
# 항공 운임은 **kg당** 매겨지므로 이 0.002%가 그대로 돈이 됩니다.
#   354 CBM  →  59,001.18 kg (166.67)  vs  59,000.00 kg (정확)   +1.18 kg
#   9,999박스 큰 건  →  +78 kg
# 늘 **위로** 치우쳐 청구가 부풀었습니다. 나누기로 바꿉니다. (2026-09-26)
#
# 항공사가 다른 계수를 쓰면 volume_factor 인자로 넘깁니다.
AIR_VOLUME_DIVISOR_CM3 = 6_000
AIR_VOLUME_FACTOR = 1_000_000 / AIR_VOLUME_DIVISOR_CM3
# 셈할 때 쓰는 계수는 Decimal 로 둡니다. float 로 두면 166.66666666666666 까지만
# 남아, 정확히 0.005kg 인 자리가 0.00 으로 떨어집니다. (AIR_VOLUME_FACTOR 는
# 화면·다른 모듈이 쓰는 float 값이라 그대로 둡니다)
AIR_VOLUME_FACTOR_EXACT = Decimal(1_000_000) / Decimal(AIR_VOLUME_DIVISOR_CM3)

# Minimum billable unit for LCL freight.
LCL_MIN_REVENUE_TON = 1.0

# Practical loadable volume and payload per container type.
CONTAINER_SPECS = {
    "20GP": {"max_cbm": 28.0, "max_weight_kg": 21_000},
    "40GP": {"max_cbm": 58.0, "max_weight_kg": 26_000},
    "40HC": {"max_cbm": 68.0, "max_weight_kg": 26_000},
}
DEFAULT_CONTAINER_TYPE = "40GP"


def _dec(value) -> Decimal:
    """사람이 적은 숫자를 그대로 Decimal 로. str() 로 2진수 오차를 털어 냅니다."""

    return Decimal(str(value))


def _fix(value, digits: int) -> float:
    """소수 자리를 사사오입으로 맞춥니다 — 계산기로 셈한 값과 같게."""

    return float(_dec(value).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP))


def round_volume(value: float, digits: int = 4) -> float:
    """부피를 반올림하되, 0보다 큰 값이 0이 되지는 않게 합니다.

    3cm 정육면체는 0.000027 CBM입니다. 소수 넷째 자리에서 반올림하면 0이 되고,
    그러면 "부피가 없는 화물"이 되어 운임 기준이 서지 않습니다.
    작은 화물도 실제로 자리를 차지합니다.
    """

    # **float 의 round() 를 쓰지 않습니다.** 30×45×37.5cm 상자 480개는 정확히
    # 24.30000 CBM 인데, 2진수로는 딱 떨어지지 않아 자리가 정확히 절반인 화물이
    # 아래로 떨어집니다. 1,000회를 맞대어 보니 4%에서 마지막 자리가 하나 어긋났습니다.
    # CBM 은 운임의 기준이라 손으로 셈한 값과 달라지면 포워더와 말이 갈립니다.
    # 사사오입(ROUND_HALF_UP)은 사람이 계산기로 셈하는 방식과 같습니다. (2026-09-26)
    exact = _dec(value)
    rounded = exact.quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
    if rounded == 0 and exact > 0:
        deep = exact.quantize(Decimal(1).scaleb(-9), rounding=ROUND_HALF_UP)
        return float(deep) or value
    return float(rounded)


# 1CBM당 몇 kg이면 그것이 무슨 물질인지. 숫자만 들이밀면 사람은 판단을 못 합니다.
# "1CBM당 19,200kg"보다 "금만큼 무겁습니다"가 훨씬 빨리 와닿습니다.
DENSITY_MARKS = (
    (1_000, "물"),
    (2_700, "알루미늄"),
    (7_850, "강철"),
    (11_340, "납"),
    (19_250, "텅스텐"),
    (19_300, "금"),
    (21_450, "백금"),
    (22_590, "오스뮴"),
)

# 오스뮴은 지구에서 가장 무거운 물질입니다. 1CBM당 22,590kg.
# 이보다 무거운 화물은 지구에 존재하지 않으므로, 넘으면 적은 값이 틀린 것입니다.
HEAVIEST_ON_EARTH = 22_590
HEAVIEST_NAME = "오스뮴"

# 물보다 무거우면(1,500) 흔치 않아 한 번 짚고, 강철보다 무거우면(7,850) 중금속이
# 아닌 한 잘못 적은 값입니다. 다만 **막지 않습니다.** 금괴·텅스텐·납괴는 실제로
# 오가는 화물이고, 강철보다 무겁다고 해서 없는 화물이 되는 것은 아닙니다.
# 무엇을 보내는지는 보낸 사람이 압니다. 우리는 값이 무엇쯤 되는지만 알려 줍니다.
HEAVY_DENSITY = 1_500
HEAVY_METAL_DENSITY = 7_850


def density_material(density: float) -> str:
    """그 밀도가 어느 물질쯤 되는지. 가장 가까운 아래쪽 물질 이름입니다."""

    name = ""
    for mark, material in DENSITY_MARKS:
        if density >= mark:
            name = material
    return name


def density_suspect(total_cbm: float, total_weight_kg: float) -> bool:
    """중금속이 아니면 잘못 적었다고 볼 만한 값인지.

    물보다 무거운 정도(1,500)는 흔합니다. 집계 화면에서 그것까지 "확인 필요"로
    세면 정작 봐야 할 건이 묻힙니다. 강철보다 무거운 것만 셉니다.
    """

    if total_cbm <= 0 or total_weight_kg <= 0:
        return False
    return total_weight_kg / total_cbm >= HEAVY_METAL_DENSITY


def density_note(total_cbm: float, total_weight_kg: float) -> str:
    """부피에 견주어 중량이 말이 되는지. 이상하면 왜 이상한지 적어 돌려줍니다."""

    if total_cbm <= 0 or total_weight_kg <= 0:
        return ""
    density = total_weight_kg / total_cbm
    if density < HEAVY_DENSITY:
        return ""

    measure = (f"적어 주신 값은 1CBM당 {density:,.0f}kg입니다 "
               f"(부피 {total_cbm:,.3f}CBM · 중량 {total_weight_kg:,.0f}kg).")

    # 오스뮴보다 무거운 것은 지구에 없습니다. 여기만은 틀렸다고 말해도 됩니다.
    if density > HEAVIEST_ON_EARTH:
        return (f"{measure} 지구에서 가장 무거운 물질인 {HEAVIEST_NAME}이 1CBM당 "
                f"{HEAVIEST_ON_EARTH:,}kg입니다. 이보다 무거운 화물은 없으니 "
                "값이 잘못 적혔습니다. 포장당 중량 칸에 전체 중량을 적었거나, "
                "상자 크기를 잘못 적지 않았는지 확인해주세요.")

    # 강철~오스뮴 사이. 중금속이면 맞는 값입니다. 우리가 정할 일이 아닙니다.
    if density >= HEAVY_METAL_DENSITY:
        return (f"{measure} {density_material(density)}만큼 무겁습니다. "
                f"금·텅스텐·납 같은 중금속을 상자에 꽉 채웠다면 나올 수 있는 값입니다. "
                "그런 화물이 맞으면 그대로 두세요. 아니라면 포장당 중량 칸에 "
                "전체 중량을 적지 않았는지 확인해주세요.")

    return (f"{measure} 물이 1CBM당 1,000kg이니 물보다 무거운 화물입니다. "
            "맞다면 그대로 두셔도 됩니다. 운임은 부피가 아니라 중량으로 매겨집니다.")


def sum_money(values) -> float:
    """품목 금액을 더합니다. 더하는 동안에도 2진수 오차가 끼지 않게 Decimal 로."""

    total = Decimal("0")
    for value in values:
        total += Decimal(str(value))
    return float(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def calculate_revenue_ton(total_cbm: float, total_weight_kg: float) -> float:
    """Revenue Ton = max(Total CBM, Total Weight / 1000)."""

    return max(total_cbm, total_weight_kg / 1000)


def _air_ceiling(value) -> float:
    """항공 청구중량은 항공사가 0.5kg 단위로 **올려** 청구합니다(전수 점검 5회차 — 38.55kg 이 그대로 나왔습니다).

    합계에서 올립니다(박스마다 올리지 않습니다). 항공사에 따라 1kg 올림도 있어 화면은 '0.5kg 올림 기준'이라고 밝힙니다.
    """

    return float(math.ceil(round(float(value) * 2, 6)) / 2)


def calculate_chargeable_weight(
    total_weight_kg: float, total_cbm: float, volume_factor: float = AIR_VOLUME_FACTOR
) -> float:
    """Chargeable Weight = max(Actual Weight, Total CBM × volume factor)."""

    return max(total_weight_kg, total_cbm * volume_factor)


# 컨테이너 안쪽 치수(cm) 길이·폭·높이. 단일 포장이 이것을 넘으면 일반 컨테이너에 못 싣습니다.
CONTAINER_INTERIOR_CM = {"20GP": (590, 235, 239), "40GP": (1200, 235, 239), "40HC": (1200, 235, 269)}
def oversize_warnings(line: dict) -> list[str]:
    """한 포장(품목 한 줄)의 가로·세로·높이가 컨테이너 안쪽 치수를 넘으면 알립니다.

    1500×350×320cm 12t 한 개가 "40GP × 3" 으로, 높이 250cm 가 40GP 로 경고 없이 나왔습니다(전수 점검 2회차).
    계산을 막지는 않습니다 — 이런 화물은 OOG(Flat Rack·Open Top·Break-bulk) 대상이라 포워더 확인이 먼저입니다.
    항공 높이 한도는 항공사마다 달라 여기서는 판단하지 않습니다.
    """

    try:
        dims = sorted((float(line.get(key) or 0) for key in ("length_cm", "width_cm", "height_cm")), reverse=True)
    except (TypeError, ValueError):
        return []
    if not all(dims):
        return []
    from itertools import permutations

    def fits(container: str) -> bool:
        # 눕히거나 돌려서 실을 수 있는 모든 방향(길이·폭·높이)을 봅니다 — 가장 유리한 방향으로.
        length, width, height = CONTAINER_INTERIOR_CM[container]
        return any(a <= length and b <= width and c <= height for a, b, c in permutations(dims))

    notes = []
    shown = "×".join(f"{value:g}" for value in dims)
    if not fits("40HC"):
        length, width, height = CONTAINER_INTERIOR_CM["40HC"]
        notes.append(f"포장 하나({shown}cm)가 컨테이너 안쪽 치수(40HC 기준 {length}×{width}×{height}cm)에 "
                     "어느 방향으로도 들어가지 않습니다. Flat Rack·Open Top·Break-bulk(OOG) 여부를 포워더에 확인하세요.")
    elif not fits("40GP"):
        notes.append(f"포장 하나({shown}cm)는 40GP(안쪽 높이 {CONTAINER_INTERIOR_CM['40GP'][2]}cm)에는 안 들어가고 "
                     "**40HC(High Cube)** 가 필요합니다. 견적의 컨테이너는 40GP 기준이라 운임이 달라질 수 있습니다.")
    return notes


def calculate_container_quantity(
    total_cbm: float, total_weight_kg: float, container_type: str = DEFAULT_CONTAINER_TYPE
) -> int:
    """Return the number of containers needed by volume or payload, whichever is larger."""

    spec = CONTAINER_SPECS[container_type]
    by_volume = math.ceil(total_cbm / spec["max_cbm"])
    by_weight = math.ceil(total_weight_kg / spec["max_weight_kg"])
    return max(1, by_volume, by_weight)


def calculate_cargo_metrics(payload: dict, container_type: str = DEFAULT_CONTAINER_TYPE,
                            *, strict: bool = True) -> dict:
    """Validate cargo input and calculate CBM, weight, R/T, chargeable weight, and containers."""

    cargo = validate_cargo_input(payload, strict=strict)
    if container_type not in CONTAINER_SPECS:
        container_type = DEFAULT_CONTAINER_TYPE

    # 부피·중량 셈은 Decimal 로 합니다. 화면에 찍히는 CBM 이 운임의 기준이고,
    # 손으로 셈한 값과 마지막 자리가 달라지면 견적이 갈립니다.
    count = _dec(cargo["quantity"])
    unit_cbm = (_dec(cargo["length_cm"]) * _dec(cargo["width_cm"])
                * _dec(cargo["height_cm"]) / Decimal(1_000_000))
    total_cbm = unit_cbm * count
    total_weight_kg = _dec(cargo["weight_per_package_kg"]) * count
    shown_cbm = _dec(round_volume(total_cbm))          # 화면에 찍히는 값으로 뒤를 셈합니다
    shown_weight = _dec(_fix(total_weight_kg, 2))
    revenue_ton = max(shown_cbm, shown_weight / Decimal(1000))
    volume_weight_kg = shown_cbm * AIR_VOLUME_FACTOR_EXACT

    # 순중량은 품목마다 따로 적습니다. 그 품목의 총중량보다 클 수 없습니다.
    # 입력하는 도중(strict=False)에는 막지 않고 경고만 남깁니다.
    from app.validators.shipment_validator import validate_net_weight

    net_weight, net_warning = None, ""
    try:
        net_weight = validate_net_weight(payload.get("net_weight_kg"), _fix(total_weight_kg, 2))
    except ValidationError as error:
        if strict:
            raise
        net_warning = str(error)

    return {
        **cargo,
        # 화면에서 품목별 계산을 "품목 1 · 샴푸"처럼 이름과 함께 보여줍니다.
        "product_description": str(payload.get("product_description") or "").strip()[:300],
        "net_weight_kg": net_weight,
        "net_weight_warning": net_warning,
        "density_warning": density_note(float(shown_cbm), float(shown_weight)),
        # 포장 하나가 컨테이너에 안 들어가는 크기면 알립니다(OOG). 계산은 그대로 합니다.
        "oversize_warning": " ".join(oversize_warnings(payload)),
        "total_cbm": float(shown_cbm),
        "total_weight_kg": float(shown_weight),
        "revenue_ton": _fix(revenue_ton, 3),
        "billable_revenue_ton": _fix(max(_dec(LCL_MIN_REVENUE_TON), revenue_ton), 3),
        "volume_weight_kg": _fix(volume_weight_kg, 2),
        "chargeable_weight_kg": _air_ceiling(max(shown_weight, volume_weight_kg)),
        "container_type": container_type,
        "container_quantity": calculate_container_quantity(
            float(shown_cbm), float(shown_weight), container_type),
        "source": "calculated",
    }


def calculate_cargo_lines(items: list[dict], container_type: str = DEFAULT_CONTAINER_TYPE,
                          *, strict: bool = True) -> dict:
    """화물이 여러 건일 때 품목별 계산과 전체 합계를 함께 돌려줍니다.

    컨테이너 수량과 항공 운임중량은 품목을 더한 뒤에 정해야 하므로,
    품목별 값과 별개로 합계 기준으로 다시 계산합니다.
    """

    if container_type not in CONTAINER_SPECS:
        container_type = DEFAULT_CONTAINER_TYPE

    items = [item for item in (items or []) if isinstance(item, dict)]
    if not items:
        raise ValidationError("화물 정보를 입력해주세요.", "cargo")
    lines = [calculate_cargo_metrics(item, container_type, strict=strict) for item in items]
    # 줄마다 화면에 찍힌 값을 Decimal 로 더합니다. 화면의 줄을 손으로 더한 값과
    # 합계가 달라지면 "우리가 셈한 것과 다르다"는 말이 바로 나옵니다.
    total_cbm = sum((_dec(line["total_cbm"]) for line in lines), Decimal(0))
    total_weight_kg = sum((_dec(line["total_weight_kg"]) for line in lines), Decimal(0))
    revenue_ton = max(total_cbm, total_weight_kg / Decimal(1000))

    return {
        "lines": lines,
        "line_count": len(lines),
        # 한 건에 위험물이 섞여 있으면 부킹·서류가 통째로 달라집니다. 등급을 모아 둡니다.
        "dangerous_classes": sorted({line["dg_class"] for line in lines
                                     if line["is_dangerous"] and line["dg_class"]}),
        # 입력이 덜 되었거나 앞뒤가 맞지 않는 항목. 계산은 막지 않고 품목 번호와 함께 알려 줍니다.
        "dg_warnings": [{"line_no": index, "message": line["dg_warning"]}
                        for index, line in enumerate(lines, start=1) if line.get("dg_warning")],
        "warnings": [{"line_no": index, "message": line[key]}
                     for index, line in enumerate(lines, start=1)
                     for key in ("net_weight_warning", "units_warning", "density_warning", "oversize_warning")
                     if line.get(key)],
        "oversize_warning": " ".join(line["oversize_warning"] for line in lines if line.get("oversize_warning")),
        "quantity": sum(line["quantity"] for line in lines),
        # 품목별 금액을 모두 적었으면 그 합이 송장 금액입니다.
        # 하나라도 비어 있으면 지어내지 않고 None을 돌려줍니다.
        # 줄마다 이미 사사오입해 두었으므로 Decimal 로 더합니다. float 로 더하면
        # 0.01 이 스무 줄 쌓였을 때 총액이 한 푼 어긋납니다. 은행이 다시 셈합니다.
        "amount": (sum_money(line["amount"] for line in lines)
                   if lines and all(line.get("amount") is not None for line in lines) else None),
        # 하나라도 비면 합계를 내지 않습니다. 둘째 품목의 순중량이 없는데 3,500 으로 나가면 총중량 8,000 에
        # 순중량 3,500 이라는 틀린 서류가 됩니다(전수 점검 1회차).
        "net_weight_kg": (sum(line["net_weight_kg"] for line in lines)
                          if lines and all(line.get("net_weight_kg") for line in lines) else None),
        "total_cbm": round_volume(total_cbm),
        "total_weight_kg": _fix(total_weight_kg, 2),
        "revenue_ton": _fix(revenue_ton, 3),
        "billable_revenue_ton": _fix(max(_dec(LCL_MIN_REVENUE_TON), revenue_ton), 3),
        "volume_weight_kg": _fix(total_cbm * AIR_VOLUME_FACTOR_EXACT, 2),
        "chargeable_weight_kg": _air_ceiling(max(total_weight_kg, total_cbm * AIR_VOLUME_FACTOR_EXACT)),
        "container_type": container_type,
        "container_quantity": calculate_container_quantity(
            float(total_cbm), float(total_weight_kg), container_type),
        "source": "calculated",
    }
