"""올린 서류 → 빠진 정보 묻기 → 채팅으로 합치기 → 고른 서류 만들기 → 검토·PDF."""

from __future__ import annotations

import re
from unittest.mock import patch

import pytest

from app.services import document_pipeline_service as pipe
from app.services import draft_document_service as drafts


@pytest.fixture(autouse=True)
def _no_ai():
    """규칙만으로 읽히는지 봅니다. AI는 따로 흉내 낸 테스트에서만 씁니다."""

    with patch.object(pipe.ai_client, "available", return_value=False):
        yield


def _form(**fields) -> dict:
    base = {"transport_mode": "SEA", "exporter_name": "SAMPLE COSMETICS",
            "exporter_address": "Seoul, Korea", "buyer_name": "SAMPLE BEAUTY INC.",
            "origin_code": "KRPUS", "destination_code": "USLAX", "currency": "USD"}
    base.update(fields)
    return {"fields": {k: v for k, v in base.items() if v},
            "items": [{"product_description": "LIPSTICK", "package_type": "carton",
                       "quantity": "100", "weight_per_package_kg": "5"}]}


def _complete() -> dict:
    """필수 정보가 다 모인 초안."""

    state = pipe.start({"form": _form(), "document_label": "견적서"})
    return pipe.merge({"draft": state["draft"], "kinds": state["kinds"], "message":
                       "인코텀즈: FOB\n바이어 주소: 1 Test Ave, Los Angeles\n단가: 12.5\n"
                       "한 상자 크기: 40x30x25"})["draft"]


# --- 검증과 묻기 --------------------------------------------------------------------

def test_빠진_필수_정보를_짚어_묻고_만들지_않는다(app):
    state = pipe.start({"form": _form(), "document_label": "견적서"})

    assert state["stage"] == "need_info"
    keys = {row["key"] for row in state["missing"]}
    assert {"buyer_address", "incoterms", "items.price"} <= keys
    # 전문가가 옆에서 짚어 주는 말투. 무엇이 빠졌는지 번호를 매겨 이름으로 말합니다.
    count = len(state["missing"])
    assert state["reply"].startswith(f"업로드해주신 견적서에서 아래 {count}가지 정보가 누락되어 있습니다.")
    assert "번호에 맞춰 채팅창에 편하게 입력해 주시면 바로 서류에 반영해 드릴게요!" in state["reply"]
    for no, row in enumerate(state["missing"], 1):
        assert f"{no}. **{row['label']}**" in state["reply"]
    assert "바이어(Consignee) 상세 주소" in state["reply"]
    assert "인코텀즈 조건(FOB, CIF 등)" in state["reply"]
    # 기본으로 고른 서류는 상업송장·포장명세서입니다.
    assert state["kinds"] == ["commercial_invoice", "packing_list_std"]


def test_필수_정보는_고른_서류마다_다르다(app):
    draft = pipe.start({"form": _form(), "document_label": "B/L"})["draft"]

    ci = {row["key"] for row in pipe.missing(draft, ["commercial_invoice"])}
    pl = {row["key"] for row in pipe.missing(draft, ["packing_list_std"])}

    # 포장명세서에는 금액·인코텀즈가 없습니다.
    assert "items.price" in ci and "incoterms" in ci
    assert "items.price" not in pl and "incoterms" not in pl


def test_빠진_채로_만들라고_하면_다시_묻는다(app):
    draft = pipe.start({"form": _form(), "document_label": "견적서"})["draft"]

    result = pipe.generate({"draft": draft, "kinds": ["commercial_invoice"]})

    assert result["stage"] == "need_info"
    assert "documents" not in result


# --- 채팅으로 받은 값 합치기 ---------------------------------------------------------

