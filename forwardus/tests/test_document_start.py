"""시작 화면에서 서류까지.

여기서 지키려는 것은 "서류가 나오는가"가 아니라 **"낼 수 있는 서류가 나오는가"**
입니다. 칸이 비거나 숫자가 어긋난 서류는 세관에서 되돌아옵니다.
"""

from __future__ import annotations

import pytest

from app.services import document_service, document_start_service as start, planning_service
from app.validators import ValidationError

ITEMS = [
    {"product_description": "샴푸", "hs_code": "3305100000", "package_type": "carton",
     "quantity": "20", "length_cm": "40", "width_cm": "30", "height_cm": "25",
     "weight_per_package_kg": "250", "net_weight_kg": "4000", "amount": "3000"},
    {"product_description": "비누", "package_type": "drum",
     "quantity": "50", "length_cm": "30", "width_cm": "30", "height_cm": "40",
     "weight_per_package_kg": "150", "net_weight_kg": "6000", "amount": "5000"},
]

FILLED = {
    "exporter_name": "Forward Cosmetics Co., Ltd.", "exporter_address": "Seoul, Korea",
    "buyer_name": "ABC Beauty Inc.", "buyer_country": "US", "buyer_address": "Los Angeles, CA",
    "consignee_city_zip": "Los Angeles, CA 90001", "attention": "Mr. Kim",
    "transport_mode": "SEA", "sea_mode": "LCL",
    "origin_code": "KRPUS", "destination_code": "USLAX",
    "requested_departure_date": "2026-11-05", "incoterms": "FOB", "currency": "USD",
    "payment_terms": "T/T 30 days after B/L date", "lc_no": "LC-2026-77",
    "buyer": "ABC Trading Ltd.", "other_references": "Contract 2026-11",
    "shipping_marks": "ABC / LA / C-NO 1-20", "remarks": "Fragile",
    "customer_order_no": "PO-9912", "date_ordered": "2026-10-01",
    "container_no": "TEMU1234567", "comments": "Stack max 3",
    "items": ITEMS,
}


@pytest.fixture()
def payload(app):
    """스케줄은 실제로 조회해서 고릅니다. 화면이 하는 일과 같습니다."""

    body = dict(FILLED)
    found = planning_service.search_schedules(
        {**body, "project_name": "스케줄 조회", "cargo": {"items": ITEMS}})
    return {**body, "schedule_id": found["items"][0]["schedule_id"]}


# --- 금액 ------------------------------------------------------------------------

def test_금액을_일부만_적으면_막는다(app, payload):
    """실제로 났던 일입니다.

    품목 두 줄 중 하나만 금액을 적어서, 총액 3,000인데 한 줄이 5,000인
    송장이 나왔습니다. 줄의 합과 총액이 어긋난 송장은 낼 수 없습니다.
    """

    half = {**payload, "items": [ITEMS[0], {**ITEMS[1], "amount": ""}]}

    with pytest.raises(ValidationError) as caught:
        start.create(half)

    assert "2번" in str(caught.value)


def test_금액을_하나도_안_적으면_적으라고_한다(app, payload):
    empty = {**payload, "items": [{**item, "amount": ""} for item in ITEMS]}

    with pytest.raises(ValidationError):
        start.create(empty)


def test_송장_줄의_합이_총액과_맞는다(app, payload):
    result = start.create(payload)
    shipment = _shipment(result)
    invoice = document_service.get_document(shipment, "commercial_invoice")

    lines = sum(float(row["amount"] or 0) for row in invoice.data["items"])
    assert lines == float(invoice.data["invoice_value"]) == 8000.0


# --- 서류에만 있는 칸 --------------------------------------------------------------

def test_서류에만_쓰는_칸이_실제로_서류에_들어간다(app, payload):
    """Shipment에는 자리가 없어 서류에 직접 넣는 칸들입니다."""

    result = start.create(payload)
    shipment = _shipment(result)
    invoice = document_service.get_document(shipment, "commercial_invoice")
    packing = document_service.get_document(shipment, "packing_list")

    assert invoice.data["lc_no"] == "LC-2026-77"
    assert invoice.data["payment_terms"] == "T/T 30 days after B/L date"
    assert invoice.data["shipping_marks"] == "ABC / LA / C-NO 1-20"
    assert packing.data["consignee_city_zip"] == "Los Angeles, CA 90001"
    assert packing.data["container_no"] == "TEMU1234567"
    assert packing.data["comments"] == "Stack max 3"


def test_우리가_받는_칸은_서류가_받아_주는_칸이어야_한다():
    """서식 칸 이름이 바뀌면 조용히 버려집니다. 그걸 여기서 잡습니다."""

    from app.validators.document_validator import EDITABLE_FIELDS

    for name in start.INVOICE_EXTRAS + start.PACKING_EXTRAS:
        assert name in EDITABLE_FIELDS, name


def test_체크리스트의_칸이_모두_서식에_있는_칸이다():
    """화면이 묻는 것과 서류가 쓰는 것이 어긋나면 헛수고를 시킵니다."""

    known = set(document_service.DOCUMENT_FIELDS["commercial_invoice"])
    known |= set(document_service.DOCUMENT_FIELDS["packing_list"])
    # Shipment를 만드는 데 쓰는 칸은 서식 이름과 다릅니다. 그것만 빼고 봅니다.
    # buyer_required_date는 서류에 안 나오고 납기를 맞출 때만 씁니다.
    plan_fields = {"exporter_name", "exporter_address", "buyer_name", "buyer_country",
                   "buyer_address", "buyer_email", "transport_mode", "sea_mode",
                   "origin_code", "destination_code", "requested_departure_date",
                   "buyer_required_date"}

    for group in start.checklist()["groups"]:
        for field in group["fields"]:
            name = field["name"]
            assert name in known or name in plan_fields, name


def test_빈_칸을_숨기지_않고_알려_준다(app, payload):
    thin = {key: value for key, value in payload.items()
            if key not in ("lc_no", "shipping_marks", "remarks", "comments")}

    result = start.create(thin)

    labels = [row["label"] for row in result["still_empty"]]
    assert labels
    assert any("Shipping Marks" in label or "화인" in label or "Marks" in label
               for label in labels), labels


# --- 라우트와 화면 ----------------------------------------------------------------

def test_라우트가_서류를_만들고_주소를_돌려준다(app, client, payload):
    response = client.post("/documents/start", json=payload)

    body = response.get_json()
    assert body["success"] is True
    assert body["data"]["shipment_id"].startswith("EXP-")
    assert client.get(body["data"]["url"]).status_code == 200


def test_빈_내용을_보내면_거절한다(app, client):
    response = client.post("/documents/start", json={})

    assert response.status_code == 400
    assert response.get_json()["success"] is False


def test_서류_작성_화면에_칸이_펼쳐져_있다(client):
    """칸은 홈이 아니라 사이드바의 서류 작성 화면에 있습니다."""

    html = client.get("/documents/new").get_data(as_text=True)

    assert "data-doc-panel" in html
    # 서식이 요구하는 칸 이름이 실제로 화면에 있어야 합니다.
    for name in ("exporter_name", "buyer_name", "payment_terms", "shipping_marks", "lc_no"):
        assert f'name="{name}"' in html, name


def _shipment(result: dict):
    from app.repositories import shipment_repository

    return shipment_repository.get_by_shipment_id(result["shipment_id"])
