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

    # 운송 예상 견적 화면이 쓰는 임시저장 모양으로 옵니다. (planning.js와 같은 모양)
    draft = browser.get("/api/work-draft/planning").get_json()["data"]

    # 출발지와 도착지가 뒤바뀌지 않았는지가 가장 중요합니다.
    assert draft["origin"]["code"] == "KRPUS" and draft["origin"]["name"] == "부산항"
    # 이름은 우리 항구 목록의 표준 이름으로 바뀔 수 있습니다. 코드가 맞는 것이 중요합니다.
    assert draft["destination"]["code"] == "TRIST" and draft["destination"]["name"]
    assert draft["incoterms"] == "CIF"
    assert draft["departure_date"] == "2026-11-02"
    assert draft["transport_mode"] == "SEA" and draft["sea_mode"] == "FCL"

    fields = draft["fields"]
    assert fields["exporter_name"] == "FORWARD CO., LTD"
    assert fields["buyer_name"] == "BESTEKS DIS TICARET"
    assert fields["buyer_address"] == "Istanbul, Turkiye"      # 주소도 따라옵니다
    assert fields["currency"] == "USD"
    # 첫 품목은 화면 칸으로 펴서 옵니다.
    assert fields["product_description"] == "Ball Chain" and fields["hs_code"] == "7117190000"
    assert fields["quantity"] == "100" and fields["weight_per_package_kg"] == "350"
    # 금액은 합계로 따로 갑니다. 단가 자리에 금액이 들어가면 안 됩니다.
    assert fields["invoice_value"] == "614"
    assert "unit_price" not in fields


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

    # 서류에는 "이름 (코드)" 모양으로 찍힙니다. 코드가 제자리에 있는지 봅니다.
    assert shipment.origin_code in reference["pol"]
    assert shipment.destination_code in reference["pod"]
    assert reference["pol"] != reference["pod"]
    # 서류의 칸 이름은 exporter·consignee입니다. 값이 그 자리에 들어가야 합니다.
    assert reference["exporter"] == shipment.exporter_name
    assert reference["exporter_address"] == shipment.exporter_address
    assert reference["incoterms"] == shipment.incoterms
    if shipment.buyer:
        assert reference["consignee"] == shipment.buyer.name
        # 수출자 주소가 수하인 주소 칸으로 가면 안 됩니다.
        assert reference["consignee_address"] != reference["exporter_address"]


def test_탭만_바꿀_때는_화면을_끌어올리지_않는다():
    """질문에 답이 오면 그 질문을 맨 위에 붙입니다. 하지만 탭만 바꾼 것은 답이 아닙니다.

    보던 자리를 그대로 둬야 읽던 글을 이어서 읽습니다.
    """

    from pathlib import Path

    js = (Path(__file__).parent.parent / "app/static/js/home.js").read_text(encoding="utf-8")
    assert "function say(kind, text, { restoring = false, pin = true } = {})" in js
    assert 'say("bot", action.opener, { pin: false })' in js
    # 진짜 답에는 그대로 붙입니다.
    assert 'kind !== "bot wait" && pin' in js
