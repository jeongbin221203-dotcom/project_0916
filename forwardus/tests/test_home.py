"""시작 화면.

가장 중요한 것은 이 화면이 내놓는 길이 **전부 실제로 열리는가**입니다.
시작 화면은 사람이 처음 만나는 자리라, 여기서 막히면 그다음이 없습니다.
"""

from __future__ import annotations

from unittest.mock import patch

from app.routes import home


# 서류 작성이 운송 계획보다 앞입니다. 서류에 적은 값이 운송 계획 칸을 미리 채웁니다.
ACTIONS = ["consult", "documents", "planning"]


def test_빠른_시작_세_단추가_순서대로_있다(client):
    import re

    html = client.get("/").get_data(as_text=True)

    assert "data-home-form" in html          # 적는 칸
    assert re.findall(r'data-home-action="(\w+)"', html) == ACTIONS
    # 단추는 적는 칸 **위**에 있어야 합니다. 아래에 있으면 눌러 볼 일이 없습니다.
    assert html.index('class="home_actions"') < html.index("data-home-input")


def test_단추_구성이_화면과_어긋나지_않는다(app):
    with app.test_request_context():
        actions = home.quick_actions()

    assert [row["key"] for row in actions] == ACTIONS
    for row in actions:
        # 누르면 우리가 먼저 말을 겁니다. 무엇부터 적을지 모르는 것이 가장 흔한 막힘입니다.
        assert row["opener"]
        assert row["examples"]
        assert row["placeholder"]


def test_서류_작성에는_칸_채우기_길이_따로_있다(app):
    with app.test_request_context():
        documents = home.quick_actions()[1]

    assert documents["key"] == "documents"
    assert documents["fill_label"]


def test_홈에는_서식_칸을_두지_않는다(client):
    """홈은 대화하는 자리입니다. 칸은 사이드바 화면으로 옮겼습니다."""

    html = client.get("/").get_data(as_text=True)

    assert "data-doc-panel" not in html
    assert "data-doc-input" not in html
    assert "data-cal" not in html


def test_일정과_운송과_서류가_같은_초안을_나눠_쓴다(app):
    """갈래가 나뉘었다고 칸이 갈리면 안 됩니다. 한 건을 만드는 중이니까요."""

    from app.services import document_start_service as start

    tabs = {group["tab"] for group in start.checklist()["groups"]}
    assert tabs == {"when", "plan", "doc"}


def test_서류_작성_화면에_칸이_모두_모여_있다(client):
    """홈에서 뺀 것들이 사라진 게 아니라 이리로 왔는지 봅니다."""

    import re

    html = client.get("/documents/new").get_data(as_text=True)

    assert re.findall(r'data-doc-nav="(\w+)"', html) == ["when", "plan", "doc", "origin"]
    assert "data-cal" in html                                  # 일정 달력
    assert 'name="requested_departure_date"' in html
    assert 'name="buyer_required_date"' in html
    for name in ("exporter_name", "buyer_name", "payment_terms", "shipping_marks", "lc_no"):
        assert f'name="{name}"' in html, name


def test_사이드바_서류_작성이_그_화면을_가리킨다(app, client):
    from flask import url_for

    from app.routes import sidebar

    item = next(row for row in sidebar.RAIL if row["key"] == "documents")
    with app.test_request_context():
        assert url_for(item["endpoint"]) == "/documents/new"
    assert "/documents/new" in client.get("/").get_data(as_text=True)


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

    from app.routes import sidebar

    for item in sidebar.RAIL:
        assert item["label"] in html
        with app.test_request_context():
            url = url_for(item["endpoint"])
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
    # 견적명은 서버가 지어 칸에 넣어 줍니다. 서류 작성 화면에서 고쳐 쓸 수 있습니다.
    # 모양은 도착국가_대표품목_날짜입니다. (processors/document_defaults)
    assert fields["project_name"].startswith("미국_치약_")
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


# --- 보여 주기용 잠금 -------------------------------------------------------------

def _locked(client):
    """잠근 상태로 시작 화면을 받아 옵니다."""

    from flask import current_app

    current_app.config["HOME_LOCKED"] = True
    return client.get("/").get_data(as_text=True)


def test_잠그면_시작_화면의_단추가_모두_막힌다(app, client):
    import re

    html = _locked(client)

    assert 'class="home_shell is_locked"' in html
    # 세 단추가 전부 막혀야 합니다. 하나라도 열려 있으면 그리로 들어갑니다.
    buttons = re.findall(r'<button type="button" role="tab".*?>', html, re.S)
    assert len(buttons) == len(ACTIONS)
    assert all("disabled" in button for button in buttons)
    assert re.search(r"<textarea[^>]*disabled", html)
    assert re.search(r'class="home_send"[^>]*disabled', html, re.S)
    # 왼쪽 사이드바는 막지 않습니다. 갈 길이 모두 거기 있어, 막으면 아무 데도 못 갑니다.
    rail = re.search(r'<aside class="home_rail.*?</aside>', html, re.S).group(0)
    assert "inert" not in rail and "disabled" not in rail