def test_칸_이름과_값으로_적은_것을_합친다(app):
    state = pipe.start({"form": _form(), "document_label": "견적서"})

    merged = pipe.merge({"draft": state["draft"], "kinds": state["kinds"], "message":
                         "인코텀즈: FOB\n바이어 주소: 1 Test Ave, Los Angeles\n단가: 12.5\n"
                         "한 상자 크기: 40x30x25"})

    draft = merged["draft"]
    assert merged["stage"] == "ready"
    assert draft["incoterms"] == "FOB"
    assert draft["buyer_address"] == "1 Test Ave, Los Angeles"
    item = draft["items"][0]
    assert (item["length_cm"], item["width_cm"], item["height_cm"]) == ("40", "30", "25")
    # 단가만 적으면 금액은 단가 × 수량이고, 그렇게 계산했다고 알립니다.
    assert item["amount"] == "1250"
    assert any("단가 × 수량" in note for note in merged["notes"])
    # 기존에 읽은 값은 그대로 남습니다.
    assert draft["exporter_name"] == "SAMPLE COSMETICS"
    assert draft["origin_code"] == "KRPUS"


def test_한글_토씨가_붙은_조건_코드도_알아본다(app):
    """"CIF로 해줘" — \\b는 한글을 글자로 쳐서 CIF 뒤에 경계가 없다고 봅니다."""

    draft = pipe.start({"form": _form(), "document_label": "견적서"})["draft"]

    merged = pipe.merge({"draft": draft, "kinds": [], "message": "CIF로 해줘"})

    assert merged["draft"]["incoterms"] == "CIF"


def test_빠진_글자_칸이_하나면_한_줄로_적은_말을_그_칸으로_본다(app):
    draft = {**_complete(), "buyer_address": ""}

    merged = pipe.merge({"draft": draft, "kinds": [], "message": "1 Test Ave, LA, CA 90001"})

    assert merged["draft"]["buyer_address"] == "1 Test Ave, LA, CA 90001"


def test_지어낸_조건은_넣지_않고_알린다(app):
    draft = pipe.start({"form": _form(), "document_label": "견적서"})["draft"]

    merged = pipe.merge({"draft": draft, "kinds": [], "message": "인코텀즈: FOBB"})

    assert "incoterms" not in merged["draft"]
    assert any("FOBB" in note for note in merged["notes"])


def test_물어본_번호에_맞춰_적은_답을_그_칸에_넣는다(app):
    state = pipe.start({"form": _form(), "document_label": "오퍼시트"})
    order = [row["key"] for row in state["missing"]]
    examples = {"buyer_address": "1 Test Ave, Los Angeles, CA 90001", "incoterms": "CIF로 해주세요",
                "items.price": "단가 12.5달러", "items.dims": "40 x 30 x 25 cm"}
    message = "\n".join(f"{order.index(key) + 1}. {value}" for key, value in examples.items())

    merged = pipe.merge({"draft": state["draft"], "kinds": state["kinds"], "message": message})

    draft = merged["draft"]
    assert merged["stage"] == "ready", merged["reply"]
    assert draft["buyer_address"] == "1 Test Ave, Los Angeles, CA 90001"
    assert draft["incoterms"] == "CIF"
    item = draft["items"][0]
    assert item["unit_price"] == "12.5" and item["amount"] == "1250"
    assert (item["length_cm"], item["width_cm"], item["height_cm"]) == ("40", "30", "25")


def test_묻고_나서_서류_체크를_바꿔도_번호는_물어본_목록을_따른다(app):
    state = pipe.start({"form": _form(), "document_label": "견적서", "kinds": ["commercial_invoice"]})
    asked = [row["key"] for row in state["missing"]]
    no = asked.index("buyer_address") + 1
    # 포장명세서를 더 고르면 다시 센 목록의 순서가 달라질 수 있습니다.
    kinds = ["commercial_invoice", "packing_list_std"]

    merged = pipe.merge({"draft": state["draft"], "kinds": kinds, "asked": asked,
                         "message": f"{no}. 1 Test Ave"})

    assert merged["draft"]["buyer_address"] == "1 Test Ave"


