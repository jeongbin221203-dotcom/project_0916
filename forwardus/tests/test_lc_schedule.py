"""신용장(L/C) 날짜로 안전한 선적예정일을 내는 자리.

L/C는 최종선적일(44C)과 유효기일(31D)을 함께 지켜야 대금을 받습니다. 유효기일에서
서류 제시기간을 뺀 날이 최종선적일보다 빠른 경우가 흔해서, 둘 중 빠른 날이 진짜 마감입니다.
"""

from __future__ import annotations

import io
from datetime import date, timedelta
from unittest.mock import patch

import pytest

from app.processors import lc_schedule
from app.services import document_extract_service as extract

TODAY = date(2026, 9, 23)


def plan(**kwargs):
    return lc_schedule.plan(today=TODAY, **kwargs)


# --- 마감일 계산 -----------------------------------------------------------------------

def test_유효기일에서_제시기간을_뺀_날이_더_빠르면_그_날이_마감이다():
    result = plan(latest_shipment=date(2026, 11, 20), expiry=date(2026, 11, 30))

    # 유효기일 11-30 − 제시기간 21일 = 11-09. 최종선적일(11-20)보다 빠릅니다.
    assert result["deadline"] == date(2026, 11, 9)
    assert result["deadline_reason"] == "expiry"
    assert any("21" in note and "2026-11-09" in note for note in result["notes"])


def test_최종선적일이_더_빠르면_그_날이_마감이다():
    result = plan(latest_shipment=date(2026, 10, 20), expiry=date(2026, 12, 31))

    assert result["deadline"] == date(2026, 10, 20)
    assert result["deadline_reason"] == "latest_shipment"


def test_L_C에_적힌_제시기간을_그대로_쓴다():
    result = plan(latest_shipment=date(2026, 12, 1), expiry=date(2026, 11, 30), presentation=7)

    assert result["presentation_days"] == 7 and result["presentation_stated"] is True
    assert result["deadline"] == date(2026, 11, 23)          # 11-30 − 7일
    assert not any("UCP" in note for note in result["notes"])


@pytest.mark.parametrize("value", [0, -5, 400, "많이", None, ""])
def test_이상한_제시기간은_21일로_본다(value):
    result = plan(expiry=date(2026, 11, 30), presentation=value)

    assert result["presentation_days"] == lc_schedule.DEFAULT_PRESENTATION_DAYS
    assert result["presentation_stated"] is False
    assert any("UCP 600" in note for note in result["notes"])


def test_날짜가_하나도_없으면_계산하지_않는다():
    assert plan() is None
    assert plan(latest_shipment=None, expiry=None, presentation=10) is None


def test_하나만_있어도_계산한다():
    only_shipment = plan(latest_shipment=date(2026, 10, 30))
    assert only_shipment["deadline"] == date(2026, 10, 30) and only_shipment["expiry"] is None
    only_expiry = plan(expiry=date(2026, 10, 30))
    assert only_expiry["deadline"] == date(2026, 10, 9)


# --- 권하는 선적예정일 --------------------------------------------------------------------

def test_여유를_두고_선적예정일을_잡는다():
    result = plan(latest_shipment=date(2026, 11, 20), expiry=date(2027, 1, 31))

    assert result["recommended_etd"] == date(2026, 11, 17)   # 마감 − 여유 3일(해상)
    assert result["cargo_ready_by"] == date(2026, 11, 13)    # 수출통관 2일 + 선적 마감 2일
    assert result["presentation_by"] == date(2026, 12, 8)    # 선적 + 21일
    assert result["level"] == "ok" and result["feasible"] is True


def test_항공은_여유와_준비_기간이_짧다():
    sea = plan(latest_shipment=date(2026, 11, 20), transport_mode="SEA")
    air = plan(latest_shipment=date(2026, 11, 20), transport_mode="AIR")

    assert air["recommended_etd"] > sea["recommended_etd"]
    assert air["cargo_ready_by"] > sea["cargo_ready_by"]


def test_마감이_가까우면_여유를_줄이고_촉박하다고_알린다():
    result = plan(latest_shipment=TODAY + timedelta(days=5))

    # 준비(통관 2일 + 마감 2일)만 겨우 되는 날짜라 여유 3일을 두지 못합니다.
    assert result["recommended_etd"] == TODAY + timedelta(days=4)
    assert result["feasible"] is True and result["level"] in ("late", "tight")
    assert any("촉박" in note for note in result["notes"])


def test_이미_늦었으면_연장을_권한다():
    result = plan(latest_shipment=TODAY - timedelta(days=1), expiry=TODAY + timedelta(days=20))

    assert result["feasible"] is False and result["days_left"] < 0
    assert any("Amendment" in note for note in result["notes"])


@pytest.mark.parametrize("shipment, expiry, days", [
    (date(2026, 11, 1), date(2026, 11, 10), None),
    (date(2026, 11, 20), date(2026, 11, 30), 7),
    (date(2026, 12, 31), date(2026, 10, 15), None),      # 유효기일이 더 빠른 L/C
])
def test_서류_제시일은_유효기일을_넘지_않는다(shipment, expiry, days):
    result = plan(latest_shipment=shipment, expiry=expiry, presentation=days)

    assert result["presentation_by"] <= expiry
    assert result["recommended_etd"] <= result["deadline"]


