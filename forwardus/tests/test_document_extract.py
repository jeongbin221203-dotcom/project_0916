"""올린 무역 서류(B/L·Offer Sheet…)를 읽어 서류 작성 칸을 채우는 자리."""

from __future__ import annotations

import io
from datetime import date, timedelta
from unittest.mock import patch

import pytest

from app.services import ServiceError, document_extract_service as extract
from app.services import document_start_service


def _bl(**overrides) -> dict:
    """AI가 B/L을 읽어 돌려준 것처럼 생긴 값. 스키마의 키를 모두 채웁니다."""

    party = lambda name="", address="", country="": {  # noqa: E731
        "name": name or None, "address": address or None, "country": country or None}
    raw = {
        "document_type": "bill_of_lading",
        "shipper": party("Forward Cosmetics Co., Ltd.", "Seoul, Korea", "KR"),
        "consignee": party("ABC Beauty Inc.", "Los Angeles, CA", "US"),
        "notify_party": party("SAME AS CONSIGNEE"),
        "transport_mode": "SEA",
        "incoterms": "FOB", "incoterms_place": "BUSAN",
        "currency": "USD", "total_amount": 25000,
        "payment_terms": "T/T 30 days after B/L date",
        "port_of_loading": "부산", "port_of_discharge": "로스앤젤레스",
        "vessel_name": "HMM ALGECIRAS", "voyage_no": "0012E", "bl_no": "HDMU1234567",
        "container_no": "TEMU1234567", "shipping_marks": "ABC / LA / C-NO 1-500",
        "shipment_date": None,
        "items": [{
            "product_description": "Skin care cream 50ml", "hs_code": None,
            "package_count": 500, "package_unit": "CTNS", "package_type": None,
            "gross_weight_kg": 4000, "net_weight_kg": 3500, "measurement_cbm": 30,
            "length_cm": None, "width_cm": None, "height_cm": None,
            "unit_price": 50, "amount": 25000,
        }],
        "unreadable": [],
    }
    raw.update(overrides)
    return raw


def _png() -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (300, 200), "white").save(buffer, "PNG")
    return buffer.getvalue()


def _image_pdf() -> bytes:
    """글자가 없는 PDF. 스캔한 B/L이 대개 이렇습니다."""

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (600, 800), "white").save(buffer, "PDF")
    return buffer.getvalue()


# --- 서류 칸 이름으로 옮기기 --------------------------------------------------------

def test_BL의_값을_서류_칸_이름으로_옮긴다(app):
    form = extract.to_form(_bl())
    fields = form["fields"]

    assert fields["exporter_name"] == "Forward Cosmetics Co., Ltd."
    assert fields["buyer_name"] == "ABC Beauty Inc."
    assert fields["buyer_country"] == "US"
    assert fields["notify_party"] == "SAME AS CONSIGNEE"
    assert fields["incoterms"] == "FOB"
    assert fields["currency"] == "USD"
    # 항구는 우리 목록에서 다시 찾은 코드입니다.
    assert fields["origin_code"] == "KRPUS"
    assert fields["destination_code"] == "USLAX"
    # 선박명·B/L 번호는 자리가 없어 기타 참조에 모읍니다.
    assert "HMM ALGECIRAS" in fields["other_references"]
    assert "HDMU1234567" in fields["other_references"]


def test_나라를_붙여_쓴_항구도_찾는다(app):
    """B/L은 항구 뒤에 나라를 붙입니다. 실제 서류로 읽어 보니 이 모양이 나왔습니다."""

    fields = extract.to_form(_bl(port_of_loading="BUSAN, KOREA",
                                 port_of_discharge="LOS ANGELES, CA, USA"))["fields"]

    assert fields["origin_code"] == "KRPUS"
    assert fields["destination_code"] == "USLAX"


