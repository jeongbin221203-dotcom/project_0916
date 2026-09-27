"""계산이 늘 지켜야 하는 것들.

터지느냐가 아니라 "답이 맞느냐"를 봅니다. hypothesis가 값을 수천 가지로
바꿔 가며 아래 규칙이 깨지는 입력을 찾습니다.

여기서 깨지면 화면에 틀린 숫자가 나온다는 뜻이라, 터지는 것보다 위험합니다.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from app.processors import cargo_calculator as cc
from app.processors import cost_calculator as cost
from app.processors import transit_calculator as tc
from app.processors.korean import particle
from app.validators import ValidationError

FAST = settings(max_examples=300, deadline=None)

dimension = st.floats(min_value=0.1, max_value=1500, allow_nan=False, allow_infinity=False)
weight = st.floats(min_value=0.001, max_value=30_000, allow_nan=False, allow_infinity=False)
count = st.integers(min_value=1, max_value=50_000)
money = st.floats(min_value=0.01, max_value=10_000_000, allow_nan=False, allow_infinity=False)


def an_item(length, width, height, quantity, kg, amount=None):
    item = {"product_description": "품목", "package_type": "carton",
            "length_cm": length, "width_cm": width, "height_cm": height,
            "quantity": quantity, "weight_per_package_kg": kg}
    if amount is not None:
        item["amount"] = amount
    return item


@FAST
@given(dimension, dimension, dimension, count, weight)
def test_volume_and_weight_scale_with_quantity(length, width, height, quantity, kg):
    """수량이 두 배면 부피도 중량도 두 배여야 합니다."""

    one = cc.calculate_cargo_metrics(an_item(length, width, height, 1, kg), strict=False)
    many = cc.calculate_cargo_metrics(an_item(length, width, height, quantity, kg), strict=False)

    # 화면에 보여주려고 반올림하므로, 그 자릿수만큼은 어긋날 수 있습니다.
    # (중량 소수 둘째 자리, 부피 넷째 자리)
    assert many["total_weight_kg"] == pytest.approx(
        one["total_weight_kg"] * quantity, rel=1e-6, abs=0.01 * quantity)
    assert many["total_cbm"] == pytest.approx(
        one["total_cbm"] * quantity, rel=1e-3, abs=0.0001 * quantity)
    # 부피가 있는 화물은 CBM이 0이 아니어야 합니다.
    assert many["total_cbm"] > 0


@FAST
@given(st.lists(st.tuples(dimension, dimension, dimension, count, weight),
                min_size=1, max_size=8))
def test_totals_equal_the_sum_of_the_items(rows):
    """합계는 품목을 더한 값이어야 합니다. 화면 오른쪽 패널의 근거입니다."""

    items = [an_item(*row) for row in rows]
    result = cc.calculate_cargo_lines(items, strict=False)

    assert result["total_weight_kg"] == pytest.approx(
        sum(line["total_weight_kg"] for line in result["lines"]), rel=1e-9, abs=0.01)
    assert result["total_cbm"] == pytest.approx(
        sum(line["total_cbm"] for line in result["lines"]), rel=1e-9, abs=0.0001)
    assert result["quantity"] == sum(line["quantity"] for line in result["lines"])
    assert result["line_count"] == len(items)


@FAST
@given(st.lists(st.tuples(dimension, dimension, dimension, count, weight, money),
                min_size=1, max_size=6))
def test_invoice_total_is_the_sum_of_item_amounts(rows):
    """품목 금액을 모두 적었으면 합계는 그 합이어야 합니다."""

    items = [an_item(*row[:5], amount=row[5]) for row in rows]
    result = cc.calculate_cargo_lines(items, strict=False)

    # 금액은 줄마다 원 단위로 맞춘 뒤 더합니다. 그래야 송장의 품목 합과 총액이
    # 어긋나지 않습니다. (예전에는 품목 합 6.24, 총액 6.25가 나왔습니다)
    assert result["amount"] == pytest.approx(
        round(sum(line["amount"] for line in result["lines"]), 2), abs=1e-9)
    assert all(line["amount"] == round(line["amount"], 2) for line in result["lines"])

    # 한 건이라도 비어 있으면 지어내지 않고 비웁니다.
    items[0].pop("amount")
    assert cc.calculate_cargo_lines(items, strict=False)["amount"] is None


@FAST
@given(dimension, dimension, dimension, count, weight)
def test_revenue_ton_is_the_larger_of_volume_and_weight(length, width, height, quantity, kg):
    """R/T는 부피와 중량 가운데 큰 쪽입니다. 운임의 기준입니다."""

    m = cc.calculate_cargo_metrics(an_item(length, width, height, quantity, kg), strict=False)
    # R/T는 화면·청구에 쓰려고 소수 셋째 자리까지 맞춥니다.
    # 반올림이므로 참값과의 차이는 마지막 자리의 절반을 넘지 않아야 합니다.
    exact = max(m["total_cbm"], m["total_weight_kg"] / 1000)
    # 값이 아주 크면 실수 자체의 오차가 반올림보다 커집니다. 크기에 비례해 봅니다.
    allowed = 0.0005 + max(1e-9, abs(exact) * 1e-12)
    assert abs(m["revenue_ton"] - exact) <= allowed, (m["revenue_ton"], exact)
    # LCL은 1 R/T 밑으로 깎아 주지 않습니다.
    assert m["billable_revenue_ton"] >= 1.0
    assert m["billable_revenue_ton"] >= m["revenue_ton"] - 1e-6


@FAST
@given(dimension, dimension, dimension, count, weight)
def test_air_chargeable_weight_is_never_below_actual_weight(length, width, height, quantity, kg):
    """항공 운임중량은 실중량보다 작을 수 없습니다."""

    m = cc.calculate_cargo_metrics(an_item(length, width, height, quantity, kg), strict=False)
    assert m["chargeable_weight_kg"] >= m["total_weight_kg"] - 1e-6
    assert m["chargeable_weight_kg"] >= m["volume_weight_kg"] - 1e-6


@FAST
@given(dimension, dimension, dimension, count, weight)
def test_containers_are_enough_to_hold_the_cargo(length, width, height, quantity, kg):
    """계산한 컨테이너 수로 화물이 실제로 들어가야 합니다."""

    for container in ("20GP", "40GP", "40HC"):
        m = cc.calculate_cargo_metrics(
            an_item(length, width, height, quantity, kg), container, strict=False)
        spec = cc.CONTAINER_SPECS[container]
        boxes = m["container_quantity"]
        assert boxes >= 1
        assert boxes * spec["max_cbm"] >= m["total_cbm"] - 1e-6
        assert boxes * spec["max_weight_kg"] >= m["total_weight_kg"] - 1e-6


@FAST
@given(st.floats(min_value=100, max_value=40_000, allow_nan=False),
       st.sampled_from(["asia", "americas", "europe", "africa"]))
def test_lcl_is_never_faster_than_fcl(distance_km, region):
    """LCL은 CFS 작업이 더 붙으므로 FCL보다 빠를 수 없습니다."""

    fcl = tc.sea_transit(distance_km, [], "FCL", direct=True, region=region)
    lcl = tc.sea_transit(distance_km, [], "LCL", direct=True, region=region)
    assert lcl["min"] >= fcl["min"]
    assert lcl["max"] >= fcl["max"]
    assert fcl["min"] <= fcl["max"] and lcl["min"] <= lcl["max"]


@FAST
@given(st.floats(min_value=100, max_value=40_000, allow_nan=False))
def test_transshipment_is_never_faster_than_direct(distance_km):
    """환적이 직기항보다 빠를 수는 없습니다."""

    direct = tc.sea_transit(distance_km, [], "FCL", direct=True, region="asia")
    transship = tc.sea_transit(distance_km, [], "FCL", direct=False, region="asia")
    assert transship["min"] >= direct["min"]
    assert transship["max"] >= direct["max"]


@FAST
@given(st.floats(min_value=100, max_value=40_000, allow_nan=False),
       st.lists(st.sampled_from(["suez", "panama"]), max_size=2, unique=True))
def test_canals_only_add_time(distance_km, canals):
    """운하를 지나면 대기가 붙습니다. 줄어들 수는 없습니다."""

    plain = tc.sea_transit(distance_km, [], "FCL", direct=True, region="asia")
    through = tc.sea_transit(distance_km, canals, "FCL", direct=True, region="asia")
    assert through["min"] >= plain["min"]


@FAST
@given(st.integers(min_value=0, max_value=3650),
       st.dates(min_value=date(2000, 1, 1), max_value=date(2099, 1, 1)))
def test_eta_is_always_departure_plus_transit(days, departure):
    """도착일은 출발일에 소요일을 더한 날입니다. 윤년·월말도 같습니다."""

    from app.processors.schedule_calculator import calculate_eta

    assert calculate_eta(departure, days) == departure + timedelta(days=days)


@FAST
@given(money, st.floats(min_value=500, max_value=2000, allow_nan=False),
       st.sampled_from(list(cost.EXPORTER_PAYS)),
       st.sampled_from([("SEA", "FCL"), ("SEA", "LCL"), ("AIR", None)]))
def test_cost_totals_add_up_and_never_go_negative(freight_usd, rate, incoterms, modes):
    """물류비 합계는 줄의 합이고, 어떤 줄도 음수가 아니어야 합니다."""

    mode, sea_mode = modes
    metrics = cc.calculate_cargo_lines(
        [an_item(40, 30, 25, 100, 12)], strict=False)
    result = cost.calculate_logistics_cost(
        transport_mode=mode, sea_mode=sea_mode, incoterms=incoterms,
        freight_usd=freight_usd, freight_source="mock", invoice_value_usd=5000,
        metrics=metrics, exchange_rate=rate, exchange_source="mock")

    assert all(line["krw_amount"] >= 0 for line in result["lines"])
    assert result["total_krw"] == pytest.approx(
        sum(line["krw_amount"] for line in result["lines"]), rel=1e-6)
    # 수출자 부담은 전체를 넘을 수 없습니다.
    assert 0 <= result["exporter_total_krw"] <= result["total_krw"] + 1e-6


@FAST
@given(st.text(min_size=1, max_size=40))
def test_particles_never_produce_an_empty_or_broken_word(word):
    """조사는 어떤 말 뒤에서도 비어 있거나 깨지면 안 됩니다."""

    for form in ("이", "로", "을", "와", "은"):
        result = particle(word, form)
        assert result and isinstance(result, str)
        assert len(result) <= 6           # "가(이)" 같은 괄호 표기가 가장 깁니다.


@FAST
@given(st.text(alphabet=st.characters(min_codepoint=0xAC00, max_codepoint=0xD7A3),
               min_size=1, max_size=20))
def test_korean_particles_are_decided_not_hedged(word):
    """순한글 말 뒤에서는 "가(이)"처럼 얼버무리지 않고 하나를 고릅니다."""

    for form in ("이", "을", "와", "은"):
        assert "(" not in particle(word, form), word
    assert particle(word, "로") in ("로", "으로")


@FAST
@given(st.integers(min_value=-3650, max_value=3650))
def test_loading_deadline_never_contradicts_itself(offset):
    """적재의무기한 안내는 남은 날짜와 말이 맞아야 합니다."""

    from app.services import container_tracking_service as cts

    today = date(2026, 9, 20)
    due = (today + timedelta(days=offset)).isoformat()

    status = cts.deadline_status(due, False, today)
    assert status["days"] == offset
    if offset < 0:
        assert status["kind"] == "over" and "지났" in status["text"]
    elif offset <= cts.DEADLINE_WARNING_DAYS:
        assert status["kind"] == "soon"
    else:
        assert status["kind"] == "ok"

    # 이미 실었으면 기한을 따지지 않습니다.
    assert cts.deadline_status(due, True, today)["kind"] == "done"


@FAST
@given(dimension, dimension, dimension, count, weight, weight)
def test_net_weight_can_never_exceed_gross(length, width, height, quantity, kg, net):
    """순중량이 총중량보다 크면 잡아내야 합니다. 신고서에 그대로 들어갑니다."""

    item = an_item(length, width, height, quantity, kg)
    gross = round(kg * quantity, 2)
    item["net_weight_kg"] = net
    assume(net != gross)

    if net > gross:
        with pytest.raises(ValidationError):
            cc.calculate_cargo_metrics(item, strict=True)
        # 입력 중에는 막지 않고 경고만 남깁니다.
        lenient = cc.calculate_cargo_metrics(item, strict=False)
        assert lenient["net_weight_warning"]
        assert lenient["net_weight_kg"] is None
    else:
        assert cc.calculate_cargo_metrics(item, strict=True)["net_weight_kg"] == pytest.approx(net)
