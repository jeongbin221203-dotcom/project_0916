"""Cargo measurement and freight unit calculations."""

from __future__ import annotations

import math

from app.validators.cargo_validator import validate_cargo_input

# IATA standard volume factor (1 CBM = 166.67 kg, i.e. 6,000 cm3/kg).
# Carriers may apply different factors, so it is kept configurable.
AIR_VOLUME_FACTOR = 166.67

# Minimum billable unit for LCL freight.
LCL_MIN_REVENUE_TON = 1.0

# Practical loadable volume and payload per container type.
CONTAINER_SPECS = {
    "20GP": {"max_cbm": 28.0, "max_weight_kg": 21_000},
    "40GP": {"max_cbm": 58.0, "max_weight_kg": 26_000},
    "40HC": {"max_cbm": 68.0, "max_weight_kg": 26_000},
}
DEFAULT_CONTAINER_TYPE = "40GP"


def calculate_revenue_ton(total_cbm: float, total_weight_kg: float) -> float:
    """Revenue Ton = max(Total CBM, Total Weight / 1000)."""

    return max(total_cbm, total_weight_kg / 1000)


def calculate_chargeable_weight(
    total_weight_kg: float, total_cbm: float, volume_factor: float = AIR_VOLUME_FACTOR
) -> float:
    """Chargeable Weight = max(Actual Weight, Total CBM × volume factor)."""

    return max(total_weight_kg, total_cbm * volume_factor)


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

    unit_cbm = cargo["length_cm"] * cargo["width_cm"] * cargo["height_cm"] / 1_000_000
    total_cbm = unit_cbm * cargo["quantity"]
    total_weight_kg = cargo["weight_per_package_kg"] * cargo["quantity"]
    revenue_ton = calculate_revenue_ton(total_cbm, total_weight_kg)
    volume_weight_kg = total_cbm * AIR_VOLUME_FACTOR

    # 순중량은 품목마다 따로 적습니다. 그 품목의 총중량보다 클 수 없습니다.
    # 입력하는 도중(strict=False)에는 막지 않고 경고만 남깁니다.
    from app.validators import ValidationError
    from app.validators.shipment_validator import validate_net_weight

    net_weight, net_warning = None, ""
    try:
        net_weight = validate_net_weight(payload.get("net_weight_kg"), round(total_weight_kg, 2))
    except ValidationError as error:
        if strict:
            raise
        net_warning = str(error)

    return {
        **cargo,
        "net_weight_kg": net_weight,
        "net_weight_warning": net_warning,
        "total_cbm": round(total_cbm, 4),
        "total_weight_kg": round(total_weight_kg, 2),
        "revenue_ton": round(revenue_ton, 3),
        "billable_revenue_ton": round(max(LCL_MIN_REVENUE_TON, revenue_ton), 3),
        "volume_weight_kg": round(volume_weight_kg, 2),
        "chargeable_weight_kg": round(calculate_chargeable_weight(total_weight_kg, total_cbm), 2),
        "container_type": container_type,
        "container_quantity": calculate_container_quantity(total_cbm, total_weight_kg, container_type),
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

    lines = [calculate_cargo_metrics(item, container_type, strict=strict) for item in items]
    total_cbm = sum(line["total_cbm"] for line in lines)
    total_weight_kg = sum(line["total_weight_kg"] for line in lines)
    revenue_ton = calculate_revenue_ton(total_cbm, total_weight_kg)

    return {
        "lines": lines,
        "line_count": len(lines),
        # 한 건에 위험물이 섞여 있으면 부킹·서류가 통째로 달라집니다. 등급을 모아 둡니다.
        "dangerous_classes": sorted({line["dg_class"] for line in lines
                                     if line["is_dangerous"] and line["dg_class"]}),
        # 입력이 덜 되었거나 앞뒤가 맞지 않는 항목. 계산은 막지 않고 품목 번호와 함께 알려 줍니다.
        "dg_warnings": [{"line_no": index, "message": line["dg_warning"]}
                        for index, line in enumerate(lines, start=1) if line.get("dg_warning")],
        "warnings": [{"line_no": index, "message": line["net_weight_warning"]}
                     for index, line in enumerate(lines, start=1) if line.get("net_weight_warning")],
        "quantity": sum(line["quantity"] for line in lines),
        "net_weight_kg": sum(line.get("net_weight_kg") or 0 for line in lines) or None,
        "total_cbm": round(total_cbm, 4),
        "total_weight_kg": round(total_weight_kg, 2),
        "revenue_ton": round(revenue_ton, 3),
        "billable_revenue_ton": round(max(LCL_MIN_REVENUE_TON, revenue_ton), 3),
        "volume_weight_kg": round(total_cbm * AIR_VOLUME_FACTOR, 2),
        "chargeable_weight_kg": round(calculate_chargeable_weight(total_weight_kg, total_cbm), 2),
        "container_type": container_type,
        "container_quantity": calculate_container_quantity(total_cbm, total_weight_kg, container_type),
        "source": "calculated",
    }
