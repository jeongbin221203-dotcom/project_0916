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


@pytest.mark.parametrize("term", sorted(ICC_2020))
@pytest.mark.parametrize("category", sorted(CATEGORIES))
def test_조건별로_이_비용을_누가_내는가(term, category):
    assert assistant_service._exporter_pays(term, category) is (
        CATEGORIES[category] in ICC_2020[term])


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
