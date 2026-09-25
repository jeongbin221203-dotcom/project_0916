"""적은 값이 화면을 옮겨 다녀도 **제자리에** 들어가는지 봅니다.

값 하나가 엉뚱한 칸으로 가면 B/L·송장에 그대로 찍히고, 도착지에서 화물을 못 찾습니다.
그래서 "서류 작성에 적은 것 → 운송 예상 견적 → Shipment → 서류" 한 줄기를 통째로 확인합니다.
"""

from __future__ import annotations

DOC = {
    "source": "document",
    "fields": {
        "exporter_name": "FORWARD CO., LTD", "exporter_address": "Seoul, Korea",
        "buyer_name": "BESTEKS DIS TICARET", "buyer_country": "TR",
        "buyer_address": "Istanbul, Turkiye",
        "buyer_email": "a@b.com", "notify_party": "SAME AS CONSIGNEE",
        "origin_code": "KRPUS", "origin_name": "부산항",
        "destination_code": "TRIST", "destination_name": "이스탄불항",
        "incoterms": "CIF", "currency": "USD",
        "requested_departure_date": "2026-11-02",
        "transport_mode": "SEA", "sea_mode": "FCL",
        "project_name": "터키 볼체인",
    },
    "items": [{"product_description": "Ball Chain", "hs_code": "7117190000",
               "quantity": "100", "length_cm": "50", "width_cm": "50", "height_cm": "50",
               "weight_per_package_kg": "350", "unit_price": "6.14", "amount": "614"}],
}


def _member(app, email="flow@example.com"):
    browser = app.test_client()
    browser.post("/auth/signup", data={"email": email, "password": "secret123",
                                       "password_confirm": "secret123"})
    return browser


def test_서류에_적은_값이_운송_예상_견적_칸으로_그대로_간다(app):
    browser = _member(app)
    browser.put("/api/work-draft", json=DOC)

    draft = browser.get("/api/work-draft/planning").get_json()["data"]
    fields = draft["fields"]

    # 자리를 바꿔 넣으면 안 되는 것들
    assert fields["origin_code"] == "KRPUS" and fields["destination_code"] == "TRIST"
    assert fields["exporter_name"] == "FORWARD CO., LTD"
    assert fields["buyer_name"] == "BESTEKS DIS TICARET"
    assert fields["buyer_address"] == "Istanbul, Turkiye"      # 주소도 따라옵니다
    assert fields["incoterms"] == "CIF" and fields["currency"] == "USD"
    assert fields["requested_departure_date"] == "2026-11-02"
    # 출발지와 도착지가 뒤바뀌지 않았는지 한 번 더
    assert fields["origin_name"] == "부산항" and fields["destination_name"] == "이스탄불항"

    item = draft["items"][0]
    assert item["product_description"] == "Ball Chain" and item["hs_code"] == "7117190000"
    assert item["quantity"] == "100" and item["weight_per_package_kg"] == "350"
    # 단가와 금액을 서로 바꿔 넣지 않습니다.
    assert item["unit_price"] == "6.14" and item["amount"] == "614"


def test_연락처는_서버에_가지_않는다(app):
    from app.models import WorkDraft

    browser = _member(app, "flow2@example.com")
    browser.put("/api/work-draft", json=DOC)
    stored = str(WorkDraft.query.one().data)
    assert "a@b.com" not in stored and "SAME AS CONSIGNEE" not in stored


def test_Shipment으로_만들면_같은_자리에_들어간다(app, create_shipment):
    """만들어진 건에서 서류 작성으로 되가져올 때도 자리가 그대로여야 합니다."""

    from app.models import User
    from app.services import document_source_service

    shipment = create_shipment()
    viewer = User.query.filter_by(email=app.config["MASTER_EMAIL"]).one()
    back = document_source_service.load(viewer, "shipment", shipment.shipment_id)["fields"]

    assert back["origin_code"] == shipment.origin_code
    assert back["destination_code"] == shipment.destination_code
    assert back["exporter_name"] == shipment.exporter_name
    if shipment.buyer:
        assert back["buyer_name"] == shipment.buyer.name
        assert back.get("buyer_address", "") == (shipment.buyer.address or "")
        assert back.get("buyer_country", "") == (shipment.buyer.country or "")


def test_서류에_찍히는_값도_같은_자리다(app, create_shipment):
    """마지막으로 서류에 찍히는 값이 Shipment의 그 칸에서 왔는지 봅니다."""

    from app.services import document_service

    shipment = create_shipment()
    reference = document_service.build_reference(shipment)

    assert reference["pol"].startswith(shipment.origin_code[:2])
    assert reference["pod"].startswith(shipment.destination_code[:2])
    assert reference["exporter_name"] == shipment.exporter_name
    assert reference["incoterms"] == shipment.incoterms