def test_운임_조건은_결제_조건_칸에_넣지_않는다(app):
    assert "payment_terms" not in extract.to_form(_bl(payment_terms="FREIGHT PREPAID"))["fields"]
    assert "payment_terms" not in extract.to_form(_bl(payment_terms="Collect"))["fields"]
    assert extract.to_form(_bl(payment_terms="T/T 30 days"))["fields"]["payment_terms"] == "T/T 30 days"


def test_서류의_포장_단위와_총중량을_우리_칸에_맞춘다(app):
    item = extract.to_form(_bl())["items"][0]

    assert item["package_type"] == "carton"        # CTNS
    assert item["quantity"] == "500"
    # 서류는 줄 전체 총중량(4,000kg), 우리 칸은 한 포장 무게입니다.
    assert item["weight_per_package_kg"] == "8"
    assert item["net_weight_kg"] == "3500"
    assert item["amount"] == "25000"


def test_채운_칸_이름은_서류_작성_화면에_있는_것뿐이다(app):
    """화면에 없는 칸 이름을 돌려주면 조용히 버려집니다."""

    checklist = document_start_service.checklist()
    names = {field["name"] for group in checklist["groups"] for field in group["fields"]}
    item_names = {field["name"] for field in checklist["item_fields"]}
    form = extract.to_form(_bl())

    for key in form["fields"]:
        # 항구는 코드 칸(hidden)과 보이는 이름 칸이 따로입니다.
        assert key in names or key in ("origin_name", "destination_name"), key
    for key in form["items"][0]:
        assert key in item_names, key


def test_AI가_지어낸_조건과_통화는_채우지_않는다(app):
    form = extract.to_form(_bl(incoterms="FOBB", currency="XYZ", port_of_discharge="발할라"))
    fields = form["fields"]

    assert "incoterms" not in fields
    assert "currency" not in fields
    assert "destination_code" not in fields
    assert any("FOBB" in note for note in form["notes"])
    assert any("XYZ" in note for note in form["notes"])
    assert any("발할라" in note for note in form["notes"])


def test_모르는_포장_종류는_비우고_잘린_HS부호는_알린다(app):
    items = [{**_bl()["items"][0], "package_unit": "BUNDLES", "package_type": "barrel",
              "hs_code": "3304"}]
    form = extract.to_form(_bl(items=items))

    assert "package_type" not in form["items"][0]
    assert any("HS부호" in note for note in form["notes"])


def test_일부_품목만_금액이_있으면_알린다(app):
    first = _bl()["items"][0]
    items = [first, {**first, "product_description": "Toner", "amount": None}]

    form = extract.to_form(_bl(items=items))

    assert any("금액" in note and "1줄" in note for note in form["notes"])


def test_품목_금액의_합이_서류_합계와_다르면_알린다(app):
    form = extract.to_form(_bl(total_amount=30000))

    assert any("합계" in note for note in form["notes"])


def test_지난_선적일은_출발_희망일로_쓰지_않는다(app):
    """B/L의 On Board Date는 이미 지난 날입니다. 스케줄 조회에 쓰면 안 됩니다."""

    past = (date.today() - timedelta(days=3)).isoformat()
    future = (date.today() + timedelta(days=20)).isoformat()

    assert "requested_departure_date" not in extract.to_form(_bl(shipment_date=past))["fields"]
    assert extract.to_form(_bl(shipment_date=future))["fields"]["requested_departure_date"] == future


def test_치수가_없으면_직접_적으라고_알린다(app):
    notes = extract.to_form(_bl())["notes"]

    assert any("치수" in note for note in notes)


# --- 파일 읽기 --------------------------------------------------------------------

def test_이미지와_PDF만_받는다(app):
    with pytest.raises(ServiceError):
        extract.read_upload("invoice.exe", b"MZ")
    with pytest.raises(ServiceError):
        extract.read_upload("invoice.png", b"")
    with pytest.raises(ServiceError):
        extract.read_upload("invoice.png", b"not an image")


def test_글자_없는_PDF는_그림으로_바꿔_보낸다(app):
    text, images = extract.read_upload("bl.pdf", _image_pdf())

    assert text == ""
    assert len(images) == 1
    assert images[0].startswith("data:image/jpeg;base64,")