def test_화면으로_보낼_때는_날짜를_글자로_바꾼다():
    text = lc_schedule.as_text(plan(latest_shipment=date(2026, 11, 20)))

    assert text["deadline"] == "2026-11-20" and text["expiry"] == ""
    assert lc_schedule.as_text(None) is None


# --- 올린 서류에서 자동으로 ----------------------------------------------------------------

def _lc_raw(**overrides) -> dict:
    party = {"name": "FORWARD", "address": "Seoul", "country": "KR"}
    raw = {
        "document_type": "letter_of_credit", "shipper": party, "consignee": party,
        "notify_party": {"name": None, "address": None, "country": None},
        "transport_mode": "SEA", "incoterms": "CIF", "incoterms_place": "LA",
        "currency": "USD", "total_amount": 50000, "payment_terms": "L/C at sight",
        "port_of_loading": "부산", "port_of_discharge": "로스앤젤레스",
        "vessel_name": None, "voyage_no": None, "bl_no": None, "container_no": None,
        "shipping_marks": None, "shipment_date": None,
        "lc_no": "M04CE9012NU00123",
        "lc_latest_shipment_date": "2026-11-20", "lc_expiry_date": "2026-11-30",
        "lc_presentation_days": None, "lc_partial_shipment": "prohibited",
        "lc_transshipment": "prohibited",
        "items": [{"product_description": "Cream", "hs_code": None, "package_count": 500,
                   "package_unit": "CTNS", "package_type": None, "gross_weight_kg": 4000,
                   "net_weight_kg": 3500, "measurement_cbm": 30, "length_cm": 40,
                   "width_cm": 30, "height_cm": 25, "unit_price": 100, "amount": 50000}],
        "unreadable": [],
    }
    raw.update(overrides)
    return raw


def _png() -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (200, 100), "white").save(buffer, "PNG")
    return buffer.getvalue()


def _upload(client, raw):
    with patch.object(extract.ai_client, "available", return_value=True), \
         patch.object(extract.ai_client, "structured_chat",
                      return_value={"success": True, "source": "api", "data": raw}), \
         patch.object(extract.bank_redaction, "ocr_available", return_value=True), \
         patch.object(extract.bank_redaction, "redact_image",
                      side_effect=lambda png: {"image": png, "found": 0}):
        return client.post("/documents/extract", data={"file": (io.BytesIO(_png()), "lc.png")},
                           content_type="multipart/form-data").get_json()["data"]


def test_L_C를_올리면_선적예정일이_저절로_채워진다(app, client):
    data = _upload(client, _lc_raw())

    assert data["document_label"] == "신용장 (L/C)"
    schedule = data["lc_schedule"]
    assert schedule["deadline"] == "2026-11-09"              # 유효기일 − 21일
    assert data["form"]["fields"]["requested_departure_date"] == schedule["recommended_etd"]
    assert data["form"]["fields"]["lc_no"] == "M04CE9012NU00123"
    # 운송 계획으로 넘길 값도 함께 실립니다. (화면에 칸이 없는 값)
    assert data["form"]["lc"] == {"lc_latest_shipment_date": "2026-11-20",
                                  "lc_expiry_date": "2026-11-30"}
    assert any("선적예정일을" in note and schedule["recommended_etd"] in note
               for note in data["notes"])
    assert any("분할선적" in note for note in data["notes"])
    assert any("환적" in note for note in data["notes"])
    labels = {row["label"]: row["value"] for row in data["summary"]}
    assert labels["L/C 최종선적일"] == "2026-11-20" and labels["L/C 유효기일"] == "2026-11-30"


def test_L_C_날짜가_없는_서류는_예전처럼_동작한다(app, client):
    data = _upload(client, _lc_raw(document_type="bill_of_lading", lc_latest_shipment_date=None,
                                   lc_expiry_date=None, lc_no=None))

    assert data["lc_schedule"] is None
    assert "requested_departure_date" not in data["form"]["fields"]
    assert "lc" not in data["form"]


def test_읽지_못한_L_C_날짜는_알려_준다(app, client):
    data = _upload(client, _lc_raw(lc_latest_shipment_date="언젠가", lc_expiry_date=None))

    assert data["lc_schedule"] is None
    assert any("날짜로 읽지 못했습니다" in note for note in data["notes"])


# --- 운송 계획으로 이어지기 ----------------------------------------------------------------

def test_운송_계획이_마감일을_다시_계산해_받는다(app):
    browser = app.test_client()
    browser.post("/auth/signup", data={"email": "lc@example.com", "password": "secret123",
                                       "password_confirm": "secret123"})
    browser.put("/api/work-draft", json={"source": "upload", "items": [], "fields": {
        "lc_latest_shipment_date": "2026-11-20", "lc_expiry_date": "2026-11-30",
        "transport_mode": "SEA", "origin_code": "KRPUS"}})

    lc = browser.get("/api/work-draft/planning").get_json()["data"]["lc"]
    assert lc["deadline"] == "2026-11-09" and lc["recommended_etd"] <= "2026-11-09"
    assert lc["presentation_by"] and lc["notes"]


def test_스케줄_카드가_마감_초과를_표시한다():
    from pathlib import Path

    js = (Path(__file__).parent.parent / "app/static/js/planning.js").read_text(encoding="utf-8")
    assert "function lcBadge" in js and "L/C 마감" in js
    assert "${lcBadge(s.etd)}" in js
    upload = (Path(__file__).parent.parent / "app/static/js/doc_upload.js").read_text(encoding="utf-8")
    assert "upload_lc" in upload and "L/C 선적 마감" in upload