def test_번호에_칸_이름까지_적어도_읽는다(app):
    draft = pipe.start({"form": _form(), "document_label": "견적서"})["draft"]

    merged = pipe.merge({"draft": draft, "kinds": [], "message": "1. 인코텀즈: FOB\n2. 바이어 주소: 9 Main St"})

    assert merged["draft"]["incoterms"] == "FOB"
    assert merged["draft"]["buyer_address"] == "9 Main St"


def test_품목이_여러_줄이면_번호_답을_품목에_넣지_않고_알린다(app):
    form = _form()
    form["items"].append({"product_description": "MASCARA", "quantity": "10",
                          "weight_per_package_kg": "3"})
    state = pipe.start({"form": form, "document_label": "견적서"})
    no = [row["key"] for row in state["missing"]].index("items.price") + 1

    merged = pipe.merge({"draft": state["draft"], "kinds": state["kinds"], "message": f"{no}. 12.5"})

    assert all("unit_price" not in row for row in merged["draft"]["items"])
    assert any("품목 번호" in note for note in merged["notes"])


@pytest.mark.parametrize("message, make, kinds", [
    ("이거 기반으로 서류 만들어줘", True, []),
    ("인보이스 써줘", True, ["commercial_invoice"]),
    ("패킹리스트랑 CI 작성 부탁드려요", True, ["commercial_invoice", "packing_list_std"]),
    ("프로포마 인보이스 만들어 주세요", True, ["proforma_invoice"]),
    ("선적의뢰서도 뽑아줘", True, ["shipping_instruction"]),
    ("please make a packing list", True, ["packing_list_std"]),
    ("인보이스 작성 방법 알려줘", False, ["commercial_invoice"]),
    ("이 B/L에서 CIF 조건이 맞나요?", False, []),
    ("", False, []),
])
def test_서류를_만들어_달라는_말인지_규칙으로_가린다(message, make, kinds):
    assert pipe.intent(message) == {"make": make, "kinds": kinds}


def test_짚어_말한_서류_기준으로_시작한다(app):
    state = pipe.start({"form": _form(), "document_label": "B/L", "kinds": ["packing_list_std"]})

    assert state["kinds"] == ["packing_list_std"]
    assert state["reply"].startswith("요청하신 **포장명세서 (Packing List)** 기준으로")
    assert "incoterms" not in {row["key"] for row in state["missing"]}


def test_AI가_읽은_값도_우리_검증을_거친다(app):
    draft = pipe.start({"form": _form(), "document_label": "견적서"})["draft"]
    ai = {"exporter_name": None, "exporter_address": None, "buyer_name": None,
          "buyer_address": "1 Test Ave, LA", "notify_party": None,
          "port_of_loading": None, "port_of_discharge": "발할라",
          "incoterms": "FOB", "currency": "XYZ", "payment_terms": "FREIGHT PREPAID",
          "items": [{"line": None, "product_description": None, "quantity": None,
                     "package_unit": None, "unit_price": 3, "amount": None,
                     "weight_per_package_kg": None, "gross_weight_kg": None,
                     "net_weight_kg": None, "length_cm": 40, "width_cm": 30, "height_cm": 25}]}

    with patch.object(pipe.ai_client, "available", return_value=True), \
         patch.object(pipe.ai_client, "structured_chat",
                      return_value={"success": True, "source": "api", "data": ai}):
        merged = pipe.merge({"draft": draft, "kinds": [], "message": "주소는 1 Test Ave..."})

    result = merged["draft"]
    assert result["incoterms"] == "FOB"
    assert result["buyer_address"] == "1 Test Ave, LA"
    assert result["destination_code"] == "USLAX"        # 지어낸 항구로 덮지 않습니다.
    assert "currency" in result and result["currency"] == "USD"   # XYZ는 버립니다.
    assert "payment_terms" not in result                # 운임 조건은 결제 조건이 아닙니다.
    assert result["items"][0]["unit_price"] == "3"      # 품목이 하나면 line 없이도 1번 줄


