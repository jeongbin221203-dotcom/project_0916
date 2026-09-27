"""서류 작성 → 운송 계획 흐름 7가지.

1 탭 순서  2 서류 → 운송 계획 동기화  3 빈 서식 PDF  4 상담 창 자동 열림 없음
5 품목별 패킹 정보 묻기·합치기  6 금액 칸 통화 표기  7 팝업 스크롤
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.routes import home
from app.services import document_pipeline_service as pipeline

STATIC = Path(__file__).parent.parent / "app" / "static"


def _member(app, email="kim@example.com"):
    browser = app.test_client()
    browser.post("/auth/signup", data={"email": email, "password": "secret123",
                                       "password_confirm": "secret123"})
    return browser


# --- 1. 탭 순서 ------------------------------------------------------------------------

def test_서류_작성_탭이_운송_계획보다_앞이다(app):
    with app.test_request_context():
        labels = [row["label"] for row in home.quick_actions()]
    assert labels == ["무역 상담", "서류 작성", "운송 예상 견적"]


def test_예시_칩을_누르면_바로_보낸다(app):
    """적는 칸에 넣어 두고 한 번 더 누르게 하지 않습니다. (예: "상업송장만 작성해줘")"""

    js = (STATIC / "js/home.js").read_text(encoding="utf-8")
    chip = js[js.index('const chip = event.target.closest("[data-home-chip]")'):]
    chip = chip[:chip.index("});")]
    assert "requestSubmit" in chip
    # 앞 질문에 답하는 중이면 넣어만 둡니다. (두 번 보내지 않게)
    assert "sendButton.disabled" in chip


def test_기본_정보는_모두_필수다(app, client):
    """보내는 곳·받는 곳의 상호와 주소. 하나라도 비면 Seller·Consignee 칸이 비어 나갑니다."""

    from app.services import agent_service, document_pipeline_service, document_start_service

    basics = ("exporter_name", "exporter_address", "buyer_name", "buyer_address")

    # 1) 서류 작성 화면의 칸에 * 표시
    with app.test_request_context():
        checklist = document_start_service.checklist()
    fields = {field["name"]: field for group in checklist["groups"] for field in group["fields"]}
    for name in basics:
        assert fields[name].get("required") is True, name
    html = client.get("/documents/new").get_data(as_text=True)
    for name in basics:
        block = html[html.index(f'data-doc-field="{name}"'):][:400]
        assert "doc_must" in block, name

    # 2) 대화로 만들 때 묻는 순서에서도 필수
    for kind, rows in agent_service.ASK_FOR.items():
        required = {name for name, must in rows if must}
        for name in basics:
            if any(name == row[0] for row in rows):
                assert name in required, (kind, name)

    # 3) 올린 서류로 만들 때의 필수 목록에도
    for kind, keys in document_pipeline_service.REQUIRED_BY_KIND.items():
        assert set(basics) <= set(keys), kind


# --- 2. 서류 작성 → 운송 계획 ----------------------------------------------------------------

DOC_VALUES = {
    "source": "document",
    "fields": {"exporter_name": "FORWARD COSMETICS", "exporter_address": "Seoul, Korea",
               "buyer_name": "ABC BEAUTY", "buyer_country": "US",
               "buyer_address": "1 Secret Ave, LA", "buyer_email": "buyer@abc.com",
               "notify_party": "SAME AS CONSIGNEE",
               "payment_terms": "T/T to Shinhan Bank A/C 100-200-300400",
               "origin_code": "KRPUS", "destination_code": "USLAX", "transport_mode": "SEA",
               "incoterms": "CIF", "currency": "EUR", "requested_departure_date": "2026-11-02"},
    "items": [{"product_description": "Cream 50ml", "hs_code": "3304990000", "package_type": "carton",
               "quantity": "500", "length_cm": "40", "width_cm": "30", "height_cm": "25",
               "weight_per_package_kg": "8", "net_weight_kg": "3500", "unit_price": "5",
               "amount": "2500"},
              {"product_description": "Toner", "quantity": "100", "amount": "500.50"}],
}


def test_서류에_적은_값이_운송_계획_모양으로_나온다(app):
    browser = _member(app)
    assert browser.put("/api/work-draft", json=DOC_VALUES).status_code == 200

    data = browser.get("/api/work-draft/planning").get_json()["data"]
    assert data["origin"]["code"] == "KRPUS" and data["destination"]["code"] == "USLAX"
    assert data["incoterms"] == "CIF" and data["transport_mode"] == "SEA"
    # 발송 예상일은 **넘기지 않습니다.** (2026-09-26)
    # 운송 계획 화면은 달력에서 날짜를 고르는 것으로 시작합니다. 미리 골라 두면
    # 들어오자마자 이미 선택된 상태라, "다음 선택: Seller 발송 예상일" 안내와
    # 화면이 어긋나 무엇을 해야 할지 알 수 없습니다.
    assert data["departure_date"] is None
    fields = data["fields"]
    assert fields["exporter_name"] == "FORWARD COSMETICS" and fields["buyer_name"] == "ABC BEAUTY"
    assert fields["product_description"] == "Cream 50ml" and fields["quantity"] == "500"
    assert fields["length_cm"] == "40" and fields["weight_per_package_kg"] == "8"
    assert fields["net_weight_kg"] == "3500" and fields["currency"] == "EUR"
    assert fields["invoice_value"] == "3000.5"
    assert data["cargo_lines"] == [{"product_description": "Toner", "quantity": "100", "amount": "500.50"}]
    assert data["savedAt"] > 0


def test_연락처와_계좌는_서버에_남기지_않는다(app):
    """주소는 남기고 연락처·계좌는 남기지 않습니다.

    주소는 다시 적다가 나는 오타가 B/L에 그대로 찍혀 손해가 큽니다. 반면 이메일·담당자는
    서류에 꼭 필요하지 않고, 계좌번호는 어떤 경우에도 서버에 두지 않습니다.
    """

    from app.models import WorkDraft

    browser = _member(app)
    browser.put("/api/work-draft", json=DOC_VALUES)
    stored = str(WorkDraft.query.one().data)
    for secret in ("buyer@abc.com", "SAME AS CONSIGNEE", "100-200-300400", "Shinhan"):
        assert secret not in stored, secret
    assert "ABC BEAUTY" in stored          # 바이어 회사명은 뒤 서류에 필요해 남깁니다.
    assert "1 Secret Ave" in stored        # 주소도 남깁니다. (2026-09 결정)


def test_나중에_적은_값만_덮고_빈_값으로_지우지_않는다(app):
    browser = _member(app)
    browser.put("/api/work-draft", json=DOC_VALUES)
    browser.put("/api/work-draft", json={"source": "chat", "fields": {"incoterms": "FOB"}, "items": []})

    data = browser.get("/api/work-draft").get_json()["data"]
    assert data["fields"]["incoterms"] == "FOB" and data["fields"]["origin_code"] == "KRPUS"
    assert len(data["items"]) == 2 and data["source"] == "chat"


def test_회원마다_따로이고_로그인_전에는_401(app, anon_client):
    alice, bob = _member(app, "a@example.com"), _member(app, "b@example.com")
    alice.put("/api/work-draft", json=DOC_VALUES)
    assert bob.get("/api/work-draft/planning").get_json()["data"] == {}
    assert anon_client.get("/api/work-draft").status_code == 401
    assert anon_client.put("/api/work-draft", json=DOC_VALUES).status_code == 401


def test_화면이_서로_이어진다(client):
    for path in ("/documents/new", "/planning/new", "/"):
        html = client.get(path).get_data(as_text=True)
        assert "js/work_draft.js" in html and "FORWARDUS_WORK_DRAFT" in html, path
    doc_js = (STATIC / "js/doc_form.js").read_text(encoding="utf-8")
    assert "ForwardusWorkDraft.save(sharedValues()" in doc_js
    planning_js = (STATIC / "js/planning.js").read_text(encoding="utf-8")
    assert "planningPrefill()" in planning_js and "adoptWorkDraft().finally" in planning_js
    home_js = (STATIC / "js/home.js").read_text(encoding="utf-8")
    assert 'syncWorkDraft("chat")' in home_js and 'syncWorkDraft("upload")' in home_js


def test_서류_작성_화면은_적던_내용을_다시_불러온다(app):
    """다른 화면에 다녀와도 적던 값이 남아 있어야 합니다. (이 탭 저장분 + 서버 저장분)"""

    js = (STATIC / "js/doc_form.js").read_text(encoding="utf-8")
    assert "forwardus:doc-form-draft" in js          # 이 탭에 두는 자리
    assert "function restoreDraft" in js and "restoreDraft();" in js
    assert "ForwardusWorkDraft.load()" in js         # 서버 저장분
    # 저장은 **누를 때만** 합니다. 적는 동안 저절로 저장하면 언제 저장됐는지
    # 알 수 없고, 저장이 막혔을 때 조용히 넘어갑니다. (2026-09-26 사용자 결정)
    assert 'data-doc-save-now' in js                 # 임시저장 단추
    assert 'form.addEventListener("input", markDirty)' in js
    assert 'saveSoon' not in js                      # 저절로 저장하던 자리
    assert '"beforeunload"' in js                    # 저장 안 한 채로 떠나면 붙잡습니다
    assert "data-doc-clear" in js                    # 비우고 새로 시작
    shared = (STATIC / "js/work_draft.js").read_text(encoding="utf-8")
    assert "async function load()" in shared and "async function clear()" in shared


def test_브라우저에_남기는_값은_회원마다_따로_둔다():
    """한 탭에서 A가 로그아웃하고 B가 로그인해도 섞이면 안 됩니다.

    sessionStorage는 탭이 살아 있는 한 남고, 로그아웃은 키를 지우지
    않았습니다. 그래서 A가 적은 바이어 주소·이메일이 B의 서류 칸에
    그대로 채워졌습니다.
    """

    base = (STATIC / "js/base.js").read_text(encoding="utf-8")
    assert "window.ForwardusStore" in base
    assert "window.FORWARDUS_SCOPE" in base
    assert "clearPrivate" in base and ".nav_logout" in base   # 로그아웃 때 지웁니다.
    assert "dropLegacy" in base                               # 스코프 없던 옛 키도 치웁니다.

    # 거래처 정보가 담기는 키는 모두 스코프를 거쳐야 합니다.
    private = ["forwardus:work-private", "forwardus:doc-form-draft",
               "forwardus:planning-draft", "forwardus:doc-draft"]
    for name in ("work_draft.js", "doc_form.js", "planning.js", "doc_upload.js", "home.js"):
        js = (STATIC / "js" / name).read_text(encoding="utf-8")
        for base_key in private:
            assert f'"{base_key}"' not in js or f'ForwardusStore.key("{base_key}")' in js, \
                f"{name}: {base_key}를 스코프 없이 씁니다."

    # standalone 화면(운송 계획 단독)도 planning.js가 초안을 남기므로 스코프가 있어야 합니다.
    shell = (Path(__file__).parent.parent / "app/templates/base.html").read_text(encoding="utf-8")
    scope_at = shell.index("window.FORWARDUS_SCOPE")
    guard_at = shell.index("{% if not standalone %}", shell.index("static_url('js/base.js')") - 3000)
    assert scope_at < guard_at, "스코프 주입이 standalone 밖에 있어야 합니다."


def test_찾아본_품명은_회원_기록으로_남는다():
    """그 회원이 찾아본 품명이라, 다시 로그인하면 그대로 있는 편이 낫습니다."""

    js = (STATIC / "js/hs_modal.js").read_text(encoding="utf-8")
    assert 'ForwardusStore.key("forwardus:hs-queries")' in js
    assert "window.localStorage" in js          # 탭을 닫아도 남습니다.
    # 로그인하지 않은 손님 것은 오래 남기지 않습니다. 누구 것인지 가릴 수 없습니다.
    assert 'scope === "guest"' in js and "window.sessionStorage" in js

    # 로그아웃해도 지우지 않는 유일한 키입니다. (지울 목록에 없어야 합니다)
    base = (STATIC / "js/base.js").read_text(encoding="utf-8")
    start = base.index("const PRIVATE = [")
    listed = base[start:base.index("];", start)]
    assert "hs-queries" not in listed


def test_새로고침은_적던_값을_지우지도_홈으로_보내지도_않는다():
    """F5는 화면이 이상할 때 사람이 가장 먼저 누르는 것입니다.

    예전에는 새로고침을 "처음부터 다시"로 보고 초안을 지운 뒤 홈으로
    보냈습니다. 고쳐 보려고 누른 사람이 적던 것을 통째로 잃었습니다.
    planning.js가 beforeunload로 저장해 둔 초안도 같은 키라 함께 지워졌습니다.
    """

    js = (STATIC / "js/base.js").read_text(encoding="utf-8")
    assert "isReload" not in js                 # 새로고침인지 따지지 않습니다.
    assert "location.replace" not in js         # 홈으로 강제로 보내지 않습니다.

    # 홈 버튼을 직접 누르는 "처음부터 다시"는 그대로 둡니다.
    assert "data-home-reset" in js and "clearDraft()" in js

    # planning.js가 저장해 둔 초안이 살아남아야 의미가 있습니다.
    planning = (STATIC / "js/planning.js").read_text(encoding="utf-8")
    assert 'window.addEventListener("beforeunload", saveDraft)' in planning


def test_임시저장을_비우면_서버에서도_지워진다(app):
    browser = _member(app)
    browser.put("/api/work-draft", json=DOC_VALUES)
    assert browser.get("/api/work-draft").get_json()["data"]["fields"]

    assert browser.delete("/api/work-draft").status_code == 200
    assert browser.get("/api/work-draft").get_json()["data"] == {}
    assert browser.get("/api/work-draft/planning").get_json()["data"] == {}


# --- 3. 빈 서식 PDF ---------------------------------------------------------------------

@pytest.mark.parametrize("kind, name", [("commercial_invoice", "commercial_invoice_blank.pdf"),
                                        ("packing_list_std", "packing_list_blank.pdf")])
def test_빈_서식_PDF를_바로_받는다(anon_client, kind, name):
    response = anon_client.get(f"/documents/blank/{kind}.pdf")
    assert response.status_code == 200 and response.mimetype == "application/pdf"
    assert response.data.startswith(b"%PDF") and name in response.headers["Content-Disposition"]


def test_빈_서식이_없는_서류는_404(anon_client):
    assert anon_client.get("/documents/blank/shipping_instruction.pdf").status_code == 404


def test_빈_서식_단추가_서류_작성과_시작_화면에_있다(client):
    html = client.get("/documents/new").get_data(as_text=True)
    assert "/documents/blank/commercial_invoice.pdf" in html
    assert "/documents/blank/packing_list_std.pdf" in html
    assert "/documents/blank/__KIND__.pdf" in client.get("/").get_data(as_text=True)
    assert "준비 중" not in (STATIC / "js/home.js").read_text(encoding="utf-8")


def test_빈_서식_칸에는_아무_글자도_찍지_않는다():
    from app.processors import document_form

    assert document_form.BLANK not in document_form.DRAFT_NOTE


# --- 4. 상담 창은 눌렀을 때만 ---------------------------------------------------------------

def test_상담_창은_저절로_열리지_않는다():
    js = (STATIC / "js/support_chat.js").read_text(encoding="utf-8")
    code = "\n".join(line for line in js.splitlines() if not line.strip().startswith("//"))
    # 여는 곳은 단추(fab) 클릭과, 이미 열린 창을 새 대화로 다시 그리는 곳뿐입니다.
    opens = re.findall(r"^.*\bopen\(.*$", code, re.M)
    opens = [line for line in opens if "function open" not in line]
    assert len(opens) == 2, opens
    assert any("fab.addEventListener" in line for line in opens)
    assert any("!panel.hidden" in line for line in opens)


# --- 5. 품목별 패킹 정보 ---------------------------------------------------------------------

def _five_items(app):
    items = [{"product_description": name, "amount": "10"}
             for name in ("LIPSTICK", "TONER", "CREAM", "MASK", "SERUM")]
    # 기본 정보(상호·주소)는 모두 채워 둡니다. 여기서 보려는 것은 품목별 패킹 정보입니다.
    form = {"fields": {"exporter_name": "A", "exporter_address": "Seoul, Korea",
                       "buyer_name": "B", "buyer_address": "1 Test Ave, LA",
                       "origin_code": "KRPUS", "destination_code": "USLAX"}, "items": items}
    return pipeline.start({"form": form, "document_label": "문서", "kinds": ["packing_list_std"]})


def test_품목이_여럿이면_몇_종인지_짚어_패킹_정보를_묻는다(app):
    state = _five_items(app)
    reply = state["reply"]
    assert "업로드해주신 문서에서 품목 5종의 세부 패킹 데이터가 확인되지 않습니다" in reply
    assert "1. 품목 5개의 각각의 순중량(Net Weight) 및 총중량(Gross Weight)" in reply
    assert "2. 포장 박스 규격(가로 x 세로 x 높이 cm) 및 총 박스(Carton) 수" in reply
    assert "- 3번 CREAM:" in reply and "1번 품목:" in reply
    # 번호로 답할 때의 순서도 말과 같습니다. (패킹 칸은 맨 뒤)
    assert [row["key"] for row in state["missing"]][:2] == ["items.weight", "items.dims"]


def test_품목_번호를_붙인_답을_그_품목에_넣는다(app):
    state = _five_items(app)
    message = ("1번 품목: 순중량 6.5kg, 총중량 80kg, 40x30x25cm, 10박스\n"
               "품목 2 - net 3kg gross 1.2톤 50x40x30 20 ctns\n"
               "3번 박스당 8kg 30x30x30 5박스")
    merged = pipeline.merge({"message": message, "draft": state["draft"], "kinds": ["packing_list_std"],
                             "asked": [row["key"] for row in state["missing"]]})
    first, second, third = merged["draft"]["items"][:3]

    assert (first["net_weight_kg"], first["quantity"], first["length_cm"]) == ("6.5", "10", "40")
    assert first["weight_per_package_kg"] == "8"            # 줄 전체 80kg ÷ 10박스
    assert second["weight_per_package_kg"] == "60"          # 1.2톤 ÷ 20박스
    assert third["weight_per_package_kg"] == "8" and third["quantity"] == "5"
    assert merged["notes"] == []                            # "3번"을 다른 질문으로 읽지 않습니다
    assert "품목 2종의 세부 패킹 데이터" in merged["reply"]      # 남은 두 품목만 다시 묻습니다


def test_품목이_하나면_예전처럼_번호로_묻는다(app):
    form = {"fields": {"exporter_name": "A", "exporter_address": "Seoul, Korea",
                       "buyer_name": "B", "buyer_address": "1 Test Ave, LA",
                       "origin_code": "KRPUS", "destination_code": "USLAX"},
            "items": [{"product_description": "LIPSTICK"}]}
    reply = pipeline.start({"form": form, "kinds": ["packing_list_std"]})["reply"]
    assert "세부 패킹 데이터" not in reply and "누락되어 있습니다" in reply


# --- 6. 금액 칸 통화 표기 -------------------------------------------------------------------

def test_금액_칸에_고른_통화가_붙는다(client):
    html = client.get("/documents/new").get_data(as_text=True)
    template = html[html.index("data-doc-item-template"):]
    for label in ("단가", "금액"):
        assert re.search(label + r'<span class="doc_money_unit" data-money-unit> \(USD\)</span>', template), label
    assert 'placeholder="USD 12.50"' in template and "data-doc-total" in html
    js = (STATIC / "js/doc_form.js").read_text(encoding="utf-8")
    assert 'form.elements.currency.addEventListener("change", applyCurrency)' in js


def test_검토_창의_금액_머리에도_통화가_붙는다(app):
    draft = {"currency": "EUR", "exporter_name": "A", "buyer_name": "B",
             "items": [{"product_description": "X", "quantity": "2", "unit_price": "3", "amount": "6"}]}
    doc = pipeline.review_document("commercial_invoice", draft)
    labels = [column["label"] for column in doc["columns"]]
    assert "Unit price (EUR)" in labels and "Amount (EUR)" in labels
    assert doc["currency"] == "EUR"


# --- 7. 팝업 스크롤 ----------------------------------------------------------------------

def _rule(css: str, selector: str) -> str:
    return css[css.index(selector + " {"):].split("}", 1)[0]


@pytest.mark.parametrize("file, box, body", [
    ("css/base.css", ".hs_modal_box", ".hs_modal_body .ac_list"),
    ("css/home.css", ".dp_box", ".dp_edit"),
    ("css/shell.css", ".fx_box", ".fx_panel"),
    ("css/base.css", ".support_panel", ".support_log"),
])
def test_팝업은_화면_안에_들고_본문만_스크롤된다(file, box, body):
    css = (STATIC / file).read_text(encoding="utf-8")
    box_rule = _rule(css, box)
    assert re.search(r"max-height: [^;]*calc\((85|90)vh / var\(--ui_scale, 1\)\)", box_rule), box
    assert "flex-direction: column" in box_rule and "overflow: hidden" in box_rule, box
    body_rule = _rule(css, body)
    assert "overflow-y: auto" in body_rule and "min-height: 0" in body_rule, body