def test_잠그면_스크립트를_아예_붙이지_않는다(app, client):
    """흐리게 보이기만 하면 안 됩니다. 실제로 아무 일도 하지 않아야 합니다."""

    html = _locked(client)

    assert "js/home.js" not in html
    assert "js/doc_form.js" not in html


def test_잠가도_위쪽_메뉴는_그대로_쓴다(app, client):
    """잠그는 것은 시작 화면뿐입니다. 갈 길까지 막으면 아무것도 못 합니다."""

    import re

    html = _locked(client)
    nav = re.search(r'<nav class="main_nav".*?</nav>', html, re.S).group(0)
    rail = re.search(r'<aside class="home_rail.*?</aside>', html, re.S).group(0)

    assert "disabled" not in nav and "disabled" not in rail and "inert" not in rail
    # 위쪽에는 로그인(또는 이름) 자리만 둡니다. 갈 길은 왼쪽 사이드바에 모았습니다.
    assert "로그인" in nav or "로그아웃" in nav
    for label in ("운송 계획", "서류 작성", "컨테이너 조회", "관세청 조회"):
        assert label in rail, label
    # 일정 역산은 없앤 기능입니다. 어디에도 남기지 않습니다.
    assert "일정 역산" not in nav and "일정 역산" not in rail
    # 메뉴가 가리키는 화면도 실제로 열려야 합니다.
    for url in re.findall(r'href="([^"]+)"', nav + rail):
        assert client.get(url).status_code == 200, url


def test_왜_안_눌리는지_말해_준다(app, client):
    """이유 없이 막힌 화면은 고장으로 보입니다."""

    html = _locked(client)

    assert "보기 전용" in html
    assert "위쪽 메뉴" in html


def test_잠금을_풀면_원래대로_돌아온다(app, client):
    from flask import current_app

    current_app.config["HOME_LOCKED"] = False
    html = client.get("/").get_data(as_text=True)

    assert "is_locked" not in html
    assert "js/home.js" in html
    assert "disabled" not in html[html.find("home_tabs"):html.find("home_log")]


def test_조회_메뉴는_사이드바에_있고_위쪽에는_없다(app, client):
    """컨테이너 조회·관세청 조회는 왼쪽 사이드바로 옮겼습니다. 위쪽에는 이름 자리만 둡니다."""

    import re

    from app.routes import sidebar

    html = client.get("/").get_data(as_text=True)
    nav = re.search(r'<nav class="main_nav".*?</nav>', html, re.S).group(0)
    rail = re.search(r'<aside class="home_rail.*?</aside>', html, re.S).group(0)

    for label in ("컨테이너 조회", "관세청 조회"):
        assert label in rail and label not in nav, label
    # 운송 계획도 사이드바에서만 다닙니다.
    assert "운송 계획" in rail and "운송 계획" not in nav

    keys = [row["key"] for row in sidebar.RAIL]
    assert keys == ["home", "planning", "documents", "dashboard", "container", "lookup"]
    # 지금 보는 화면이 사이드바에 표시됩니다.
    assert 'aria-current="page"' in re.search(
        r'<aside class="home_rail.*?</aside>', client.get("/lookup/").get_data(as_text=True), re.S).group(0)


def test_서류_작성은_한_스크롤로_이어지고_사이드바가_따라다닌다(client):
    """네 갈래를 따로 누르지 않고 쭉 내려가며 채웁니다. 작은 사이드바가 자리를 알려 줍니다."""

    import re

    html = client.get("/documents/new").get_data(as_text=True)

    # 네 갈래가 모두 한 화면에 이어져 있습니다. 숨겨 두지 않습니다.
    sections = re.findall(r'id="doc_sec_(\w+)" data-doc-section="(\w+)"', html)
    assert [key for key, _ in sections] == ["when", "plan", "doc", "origin"]
    assert "data-doc-tab" not in html
    # 따라다니는 사이드바가 각 갈래를 가리킵니다.
    rail = html.split('class="doc_rail"')[1].split("</nav>")[0]
    assert re.findall(r'href="#doc_sec_(\w+)"', rail) == ["when", "plan", "doc", "origin"]
    assert re.findall(r'data-doc-nav="(\w+)"', rail) == ["when", "plan", "doc", "origin"]