# --- 만들기와 검토 --------------------------------------------------------------------

def test_고른_서류만_만든다(app):
    result = pipe.generate({"draft": _complete(),
                            "kinds": ["packing_list_std", "shipping_instruction"]})

    assert result["stage"] == "made"
    assert [doc["kind"] for doc in result["documents"]] == ["packing_list_std",
                                                            "shipping_instruction"]
    for doc in result["documents"]:
        assert doc["preview"].startswith("data:image/png;base64,")
        assert doc["fields"] and doc["columns"]
        # 검토 창 칸에 넣는 값은 그려질 글자 그대로입니다.
        assert all(isinstance(value, str) for value in doc["data"]["items"][0].values())


def test_모르는_서류는_버리고_하나도_안_고르면_거절한다(app):
    from app.validators import ValidationError

    with pytest.raises(ValidationError):
        pipe.generate({"draft": _complete(), "kinds": ["passport"]})


def test_선적의뢰서를_그린다(app):
    from app.processors import document_form

    assert document_form.available("shipping_instruction")
    rendered = drafts.render("shipping_instruction", _complete())
    assert rendered["data"]["freight_term"] == "FREIGHT COLLECT"      # FOB는 운임 후불
    assert "etd" in rendered["undecided"]


def test_고친_값으로_다시_그리고_모르는_칸은_버린다(app):
    doc = pipe.generate({"draft": _complete(), "kinds": ["commercial_invoice"]})["documents"][0]
    edited = {**doc["data"], "consignee": "EDITED BUYER", "evil": "<script>"}

    cleaned = drafts.clean_data("commercial_invoice", edited)

    assert cleaned["consignee"] == "EDITED BUYER"
    assert "evil" not in cleaned
    assert drafts.preview_data("commercial_invoice", edited) != doc["preview"]


# --- 창구 --------------------------------------------------------------------------

def test_창구로_시작부터_만들기까지(client):
    start = client.post("/api/doc-pipeline/start",
                        json={"form": _form(), "document_label": "견적서"}).get_json()["data"]
    merged = client.post("/api/doc-pipeline/merge", json={
        "draft": start["draft"], "kinds": start["kinds"],
        "message": "인코텀즈: FOB\n바이어 주소: 1 Test Ave\n단가: 12.5\n한 상자 크기: 40x30x25",
    }).get_json()["data"]
    made = client.post("/api/doc-pipeline/generate", json={
        "draft": merged["draft"], "kinds": ["commercial_invoice", "packing_list_std"],
    }).get_json()["data"]

    assert start["stage"] == "need_info"
    assert merged["stage"] == "ready"
    assert made["stage"] == "made" and len(made["documents"]) == 2


def test_창구로_말의_뜻을_묻는다(client):
    body = client.post("/api/doc-pipeline/intent", json={"message": "인보이스 써줘"}).get_json()

    assert body["data"] == {"make": True, "kinds": ["commercial_invoice"]}


# --- + 로 붙인 파일 (세 탭 공통 창구) ------------------------------------------------

def _extracted(label="선하증권 (B/L)") -> dict:
    return {"document_type": "bill_of_lading", "document_label": label, "form": _form(),
            "summary": [{"label": "Shipper", "value": "SAMPLE COSMETICS"}],
            "filled": 7, "missing": ["바이어 주소"], "notes": [], "hs_queries": ["LIPSTICK"],
            "source": "api"}


def _attach(client, **form):
    import io

    data = {"file": (io.BytesIO(b"%PDF-1.4 fake"), "bl.pdf"), **form}
    return client.post("/api/attach", data=data, content_type="multipart/form-data")