def test_큰_파일은_거절한다(app, monkeypatch):
    monkeypatch.setattr(extract, "MAX_UPLOAD_BYTES", 10)

    with pytest.raises(ServiceError):
        extract.read_upload("bl.png", _png())


# --- 창구 --------------------------------------------------------------------------

def test_올린_서류를_읽어_서류_칸_초안을_돌려준다(app, client):
    sent = {}

    def fake(messages, schema, **kwargs):
        sent.update(messages=messages, schema=schema, kwargs=kwargs)
        return {"success": True, "source": "api", "data": _bl()}

    with patch.object(extract.ai_client, "available", return_value=True), \
         patch.object(extract.ai_client, "structured_chat", side_effect=fake):
        response = client.post("/documents/extract", data={"file": (io.BytesIO(_png()), "bl.png")},
                               content_type="multipart/form-data")

    body = response.get_json()
    assert response.status_code == 200, body
    data = body["data"]
    assert data["document_type"] == "bill_of_lading"
    assert data["form"]["fields"]["buyer_name"] == "ABC Beauty Inc."
    # HS부호가 없는 품목은 간편 검색 창이 그 품명으로 찾도록 넘깁니다.
    assert data["hs_queries"] == ["Skin care cream 50ml"]
    assert "품목 가로(cm)" in data["missing"]
    # 그림은 Vision 조각으로 가고, 모양이 정해진 JSON으로 받습니다.
    parts = sent["messages"][1]["content"]
    assert any(part["type"] == "image_url" for part in parts)
    assert sent["kwargs"]["name"] == "trade_document_extract"
    assert sent["schema"]["additionalProperties"] is False


def test_키가_없으면_읽지_않고_알린다(app, client):
    with patch.object(extract.ai_client, "available", return_value=False):
        response = client.post("/documents/extract", data={"file": (io.BytesIO(_png()), "bl.png")},
                               content_type="multipart/form-data")

    assert response.status_code == 400
    assert "AI_API_KEY" in response.get_json()["message"]


def test_파일_없이_부르면_거절한다(client):
    response = client.post("/documents/extract", data={}, content_type="multipart/form-data")

    assert response.status_code == 400
    assert response.get_json()["success"] is False


def test_AI가_실패하면_짐작하지_않고_실패를_알린다(app, client):
    with patch.object(extract.ai_client, "available", return_value=True), \
         patch.object(extract.ai_client, "structured_chat",
                      return_value={"success": False, "error_code": "API_TIMEOUT",
                                    "source": "api", "message": "timeout"}):
        response = client.post("/documents/extract", data={"file": (io.BytesIO(_png()), "bl.png")},
                               content_type="multipart/form-data")

    assert response.status_code == 502
    assert "시간" in response.get_json()["message"]


# --- 화면 연결 ----------------------------------------------------------------------

def test_서류_작성_화면에_올리기_칸과_Notify_Party_칸이_있다(client):
    html = client.get("/documents/new").get_data(as_text=True)

    assert "data-doc-upload" in html
    assert "doc_upload.js" in html
    assert 'name="notify_party"' in html


def test_HS_간편_검색_창은_어느_화면에나_있고_Cargo와_같은_창구를_쓴다(client):
    for path in ("/", "/documents/new", "/planning/new", "/shipments"):
        html = client.get(path).get_data(as_text=True)
        assert "data-hs-modal" in html, path
        assert "hs_search.js" in html, path
        assert "/planning/api/hs-codes" in html, path


def test_상담_답변은_HS_간편_검색_링크를_쓰도록_안내받는다():
    from app.services import support_chat_service

    assert "(#hs:" in support_chat_service.SYSTEM_PROMPT
    # 좁은 상담 창은 링크를 그리지 않으니 짧은 프롬프트에는 넣지 않습니다.
    assert "#hs" not in support_chat_service.BRIEF_SYSTEM_PROMPT
