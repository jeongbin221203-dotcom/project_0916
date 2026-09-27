"""⑬ 인코텀즈를 바꾸면 따라와야 할 것이 **모두** 따라오는가.

조건 하나를 바꾸면 위험이 넘어가는 시점·보험 의무·누가 무엇을 내는지가
한꺼번에 달라집니다. 하나라도 옛 조건으로 남으면 견적과 서류가 어긋나고,
그 차액은 나중에 누가 내느냐로 다툽니다.

기준표는 **제품 표를 보지 않고** ICC Incoterms 2020 규칙에서 따로 적었습니다.
같은 표를 두 번 읽으면 틀린 것을 못 찾습니다. (2026-09-27)
"""

from __future__ import annotations

import pytest

from app.processors.cargo_calculator import calculate_cargo_lines
from app.processors.cost_calculator import (EXPORTER_PAYS, INCOTERMS_INFO,
                                            INSURANCE_PAID_BY_EXPORTER,
                                            calculate_logistics_cost)

SEA_ONLY = {"FAS", "FOB", "CFR", "CIF"}          # 본선 기준이라 항공에는 못 씁니다
INSURANCE_DUTY = {"CIF": "ICC(C)", "CIP": "ICC(A)"}   # 보험을 사 줄 의무는 이 둘뿐
GROUPS = {"EXW": "E", "FCA": "F", "FAS": "F", "FOB": "F",
          "CFR": "C", "CIF": "C", "CPT": "C", "CIP": "C",
          "DAP": "D", "DPU": "D", "DDP": "D"}

INFO = {row["code"]: row for row in INCOTERMS_INFO}
CARGO = [{"product_description": "치약", "package_type": "carton", "quantity": 100,
          "length_cm": 40, "width_cm": 30, "height_cm": 25, "weight_per_package_kg": 8}]


def _quote(code):
    return calculate_logistics_cost(
        transport_mode="SEA", sea_mode="LCL", incoterms=code,
        freight_usd=1200, freight_source="tariff", invoice_value_usd=25000,
        metrics=calculate_cargo_lines(CARGO), exchange_rate=1380.5)


def test_조건은_11개다():
    assert set(INFO) == set(GROUPS)


@pytest.mark.parametrize("code", sorted(GROUPS))
def test_해상_전용_표시가_맞다(code):
    """FAS·FOB·CFR·CIF 는 '본선 옆'·'본선 적재' 기준이라 항공에는 넘어가는 시점이 없습니다."""

    assert bool(INFO[code].get("sea_only")) is (code in SEA_ONLY)


@pytest.mark.parametrize("code,level", sorted(INSURANCE_DUTY.items()))
def test_보험_의무는_CIF_CIP_뿐이고_담보_수준을_적는다(code, level):
    text = " ".join(str(INFO[code].get(key) or "")
                    for key in ("short", "summary", "risk", "detail", "caution",
                                "seller_cost", "buyer_cost", "duties"))
    assert level in text, f"{code} 에 {level} 이 없습니다"
    assert "110" in text, f"{code} 에 보험금액(매매대금의 110% 이상)이 없습니다"


@pytest.mark.parametrize("code", sorted(GROUPS))
def test_비용_배분이_조건_묶음과_맞다(code):
    pays, group = EXPORTER_PAYS[code], GROUPS[code]
    if group == "E":
        assert not pays, "E조건은 수출자가 아무것도 내지 않습니다"
    if group == "F":
        assert "freight" not in pays, "F조건은 바이어가 운임을 냅니다"
    if group in ("C", "D"):
        assert "freight" in pays, f"{group}조건은 수출자가 운임을 냅니다"
    if group == "D":
        assert "destination" in pays, "D조건은 도착지까지 수출자가 냅니다"


@pytest.mark.parametrize("code", sorted(GROUPS))
def test_적하보험료는_위험을_지는_쪽이_낸다(code):
    """의무(ICC)와 별개입니다. D조건은 도착지까지 위험을 지므로 보험도 수출자."""

    want = code in INSURANCE_DUTY or GROUPS[code] == "D"
    assert (code in INSURANCE_PAID_BY_EXPORTER) is want


def test_조건이_뒤로_갈수록_수출자_부담이_늘어난다():
    """EXW 에서 DDP 로 갈수록 수출자가 더 냅니다. 뒤집히면 견적이 틀린 것입니다."""

    order = ["EXW", "FOB", "CFR", "CIF", "DAP", "DDP"]
    amounts = [_quote(code)["exporter_total_krw"] for code in order]
    assert amounts == sorted(amounts), dict(zip(order, amounts))


def test_EXW는_수출자_0원_DDP는_바이어_0원():
    assert _quote("EXW")["exporter_total_krw"] == 0
    assert _quote("DDP")["buyer_total_krw"] == 0


@pytest.mark.parametrize("code", sorted(GROUPS))
def test_수출자와_바이어를_더하면_총액이다(code):
    got = _quote(code)
    assert got["exporter_total_krw"] + got["buyer_total_krw"] == got["total_krw"]
