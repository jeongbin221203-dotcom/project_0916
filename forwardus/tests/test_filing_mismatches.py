"""값은 다 찼는데 **앞뒤가 안 맞는** 것을 관세사에게 넘기기 전에 짚는가.

비어 있는 칸은 사람이 바로 알아챕니다. 이건 다 채워져 있어서 안 보이고,
그대로 신고된 뒤에 정정해야 합니다.

⑥ 검사에서 "말없이 통과"로 남아 있던 것들입니다. (2026-09-27)
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.extensions import db
from app.services import customs_filing_service


def _rows(shipment):
    return customs_filing_service.filing_sheet(shipment)["mismatches"]


def test_멀쩡한_건에는_아무것도_안_뜬다(create_shipment):
    """헛경보가 뜨면 사람이 경고를 안 믿게 됩니다."""

    assert not _rows(create_shipment())


def test_받는_분_나라와_도착지가_다르면_짚는다(create_shipment):
    shipment = create_shipment(buyer={"name": "BESTEKS DIS TICARET", "country": "TR"})
    text = " ".join(_rows(shipment))
    assert "TR" in text and "US" in text
    assert "삼각무역" in text, "막지 않고 왜 그럴 수 있는지도 적어야 합니다"


def test_도착이_출발보다_빠르면_짚는다(create_shipment):
    shipment = create_shipment()
    shipment.eta = shipment.etd - timedelta(days=3)
    db.session.commit()
    assert any("있을 수 없는 일정" in row for row in _rows(shipment))


def test_바이어_요청일보다_늦으면_며칠_늦는지_적는다(create_shipment):
    shipment = create_shipment()
    shipment.buyer_required_date = shipment.eta - timedelta(days=7)
    db.session.commit()
    text = " ".join(_rows(shipment))
    assert "7일 늦습니다" in text


def test_출발_희망일이_지난_날이면_짚는다(create_shipment):
    shipment = create_shipment()
    shipment.requested_departure_date = date.today() - timedelta(days=30)
    db.session.commit()
    assert any("이미 지난 날" in row for row in _rows(shipment))


def test_화물_준비일이_출항일보다_늦으면_짚는다(create_shipment):
    shipment = create_shipment()
    shipment.cargo_ready_date = shipment.etd + timedelta(days=2)
    db.session.commit()
    assert any("싣지 못합니다" in row for row in _rows(shipment))


def test_밀도가_말이_안_되면_짚는다(create_shipment, cargo_input):
    """포장당 중량 칸에 전체 중량을 적는 것이 가장 흔한 실수입니다.
    그러면 운임 기준이 100배 틀립니다."""

    shipment = create_shipment(cargo={**cargo_input, "quantity": 10,
                                      "length_cm": 10, "width_cm": 10, "height_cm": 10,
                                      "weight_per_package_kg": 20, "net_weight_kg": None})
    text = " ".join(_rows(shipment))
    assert "1CBM당" in text and "품목 1" in text


def test_그대로_넘기기_글에도_적힌다(create_shipment):
    """관세사가 화면을 안 보고 글만 복사해 가도 보여야 합니다."""

    shipment = create_shipment(buyer={"name": "BESTEKS DIS TICARET", "country": "TR"})
    text = customs_filing_service.as_text(customs_filing_service.filing_sheet(shipment))
    assert "앞뒤가 안 맞는 것" in text


def test_화면에도_나온다(client, create_shipment):
    shipment = create_shipment(buyer={"name": "BESTEKS DIS TICARET", "country": "TR"})
    response = client.get(f"/documents/{shipment.shipment_id}/customs-filing")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "앞뒤가 안 맞습니다" in body
