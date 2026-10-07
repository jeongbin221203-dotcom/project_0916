"""제재 확인 — 도착국만이 아니라 바이어 국가·주소·수정 경로에도, 일반 거래는 건드리지 않습니다."""

import pytest

from app.extensions import db
from app.models import Shipment
from app.services import planning_service, shipment_service
from app.validators import ValidationError


@pytest.mark.parametrize("buyer_country", ["KP", "RU", "IR", "CU", "SY"])
def test_바이어_국가가_제재국이면_도착국이_달라도_막거나_확인받는다(buyer_country):
    with pytest.raises(ValidationError) as caught:
        planning_service.check_trade_controls(["CN", buyer_country], {})
    assert caught.value.code in ("TRADE_CONTROL", "RESTRICTED_CONFIRM")
    if caught.value.code == "RESTRICTED_CONFIRM":
        planning_service.check_trade_controls(["CN", buyer_country], {"restricted_confirmed": True})


def test_북한은_확인해도_막는다():
    with pytest.raises(ValidationError) as caught:
        planning_service.check_trade_controls(["US", "KP"], {"restricted_confirmed": True})
    assert caught.value.code == "TRADE_CONTROL"


@pytest.mark.parametrize("text", ["Sevastopol, Crimea", "Donetsk City", "크림반도 세바스토폴", "Mariupol port"])
def test_주소에_점령지_이름이_있으면_나라_칸이_UA여도_확인받는다(text):
    with pytest.raises(ValidationError) as caught:
        planning_service.check_trade_controls(["CN", "UA"], {}, text=text)
    assert caught.value.code == "RESTRICTED_CONFIRM"
    planning_service.check_trade_controls(["CN", "UA"], {"restricted_confirmed": True}, text=text)


@pytest.mark.parametrize("country, text", [("US", "Los Angeles, CA"), ("DE", "Hamburg"), ("UA", "Kyiv"),
                                            ("KZ", "Almaty"), ("JP", "Donetsu Trading")])
def test_일반_거래는_걸리지_않는다(country, text):
    planning_service.check_trade_controls(["US", country], {}, text=text)


def test_확인_문구에_책임_소재가_있다():
    from app.processors import trade_controls
    assert "책임은" in trade_controls.note("RU") and "수출자" in trade_controls.note("RU")


def test_시리아_문구는_완화_사실을_담는다():
    from app.processors import trade_controls
    assert "완화" in trade_controls.note("SY") and "광범위한 제재와 수출통제 대상입니다" not in trade_controls.note("SY")


def test_우회_위험_나라는_재수출_확인_문구():
    from app.processors import trade_controls
    for code in ("KZ", "KG", "AM", "GE"):
        assert trade_controls.level(code) == "watch" and "재수출" in trade_controls.note(code)


@pytest.fixture()
def made(app, create_shipment):
    create_shipment()
    with app.app_context():
        yield Shipment.query.order_by(Shipment.id.desc()).first()


def test_수정에서_바이어_국가를_제재국으로_바꿀_수_없다(made):
    form = {**shipment_service._party_snapshot(made), "buyer_country": "KP"}
    with pytest.raises(ValidationError):
        shipment_service.update_shipment(made, form)
    form["buyer_country"] = "RU"
    with pytest.raises(ValidationError) as caught:
        shipment_service.update_shipment(made, form)
    assert caught.value.code == "RESTRICTED_CONFIRM"
    shipment_service.update_shipment(made, {**form, "restricted_confirmed": "1"})
    assert made.buyer.country == "RU"
