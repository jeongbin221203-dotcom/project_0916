"""㉓ AI Assistant — 인코텀즈별 **수출자 부담 비용**.

화면은 "FOB 조건에서 수출자 부담 비용은 약 X원, 나머지는 Buyer 부담입니다"
라고 단정합니다. 이 배분이 ICC 표와 어긋나면 견적이 그대로 틀립니다.
표를 손으로 한 번 더 적어 두고 맞대어 봅니다. (2026-09-26)
"""

from __future__ import annotations

import pytest

from app.processors.cost_calculator import EXPORTER_PAYS
from app.services import assistant_service


# ICC Incoterms 2020 A9/B9 비용 배분. **제품 표를 보고 적지 않고** 규칙에서 적었습니다.
#   origin      수출지 비용 (수출통관 · 터미널 · 반입)
#   freight     국제운임
#   insurance   적하보험 (CIF · CIP 만 매도인 의무)
#   destination 도착지 비용 (양하 · 터미널)
#   import      수입통관 · 관세 (DDP 만)
ICC_2020 = {
    "EXW": set(),
    "FCA": {"origin"},
    "FAS": {"origin"},
    "FOB": {"origin"},
    "CFR": {"origin", "freight"},
    "CIF": {"origin", "freight", "insurance"},
    "CPT": {"origin", "freight"},
    "CIP": {"origin", "freight", "insurance"},
    "DAP": {"origin", "freight", "destination"},
    "DPU": {"origin", "freight", "destination"},
    "DDP": {"origin", "freight", "destination", "import"},
}
CATEGORIES = {"Origin Charge": "origin", "Customs": "origin", "Freight": "freight",
              "Insurance": "insurance", "Destination Charge": "destination"}


def test_조건_11개가_모두_있고_더도_덜도_없다():
    assert set(EXPORTER_PAYS) == set(ICC_2020)


@pytest.mark.parametrize("term", sorted(ICC_2020))
def test_비용_배분이_ICC_2020과_같다(term):
    assert EXPORTER_PAYS[term] == ICC_2020[term]


# 적하보험료만 규칙이 다릅니다.
#
# EXPORTER_PAYS 는 ICC 가 정한 **의무** 표입니다. 보험을 사 줄 의무는 CIF·CIP 에만
# 있습니다. 그런데 견적서는 "이 돈을 누가 내는가"를 적는 자리라 뜻이 다릅니다.
# D조건(DAP·DPU·DDP)은 수출자가 도착지까지 위험을 지므로 그 보험도 수출자가
# 자기 돈으로 듭니다. 바이어는 덮을 위험이 없습니다. 예전에는 의무 표만 보고
# "적하보험료 — 바이어 부담"이라고 적어, DDP 견적에서 바이어 부담이 0원이어야
# 하는데 보험료만큼 남았습니다. (2026-09-26)
INSURANCE_PAID_BY_EXPORTER = {"CIF", "CIP", "DAP", "DPU", "DDP"}


@pytest.mark.parametrize("term", sorted(ICC_2020))
@pytest.mark.parametrize("category", sorted(CATEGORIES))
def test_조건별로_이_비용을_누가_내는가(term, category):
    group = CATEGORIES[category]
    want = (term in INSURANCE_PAID_BY_EXPORTER if group == "insurance"
            else group in ICC_2020[term])
    assert assistant_service._exporter_pays(term, category) is want


def test_적하보험료는_D조건에서_수출자가_낸다():
    """D조건은 수출자가 도착지까지 위험을 집니다. 바이어는 덮을 위험이 없습니다."""

    for term in ("DAP", "DPU", "DDP", "CIF", "CIP"):
        assert assistant_service._exporter_pays(term, "Insurance"), term
    for term in ("EXW", "FCA", "FAS", "FOB", "CFR", "CPT"):
        assert not assistant_service._exporter_pays(term, "Insurance"), term


def test_DDP는_바이어_부담이_0이다():
    """수출자가 문 앞까지 모두 부담하는 조건입니다. 한 항목이라도 남으면 틀린 견적입니다."""

    from app.processors import cost_calculator
    from app.processors.cargo_calculator import calculate_cargo_lines

    metrics = calculate_cargo_lines([{
        "product_description": "화물", "package_type": "carton", "quantity": 100,
        "length_cm": 40, "width_cm": 30, "height_cm": 25, "weight_per_package_kg": 8}])
    got = cost_calculator.calculate_logistics_cost(
        transport_mode="SEA", sea_mode="LCL", incoterms="DDP",
        freight_usd=1200, freight_source="tariff", invoice_value_usd=25000,
        metrics=metrics, exchange_rate=1380.5)
    assert got["buyer_total_krw"] == 0
    assert got["exporter_total_krw"] == got["total_krw"]


def test_EXW는_수출자_부담이_0이다():
    from app.processors import cost_calculator
    from app.processors.cargo_calculator import calculate_cargo_lines

    metrics = calculate_cargo_lines([{
        "product_description": "화물", "package_type": "carton", "quantity": 100,
        "length_cm": 40, "width_cm": 30, "height_cm": 25, "weight_per_package_kg": 8}])
    got = cost_calculator.calculate_logistics_cost(
        transport_mode="SEA", sea_mode="LCL", incoterms="EXW",
        freight_usd=1200, freight_source="tariff", invoice_value_usd=25000,
        metrics=metrics, exchange_rate=1380.5)
    assert got["exporter_total_krw"] == 0


@pytest.mark.parametrize("term", sorted(ICC_2020))
def test_모르는_비용_항목은_수출자_부담으로_셈하지_않는다(term):
    """지어내면 견적이 늘어납니다. 모르면 안 넣습니다."""

    assert not assistant_service._exporter_pays(term, "Unknown Charge")


def test_EXW는_수출자가_아무것도_내지_않는다(create_shipment):
    shipment = create_shipment(incoterms="EXW")
    got = assistant_service.cost_explanation(shipment)
    if got.get("available"):
        assert got["exporter_cost_krw"] == 0


@pytest.mark.parametrize("term", ["FOB", "CIF", "DDP"])
def test_수출자_부담은_총액을_넘지_않는다(create_shipment, term):
    shipment = create_shipment(incoterms=term)
    got = assistant_service.cost_explanation(shipment)
    if got.get("available"):
        assert 0 <= got["exporter_cost_krw"] <= got["total_krw"]
