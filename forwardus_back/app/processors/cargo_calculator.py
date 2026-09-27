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


def calculate_cargo_metrics(payload: dict, container_type: str = DEFAULT_CONTAINER_TYPE) -> dict:
    """Validate cargo input and calculate CBM, weight, R/T, chargeable weight, and containers."""

    cargo = validate_cargo_input(payload)
    if container_type not in CONTAINER_SPECS:
        container_type = DEFAULT_CONTAINER_TYPE

    unit_cbm = cargo["length_cm"] * cargo["width_cm"] * cargo["height_cm"] / 1_000_000
    total_cbm = unit_cbm * cargo["quantity"]
    total_weight_kg = cargo["weight_per_package_kg"] * cargo["quantity"]
    revenue_ton = calculate_revenue_ton(total_cbm, total_weight_kg)
    volume_weight_kg = total_cbm * AIR_VOLUME_FACTOR

    return {
        **cargo,
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
