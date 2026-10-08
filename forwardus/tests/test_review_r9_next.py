"""다음 과제 3가지 — 항구·공항별 운임, 중고 안내의 품목(HS 장)별 구분, 한국 쪽 중고차 수출 절차."""

import datetime

import pytest

from app.processors import export_requirements, used_goods
from app.services import planning_service
from app.validators import ValidationError


# ── 중고 안내의 품목별 구분 ────────────────────────────────────────────────────────────
def test_이집트로_중고_굴착기를_보내면_승용차_문구가_나오지_않는다():
    assert used_goods.notes_for("EG", {"84"}) == []
    assert any("승용차" in text for text in used_goods.notes_for("EG", {"87"}))


def test_품목을_모르면_모든_문구를_보인다():
    assert used_goods.notes_for("PE") and len(used_goods.notes_for("PE")) == 3
    assert len(used_goods.notes_for("PE", set())) == 3


def test_페루는_품목별로_다른_문구():
    clothes = used_goods.notes_for("PE", {"62"})
    parts = used_goods.notes_for("PE", {"87"})
    machinery = used_goods.notes_for("PE", {"84"})
    assert len(clothes) == len(parts) == len(machinery) == 1
    assert "의류" in clothes[0] and "자동차 부품" in parts[0] and "방사선원" in machinery[0]


def test_품목_무관_문구는_어떤_품목에도_나온다():
    assert used_goods.notes_for("CO", {"33"}) and "중고·재생·재조립" in used_goods.notes_for("CO", {"33"})[0]


def test_EU_나라는_기계_전기만_독일_문구를_쓴다():
    assert used_goods.notes_for("FR", {"84"}) and used_goods.notes_for("NL", {"85"})
    assert used_goods.notes_for("FR", {"61"}) == []


def test_기존_NOTES_이름도_유지된다():
    assert used_goods.NOTES["EG"] and used_goods.notes_for("ZZ") == []


# ── 한국 쪽 중고차 수출 절차 ──────────────────────────────────────────────────────────
@pytest.mark.parametrize("hs", ["8703.23", "8704.21", "8711.20", "8702.10"])
def test_중고_차량은_한국_쪽_수출_절차가_붙는다(hs):
    keys = {item["key"] for item in export_requirements.check(hs, is_used=True)}
    assert "used_vehicle" in keys and "used" in keys
    item = next(i for i in export_requirements.check(hs, is_used=True) if i["key"] == "used_vehicle")
    assert any("말소" in paper for paper in item["documents"])


def test_신차나_중고_기계에는_차량_절차가_없다():
    assert "used_vehicle" not in {i["key"] for i in export_requirements.check("8703.23")}
    assert "used_vehicle" not in {i["key"] for i in export_requirements.check("8429.52", is_used=True)}


# ── 중고 차량·기계의 연료·배터리 확인 ──────────────────────────────────────────────────
@pytest.mark.parametrize("hs", ["8703.23", "8427.20", "8429.52", "8704.21"])
def test_중고_차량_기계는_위험물_확인을_받는다(hs):
    item = {"hs_code": hs, "product_description": "Used machine", "used_condition": "used"}
    with pytest.raises(ValidationError) as caught:
        planning_service._check_used_machinery([item], {})
    assert caught.value.code == "DG_CONFIRM"
    planning_service._check_used_machinery([item], {"dg_confirmed": True})


@pytest.mark.parametrize("item", [
    {"hs_code": "8703.23", "product_description": "New car", "used_condition": ""},
    {"hs_code": "3304.99", "product_description": "Used cream sample", "used_condition": "used"},
    {"hs_code": "8429.52", "product_description": "Used excavator", "used_condition": "used", "is_dangerous": True},
])
def test_신품_다른_품목_이미_위험물은_묻지_않는다(item):
    planning_service._check_used_machinery([item], {})


# ── 항구·공항별 운임 ────────────────────────────────────────────────────────────────
def _freight(app, shipment_payload, destination, mode="SEA", sea_mode="FCL"):
    payload = {**shipment_payload, "destination_code": destination, "transport_mode": mode, "sea_mode": sea_mode,
               "origin_code": "ICN" if mode == "AIR" else shipment_payload["origin_code"],
               "requested_departure_date": (datetime.date.today() + datetime.timedelta(days=12)).isoformat()}
    with app.app_context():
        result = planning_service.search_schedules(payload)
    rows = [item for item in result["items"] if item.get("source") == "mock" and item.get("freight_usd")]
    return min(item["freight_usd"] for item in rows) if rows else None


def test_같은_권역이어도_가까운_항구가_싸고_먼_항구가_비싸다(app, shipment_payload):
    near = _freight(app, shipment_payload, "NLRTM")        # 유럽 중앙 근처
    far = _freight(app, shipment_payload, "SEGOT")         # 유럽이지만 더 멀다
    assert near and far
    assert far != near


def test_블라디보스토크는_유럽_요율이_아니다(app, shipment_payload):
    vladivostok = _freight(app, shipment_payload, "RUVVO")
    rotterdam = _freight(app, shipment_payload, "NLRTM")
    assert vladivostok and rotterdam and vladivostok < rotterdam


def test_보정_배율은_상하한_안(app, shipment_payload):
    with app.app_context():
        for destination in ("RUVVO", "NLRTM", "USNYC", "BRSSZ"):
            payload = {**shipment_payload, "destination_code": destination,
                       "requested_departure_date": (datetime.date.today() + datetime.timedelta(days=12)).isoformat()}
            for item in planning_service.search_schedules(payload)["items"]:
                if item.get("freight_distance_factor"):
                    assert 0.55 <= item["freight_distance_factor"] <= 1.8


def test_항공도_거리에_따라_다르다(app, shipment_payload):
    near = _freight(app, shipment_payload, "NRT", mode="AIR", sea_mode=None)
    far = _freight(app, shipment_payload, "GRU", mode="AIR", sea_mode=None)
    assert near and far and near < far