def test_상담_탭에서_서류를_만들어_달라면_서류_작성으로_보낸다(client):
    from app.services import attachment_service

    with patch.object(attachment_service.document_extract_service, "extract",
                      return_value=_extracted()) as extract, \
         patch.object(attachment_service.support_chat_service, "ask") as ask:
        body = _attach(client, message="이거 기반으로 인보이스 써줘", mode="consult").get_json()

    data = body["data"]
    assert extract.call_args.args[0] == "bl.pdf"
    assert data["recognized"] == "이 문서는 **선하증권 (B/L)**입니다."
    assert data["route"] == "documents"
    assert data["pipeline"]["kinds"] == ["commercial_invoice"]
    assert data["pipeline"]["stage"] == "need_info"
    ask.assert_not_called()           # 상담 답을 따로 받지 않습니다.


def test_상담_탭에서_물어보면_읽은_값을_곁들여_답한다(client):
    from app.services import attachment_service

    answer = {"success": True, "source": "api", "data": {"answer": "B/L의 Consignee를 보면…"}}
    with patch.object(attachment_service.document_extract_service, "extract",
                      return_value=_extracted()), \
         patch.object(attachment_service.support_chat_service, "ask", return_value=answer) as ask:
        body = _attach(client, message="이 B/L에서 확인할 게 뭐예요?", mode="consult",
                       history='[{"role": "user", "content": "안녕"}, "bad"]').get_json()

    data = body["data"]
    assert data["route"] == "consult" and "pipeline" not in data
    assert data["answer"] == "B/L의 Consignee를 보면…"
    question, history = ask.call_args.args
    assert question.startswith("[사용자가 첨부한 서류] 선하증권 (B/L)")
    assert "- Shipper: SAMPLE COSMETICS" in question and question.endswith("이 B/L에서 확인할 게 뭐예요?")
    assert history == [{"role": "user", "content": "안녕"}]      # 모양이 틀린 것은 버립니다.


def test_서류_작성_탭에서는_말이_없어도_서류_흐름을_시작한다(client):
    from app.services import attachment_service

    with patch.object(attachment_service.document_extract_service, "extract",
                      return_value=_extracted("Offer Sheet")):
        data = _attach(client, mode="documents").get_json()["data"]

    assert data["route"] == "documents"
    assert data["pipeline"]["kinds"] == ["commercial_invoice", "packing_list_std"]
    assert data["pipeline"]["reply"].startswith("업로드해주신 Offer Sheet에서 아래")


def test_운송_탭에서_파일만_올리면_종류만_알리고_머문다(client):
    from app.services import attachment_service

    with patch.object(attachment_service.document_extract_service, "extract",
                      return_value=_extracted()), \
         patch.object(attachment_service.support_chat_service, "ask") as ask:
        data = _attach(client, mode="planning").get_json()["data"]

    assert data["route"] == "planning" and "answer" not in data and "pipeline" not in data
    ask.assert_not_called()


def test_붙인_파일_창구는_파일이_없으면_거절한다(client):
    response = client.post("/api/attach", data={"message": "hi"}, content_type="multipart/form-data")

    assert response.status_code == 400


def test_없는_단계는_404(client):
    assert client.post("/api/doc-pipeline/delete", json={}).status_code == 404


def test_검토한_서류들을_PDF_한_파일로_받는다(client):
    made = pipe.generate({"draft": _complete(), "kinds": ["commercial_invoice",
                                                          "packing_list_std"]})
    documents = [{"kind": doc["kind"], "data": doc["data"]} for doc in made["documents"]]

    response = client.post("/documents/draft/review.pdf", json={"documents": documents})

    assert response.status_code == 200
    assert response.mimetype == "application/pdf"
    assert response.data.startswith(b"%PDF")
    # 서류 두 장이 A4 두 쪽입니다.
    assert len(re.findall(rb"/Type\s*/Page[^s]", response.data)) == 2


def test_미리보기_창구는_모르는_서식을_거절한다(client):
    response = client.post("/documents/draft/preview", json={"kind": "passport", "data": {}})

    assert response.status_code == 404


