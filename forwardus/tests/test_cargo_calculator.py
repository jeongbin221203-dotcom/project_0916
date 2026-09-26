"""Cargo calculation and input validation tests."""

from __future__ import annotations

import pytest

from app.processors.cargo_calculator import (
    calculate_cargo_metrics,
    calculate_chargeable_weight,
    calculate_container_quantity,
    calculate_revenue_ton,
)
from app.processors.cost_calculator import calculate_insurance_premium
from app.validators import ValidationError

BASE = {
    "length_cm": 100,
    "width_cm": 100,
    "height_cm": 100,
    "quantity": 2,
    "weight_per_package_kg": 600,
}


def test_cbm_weight_and_revenue_ton():
    result = calculate_cargo_metrics(BASE)
    assert result["total_cbm"] == 2.0
    assert result["total_weight_kg"] == 1200.0
    assert result["revenue_ton"] == 2.0


def test_revenue_ton_uses_weight_when_heavier():
    assert calculate_revenue_ton(1.5, 3200) == 3.2
    assert calculate_revenue_ton(4.0, 1000) == 4.0


def test_lcl_billable_minimum_is_one_rt():
    small = dict(BASE, length_cm=10, width_cm=10, height_cm=10, quantity=1, weight_per_package_kg=1)
    result = calculate_cargo_metrics(small)
    assert result["revenue_ton"] == pytest.approx(0.001)
    assert result["billable_revenue_ton"] == 1.0


def test_air_chargeable_weight():
    # 용적중량 = 가로×세로×높이(cm) ÷ 6,000. 1 CBM이면 1,000,000/6,000 = 166.666…kg.
    # **반올림한 166.67을 쓰지 않습니다.** 항공 운임은 kg당 매겨져 그 0.002%가
    # 그대로 돈이 되고, 늘 위로 치우쳐 청구가 부풀었습니다. (2026-09-26)
    # 2 CBM = 333.33 kg < 1,200 kg 실중량 → 실중량이 이깁니다.
    assert calculate_cargo_metrics(BASE)["chargeable_weight_kg"] == 1200.0
    # 가볍고 부피가 큰 화물 → 용적중량이 이깁니다.
    assert calculate_chargeable_weight(100, 2.0) == pytest.approx(333.3333, abs=0.001)
    # 큰 건에서 반올림 상수와 벌어지는 폭. (354 CBM이면 1.18kg)
    assert calculate_chargeable_weight(1000, 354.0) == pytest.approx(59000.0, abs=0.01)


def test_container_quantity_by_volume_and_weight():
    assert calculate_container_quantity(30, 5000, "40GP") == 1
    assert calculate_container_quantity(120, 5000, "40GP") == 3
    assert calculate_container_quantity(10, 60000, "40GP") == 3


def test_insurance_minimum():
    assert calculate_insurance_premium(100, 10, 1380) >= 10_000


@pytest.mark.parametrize("field", ["length_cm", "width_cm", "height_cm", "quantity", "weight_per_package_kg"])
@pytest.mark.parametrize("bad", [None, "", "   ", "abc", "nan", "inf", "-inf", -1, 0, True])
def test_invalid_numeric_input_rejected(field, bad):
    with pytest.raises(ValidationError) as info:
        calculate_cargo_metrics(dict(BASE, **{field: bad}))
    assert info.value.field == field


def test_numeric_strings_accepted():
    result = calculate_cargo_metrics({k: str(v) for k, v in BASE.items()})
    assert result["total_cbm"] == 2.0


def test_quantity_must_be_integer():
    with pytest.raises(ValidationError):
        calculate_cargo_metrics(dict(BASE, quantity=2.5))


@pytest.mark.parametrize("field,value", [
    ("length_cm", 1e9),
    ("quantity", 10_000_000),
    ("weight_per_package_kg", 1e7),
])
def test_abnormally_large_values_rejected(field, value):
    with pytest.raises(ValidationError):
        calculate_cargo_metrics(dict(BASE, **{field: value}))


def test_invalid_package_type_rejected():
    with pytest.raises(ValidationError):
        calculate_cargo_metrics(dict(BASE, package_type="spaceship"))
