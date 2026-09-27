"""[만들기]를 두 번 눌러도 건이 하나여야 합니다.

화면은 누르는 순간 단추를 잠급니다. 그래도 두 번째 창에서 누르거나,
브라우저·중계 서버가 POST 를 다시 보내면 그대로 두 건이 만들어졌습니다.
넣어 보니 정말 두 건이 생겼습니다.

두 건이 생기면 둘 다 관세사에게 갈 수 있습니다. 같은 화물을 두 번 신고하거나,
한쪽만 고쳐 둔 채 다른 쪽이 나갑니다. 번호가 달라 사람은 알아채기 어렵습니다.

처음에는 서비스에서 "같은 사람·같은 스케줄·같은 바이어·같은 금액"처럼 몇 칸만
골라 견주었습니다. 그랬더니 **화물이 다른데도**(위험물 vs 일반) 같은 건으로
묶였습니다. 고른 칸에 화물이 없었기 때문입니다. 기존 테스트가 그것을 잡아
주었습니다. 몇 칸만 보면 언제나 빠뜨린 칸이 생기므로, **보낸 내용 전체**를
지문으로 보는 방식으로 바꿨습니다. (2026-09-26)
"""

from __future__ import annotations

import pytest

from app.models import Shipment
from app.routes import ONCE_SECONDS, once_only, remember_once


def _with_schedule(client, payload):
    found = client.post("/planning/api/schedules", json=payload).get_json()
    return {**payload, "schedule_id": found["data"]["items"][0]["schedule_id"]}


def test_창구로_두_번_보내도_한_건이다(client, shipment_payload):
    before = Shipment.query.count()
    payload = _with_schedule(client, shipment_payload)
    first = client.post("/planning/api/shipments", json=payload)
    second = client.post("/planning/api/shipments", json=payload)
    assert first.status_code < 400 and second.status_code < 400
    assert Shipment.query.count() == before + 1
    assert first.get_json()["data"]["shipment_id"] \
        == second.get_json()["data"]["shipment_id"]
    assert second.get_json()["data"].get("reused") is True


def test_보낸_내용이_한_글자라도_다르면_따로_만든다(client, shipment_payload):
    """몇 칸만 견주면 빠뜨린 칸이 생깁니다. 보낸 것을 통째로 봅니다."""

    before = Shipment.query.count()
    payload = _with_schedule(client, shipment_payload)
    client.post("/planning/api/shipments", json=payload)
    client.post("/planning/api/shipments",
                json={**payload, "project_name": payload["project_name"] + " 2차"})
    assert Shipment.query.count() == before + 2


def test_화물이_다르면_따로_만든다(client, shipment_payload, cargo_input):
    """위험물과 일반 화물이 같은 건으로 묶이면 신고가 통째로 틀립니다."""

    before = Shipment.query.count()
    payload = _with_schedule(client, shipment_payload)
    client.post("/planning/api/shipments", json=payload)
    client.post("/planning/api/shipments", json={
        **payload, "cargo": {**cargo_input, "is_dangerous": True, "dg_class": "3",
                             "un_number": "1263", "packing_group": "II",
                             "proper_shipping_name": "PAINT"}})
    assert Shipment.query.count() == before + 2


def test_서류_작성에서도_두_번_눌러도_한_건이다(client, shipment_payload, cargo_input):
    before = Shipment.query.count()
    payload = _with_schedule(client, shipment_payload)
    flat = {**payload, "buyer_name": payload["buyer"]["name"],
            "buyer_country": payload["buyer"]["country"],
            # 서류는 품목 금액을 반드시 적어야 합니다. (송장 금액이 됩니다)
            # 서류는 품목 금액을 반드시 적어야 합니다. (송장 금액이 됩니다)
            # 수량은 화물 견본 그대로 둡니다 — 바꾸면 순중량이 총중량을 넘습니다.
            "items": [{**cargo_input, "unit_price": "50.00",
                       "amount": f"{50 * cargo_input['quantity']:.2f}"}]}
    flat.pop("buyer", None)
    flat.pop("cargo", None)
    first = client.post("/documents/start", json=flat)
    second = client.post("/documents/start", json=flat)
    assert first.status_code < 400, first.get_data(as_text=True)[:200]
    assert second.status_code < 400
    assert Shipment.query.count() == before + 1


def test_지문은_보낸_내용_전체로_만든다(app):
    with app.test_request_context("/"):
        assert once_only("x", {"a": 1}) == ""
        remember_once("x", {"a": 1}, "EXP-1")
        assert once_only("x", {"a": 1}) == "EXP-1"
        assert once_only("x", {"a": 2}) == "", "한 글자만 달라도 다른 요청입니다"
        assert once_only("y", {"a": 1}) == "", "다른 창구면 다른 요청입니다"


def test_기억하는_시간이_너무_길지_않다():
    """길면 일부러 두 번 만들고 싶을 때 막힙니다."""

    assert 30 <= ONCE_SECONDS <= 300
