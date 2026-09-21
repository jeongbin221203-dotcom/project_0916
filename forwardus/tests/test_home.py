"""시작 화면.

가장 중요한 것은 이 화면이 내놓는 길이 **전부 실제로 열리는가**입니다.
시작 화면은 사람이 처음 만나는 자리라, 여기서 막히면 그다음이 없습니다.
"""

from __future__ import annotations

from unittest.mock import patch

from app.routes import home


TABS = ["chat", "doc", "origin", "plan", "when"]


def test_다섯_갈래가_모두_있다(client):
    html = client.get("/").get_data(as_text=True)

    assert "data-home-form" in html          # 적는 칸
    for key in TABS:
        assert f'data-home-tab="{key}"' in html
        # 상담 말고는 펼쳐질 칸이 있어야 합니다.
        if key != "chat":
            assert f'data-doc-tab="{key}"' in html


def test_탭_구성이_화면과_어긋나지_않는다(app):
    with app.test_request_context():
        tabs = home._tabs()

    assert [tab["key"] for tab in tabs] == TABS
    # 상담만 적는 칸이고 나머지 넷은 서식 칸을 펼칩니다.
    assert [tab["form"] for tab in tabs] == [False, True, True, True, True]


def test_상담은_이_화면에서_바로_답한다(app):
    """상담만 넘어갈 자리가 없습니다. 여기서 답이 나와야 합니다."""

    with app.test_request_context():
        chat = home._tabs()[0]

    assert chat["go"] == ""
    assert chat["examples"]
    # 물어보는 것 말고 화물을 적어 칸을 채우는 길도 있어야 합니다.
    assert chat["fill_label"]


def test_일정과_운송과_서류가_같은_초안을_나눠_쓴다(app):
    """탭이 갈렸다고 칸이 갈리면 안 됩니다. 한 건을 만드는 중이니까요."""

    from app.services import document_start_service as start

    tabs = {group["tab"] for group in start.checklist()["groups"]}
    assert tabs == {"when", "plan", "doc"}


def test_일정_탭에_달력과_두_날짜가_있다(client):
    html = client.get("/").get_data(as_text=True)

    assert "data-cal" in html
    assert 'name="requested_departure_date"' in html
    assert 'name="buyer_required_date"' in html


def test_원산지증명서_창구가_이_건의_협정을_알려_준다(app, client, create_shipment):
    shipment = create_shipment()

    response = client.get(f"/documents/{shipment.shipment_id}/origin-guide")

    body = response.get_json()
    assert body["success"] is True
    # 협정을 못 찾더라도 신청 창구와 등록 자리는 늘 있어야 합니다.
    assert body["data"]["apply_links"]
    assert body["data"]["upload_url"].endswith("/requirements/upload")


def test_왼쪽_줄의_바로가기가_모두_열린다(app, client):
    from flask import url_for

    html = client.get("/").get_data(as_text=True)
    assert "home_rail" in html

    for item in home.RAIL:
        assert item["label"] in html
        with app.test_request_context():
            url = url_for(home.RAIL_URLS[item["key"]])
        assert client.get(url).status_code == 200, item["key"]


def test_가운데에는_적는_칸만_남긴다(client):
    """갈 곳은 전부 왼쪽 줄로 옮겼습니다. 가운데에 카드가 남아 있으면 안 됩니다."""

    html = client.get("/").get_data(as_text=True)

    assert "home_cards" not in html
    assert "home_box" in html


def test_상담_창구가_시작_화면에서도_답한다(client):
    reply = {"success": True, "source": "api", "data": {"answer": "상업송장과 포장명세서입니다."}}
    with patch("app.services.support_chat_service.ask", return_value=reply):
        response = client.post("/api/support-chat",
                               json={"question": "무슨 서류가 필요한가요?", "history": []})

    assert response.get_json()["data"]["answer"] == "상업송장과 포장명세서입니다."


def test_최근_Shipment를_왼쪽_줄에서_펼쳐_본다(client, create_shipment):
    """카드는 줄에 넣기엔 넓어 눌렀을 때 옆으로 펼칩니다."""

    shipment = create_shipment()
    html = client.get("/").get_data(as_text=True)

    assert "data-rail-recent" in html
    assert "rail_flyout" in html
    assert shipment.shipment_id in html


def test_Shipment가_없으면_최근_칸도_없다(client):
    html = client.get("/").get_data(as_text=True)

    assert "data-rail-recent" not in html


def test_Shipment가_하나도_없어도_열린다(client):
    """처음 켠 사람이 보는 화면입니다. 여기서 터지면 안 됩니다."""

    response = client.get("/")

    assert response.status_code == 200
    assert "ForwardUs" in response.get_data(as_text=True)


# --- 대화창으로 서류 초안 채우기 ---------------------------------------------------

def test_적은_글로_서류_칸을_채운다(app, client):
    """대화창에 화물을 적으면 서류 칸 이름 그대로 돌려줘야 합니다."""

    import json
    from unittest.mock import patch

    from app.services import intake_service

    answer = json.dumps({
        "transport_mode": "SEA", "sea_mode": "LCL",
        "origin": "부산", "destination": "로스앤젤레스",
        "incoterms": "FOB", "currency": "USD", "invoice_value": 25000,
        "exporter_name": "포워더스", "buyer_name": "ABC Beauty Inc.",
        "items": [{"product_description": "치약", "quantity": 500, "package_type": "carton"}],
    }, ensure_ascii=False)

    with patch.object(intake_service.ai_client, "available", return_value=True), \
         patch.object(intake_service.ai_client, "chat",
                      return_value={"success": True, "data": answer, "source": "api"}):
        response = client.post("/api/intake", json={"text": "부산에서 LA로 치약 500박스"})

    fields = response.get_json()["data"]["form"]["fields"]
    # 화면의 칸 이름과 똑같아야 그대로 꽂을 수 있습니다.
    assert fields["origin_code"] == "KRPUS"
    assert fields["destination_code"] == "USLAX"
    assert fields["incoterms"] == "FOB"
    assert fields["buyer_name"] == "ABC Beauty Inc."
    # 견적명은 서버가 짓습니다. 화면에 칸이 없습니다.
    assert "project_name" not in fields
    assert response.get_json()["data"]["form"]["items"][0]["product_description"] == "치약"


def test_지어낸_항구는_채우지_않는다(app, client):
    import json
    from unittest.mock import patch

    from app.services import intake_service

    answer = json.dumps({"origin": "부산", "destination": "발할라"}, ensure_ascii=False)
    with patch.object(intake_service.ai_client, "available", return_value=True), \
         patch.object(intake_service.ai_client, "chat",
                      return_value={"success": True, "data": answer, "source": "api"}):
        body = client.post("/api/intake", json={"text": "발할라로 보냅니다"}).get_json()

    assert "destination_code" not in body["data"]["form"]["fields"]
    assert any("발할라" in note for note in body["data"]["notes"])


def test_빈_글로_초안을_부르면_거절한다(app, client):
    response = client.post("/api/intake", json={"text": ""})

    assert response.status_code == 400
