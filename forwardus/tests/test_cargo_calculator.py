"""Cargo calculation and input validation tests."""

from __future__ import annotations

import pytest

from app.processors.cargo_calculator import (
    calculate_cargo_lines,
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


# --- 셈법: 사사오입 · 2진수 오차 없음 ------------------------------------------------
#
# 왜 테스트로 못 박아 두는가
#   금액·CBM 을 float 로 곱하면, 정확히 절반인 자리가 2진수 표현 때문에 아래로
#   떨어집니다. 30만 가지를 맞대어 보니 금액 6,049건(2%)이 1센트 어긋났습니다.
#   신용장 서류는 은행이 단가 × 수량을 다시 셈해 맞춰 보고, 한 푼만 달라도
#   불일치로 반송됩니다. 다시 float 로 돌아가면 이 테스트가 먼저 웁니다.
#   (2026-09-26)

@pytest.mark.parametrize("price,count,want", [
    ("27174.065", 1, 27174.07),        # float 로는 27174.06
    ("44917.885", 3, 134753.66),       # float 로는 134753.65
    ("91077.001", 25, 2276925.03),     # float 로는 2276925.02
    ("30557.085", 25, 763927.13),
    ("41206.435", 9999, 412023143.57),
])
def test_금액은_사사오입으로_셈한다(price, count, want):
    got = calculate_cargo_metrics(dict(BASE, quantity=count, unit_price=price))
    assert got["amount"] == want


def test_품목_금액의_합이_송장_금액과_맞는다():
    """줄마다 맞춘 금액을 더한 값이 총액이어야 합니다. float 로 더하면 어긋납니다."""

    rows = [dict(BASE, quantity=3, unit_price="44917.885") for _ in range(20)]
    total = calculate_cargo_lines(rows)
    assert total["amount"] == round(134753.66 * 20, 2)
    assert sum(line["amount"] for line in total["lines"]) == pytest.approx(total["amount"])


def test_CBM도_사사오입으로_셈한다():
    """16.5 × 10 × 10cm 상자 1개 = 0.00165 CBM. 넷째 자리가 딱 절반이면 위로."""

    got = calculate_cargo_metrics(dict(BASE, length_cm="16.5", width_cm="10",
                                       height_cm="10", quantity=1))
    assert got["total_cbm"] == 0.0017           # float round() 는 0.0016 을 줍니다


def test_용적중량_계수는_나누어_쓴다():
    """166.67 로 적어 두면 늘 위로 부풀어 청구가 늘어납니다."""

    from app.processors.cargo_calculator import AIR_VOLUME_FACTOR_EXACT
    from decimal import Decimal

    assert AIR_VOLUME_FACTOR_EXACT == Decimal(1_000_000) / Decimal(6_000)
    got = calculate_cargo_metrics(dict(BASE, length_cm=100, width_cm=100,
                                       height_cm=100, quantity=354))
    assert got["total_cbm"] == 354.0
    assert got["volume_weight_kg"] == 59000.0   # 166.67 을 쓰면 59001.18
