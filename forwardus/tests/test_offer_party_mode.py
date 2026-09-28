"""서류에 적힌 것은 **다시 묻지 않습니다.** (2026-09-28)

화면에 칸이 있는데 서류를 읽어도 비어 있던 것들입니다.
  도시 · 주 · 우편번호 · Buyer 이메일 · 담당자(ATTENTION)
  해상 운송 방식 (FCL / LCL)

Firm Offer 에는 이렇게 다 적혀 있었습니다.
    BESTEKS DIS TICARET LTD. STI
    31 Example Trade Street, Floor 5, Osmanbey
    Sisli, Istanbul 34363, Turkey
    Attention: Deniz Kaya / Import Manager
    Email: purchasing@besteks.example
그런데 당사자 정보를 **이름·주소·나라 셋만** 받고 있었습니다.
"""

from __future__ import annotations

import pytest

from app.services import document_extract_service as extract


BUYER = {"name": "BESTEKS DIS TICARET LTD. STI",
         "address": "31 Example Trade Street, Floor 5, Osmanbey",
         "city_zip": "Sisli, Istanbul 34363", "country": "TR",
         "email": "purchasing@besteks.example",
         "attention": "Deniz Kaya / Import Manager"}


def test_바이어_상세를_칸에_넣는다(app):
    fields = extract.to_form({"consignee": BUYER})["fields"]
    assert fields["buyer_name"] == BUYER["name"]
    assert fields["buyer_address"] == BUYER["address"]
    assert fields["consignee_city_zip"] == "Sisli, Istanbul 34363"
    assert fields["buyer_email"] == "purchasing@besteks.example"
    assert fields["attention"] == "Deniz Kaya / Import Manager"


def test_없는_칸은_비워_둔다(app):
    """서류에 안 적힌 것을 지어내지 않습니다."""

    fields = extract.to_form({"consignee": {"name": "ABC", "address": "Seoul"}})["fields"]
    for key in ("consignee_city_zip", "buyer_email", "attention"):
        assert not fields.get(key), key


# --- 해상 운송 방식 -------------------------------------------------------------------

def _line(**extra) -> dict:
    return {"product_description": "우산", "pieces": 1200, "units_per_package": 50,
            "piece_unit": "PCS", "package_unit": "CTN", "unit_price": 4.5,
            "amount": 5400, **extra}


UMBRELLA = [
    _line(length_cm=60, width_cm=40, height_cm=35, gross_weight_kg=408),
    _line(pieces=800, amount=5200, unit_price=6.5,
          length_cm=95, width_cm=35, height_cm=30, gross_weight_kg=400),
]


def test_치수가_있으면_FCL_LCL_을_정한다(app):
    """짐작이 아니라 **계산**입니다. 부피와 무게로 정해집니다.

    3.612 CBM 은 20피트 컨테이너의 13%밖에 안 됩니다. LCL 이 맞습니다.
    """

    out = extract.to_form({"transport_mode": "SEA", "items": UMBRELLA})
    assert out["fields"]["sea_mode"] == "LCL"
    assert any("3.612" in note and "LCL" in note for note in out["notes"]), out["notes"]


def test_치수가_없으면_정하지_않는다(app):
    """**반쪽 숫자가 더 위험합니다.**

    치수를 모르는 채 FCL 이라고 했다가 컨테이너를 통째로 빌리면 큰돈이 나갑니다.
    """

    out = extract.to_form({"transport_mode": "SEA", "items": [_line()]})
    assert not out["fields"].get("sea_mode")


def test_한_줄이라도_모르면_정하지_않는다(app):
    """줄 하나만 세면 화물 전체가 아닙니다."""

    out = extract.to_form({"transport_mode": "SEA",
                           "items": [UMBRELLA[0], _line()]})
    assert not out["fields"].get("sea_mode")


def test_항공이면_해상_방식을_안_정한다(app):
    out = extract.to_form({"transport_mode": "AIR", "items": UMBRELLA})
    assert not out["fields"].get("sea_mode")


@pytest.mark.parametrize("cbm_each,count,kg,want", [
    (60 * 40 * 35, 24, 17, "LCL"),          # 우산 화물 — 컨테이너를 못 채웁니다
    (100 * 100 * 100, 30, 500, "FCL"),      # 30 CBM — 컨테이너가 쌉니다
])
def test_부피에_따라_갈린다(app, cbm_each, count, kg, want):
    line = _line(length_cm=cbm_each ** (1 / 3) if False else 0)
    # 치수를 직접 줍니다 (위 계산은 쓰지 않습니다)
    if want == "LCL":
        line = _line(length_cm=60, width_cm=40, height_cm=35,
                     gross_weight_kg=kg * count, pieces=count * 50)
    else:
        line = _line(length_cm=100, width_cm=100, height_cm=100,
                     gross_weight_kg=kg * count, pieces=count * 50)
    line["units_per_package"] = 50
    out = extract.to_form({"transport_mode": "SEA", "items": [line]})
    assert out["fields"].get("sea_mode") == want, out["notes"]