def test_PDF_창구는_빈_목록을_거절한다(client):
    assert client.post("/documents/draft/review.pdf", json={"documents": []}).status_code == 400


# --- 화면 ------------------------------------------------------------------------

def test_HS_CODE_조회는_탭_줄_오른쪽_끝에_있고_칩에는_없다(client):
    from app.routes import home

    html = client.get("/").get_data(as_text=True)
    actions = html[html.index('class="home_actions"'):html.index("data-home-form")]

    # 탭 셋 다음, 같은 줄에 HS CODE 조회 단추가 있습니다.
    assert actions.index('data-home-action="documents"') < actions.index("data-home-hs-open")
    assert "HS CODE 조회" in actions
    with client.application.test_request_context():
        assert all("hs_label" not in action for action in home.quick_actions())
    assert "data-dp-modal" in html and "doc_preview.js" in html


def test_적는_칸_왼쪽_아래에_첨부_단추가_있다(client):
    from app.routes import home

    html = client.get("/").get_data(as_text=True)
    box = html[html.index("data-home-form"):html.index("home_send")]

    # 탭과 상관없이 하나의 적는 칸에 있고, 칩 줄보다 앞(왼쪽)입니다.
    assert box.index("data-home-plus") < box.index("data-home-chips")
    assert "data-home-attach" in box and "data-home-upload" in box
    assert all("upload_label" not in action for action in home.quick_actions())


def test_대화로_만든_초안도_검토_창에서_쓸_칸을_함께_보낸다(client):
    draft = {**_complete(), "kind": "packing_list_std"}

    body = client.post("/api/agent", json={"message": "그냥 만들어줘", "draft": draft}).get_json()

    documents = body["data"]["documents"]
    assert documents and all(doc["fields"] and "data" in doc for doc in documents)


# --- Consignee ↔ Buyer 자동 보완 ------------------------------------------------

def test_Consignee만_있으면_송장_Buyer에_SAME_AS_CONSIGNEE가_찍힌다(app):
    draft = _complete()

    invoice = pipe.review_document("commercial_invoice", drafts.as_text(draft))

    assert invoice["data"]["consignee"] == "SAMPLE BEAUTY INC."
    assert invoice["data"]["buyer"] == "SAME AS CONSIGNEE"


def test_Buyer만_적어도_바이어_상호가_빠졌다고_묻지_않는다(app):
    """올린 서류에 Buyer 칸만 있는 경우입니다.

    받는 곳과 대금 내는 곳은 대개 같습니다. 한쪽만 적혀 있는데 "상호가
    빠졌다"고 되물으면, 이미 적어 낸 것을 한 번 더 적으라는 말이 됩니다.
    """

    state = pipe.start({"form": _form(buyer_name="", buyer="SAMPLE BEAUTY INC.")})

    assert state["draft"]["buyer_name"] == "SAMPLE BEAUTY INC."
    assert "buyer_name" not in {row["key"] for row in state["missing"]}


# --- 견적명 -----------------------------------------------------------------------

def test_견적명을_지어_제안한다(app):
    """대시보드에서 이 건을 부를 이름. 서류 작성 화면과 같은 모양이어야 합니다."""

    state = pipe.start({"form": _form(), "document_label": "견적서"})

    assert re.fullmatch(r"미국_LIPSTICK_\d{8}", state["project_name_suggestion"])
    assert state["project_name"] == ""      # 아직 사람이 적지 않았습니다.


def test_적어_둔_견적명은_대화가_이어져도_남는다(app):
    state = pipe.start({"form": _form(), "document_label": "견적서"})
    draft = {**state["draft"], "project_name": "2026-10 멕시코 화장품 1차 오퍼"}

    after = pipe.merge({"draft": draft, "kinds": state["kinds"], "message": "인코텀즈: FOB"})

    assert after["project_name"] == "2026-10 멕시코 화장품 1차 오퍼"
    assert after["draft"]["project_name"] == "2026-10 멕시코 화장품 1차 오퍼"
