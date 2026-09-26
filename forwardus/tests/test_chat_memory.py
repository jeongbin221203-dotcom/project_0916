"""Entity / State 분리.

Entity (무역 상담)      주고받은 말을 전부 DB에 남깁니다. 오래된 것은 요약해서 함께 들고 갑니다.
State  (운송 계획·서류)  대화 원문은 저장하지 않고 핵심 값만 work_drafts에 남깁니다.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.models import ChatMessage, ChatThread, WorkDraft
from app.services import chat_memory_service as memory
from app.services import support_chat_service

ANSWER = {"success": True, "source": "api", "data": {"answer": "FOB는 본선 인도 조건입니다."}}


def _member(app, email="kim@example.com"):
    browser = app.test_client()
    browser.post("/auth/signup", data={"email": email, "password": "secret123",
                                       "password_confirm": "secret123"})
    return browser


def _ask(browser, question, **extra):
    with patch.object(support_chat_service.ai_client, "available", return_value=True), \
         patch.object(support_chat_service.ai_client, "chat", return_value=ANSWER):
        return browser.post("/api/support-chat", json={"question": question, **extra})


# --- Entity: 무역 상담은 전부 기억합니다 -------------------------------------------------

def test_상담은_주고받은_말을_모두_남긴다(app):
    browser = _member(app)

    _ask(browser, "FOB가 뭔가요?")
    _ask(browser, "그럼 CIF와 차이는요?")

    rows = ChatMessage.query.order_by(ChatMessage.id).all()
    assert [row.role for row in rows] == ["user", "assistant", "user", "assistant"]
    assert rows[0].text == "FOB가 뭔가요?" and rows[2].text == "그럼 CIF와 차이는요?"
    assert all(row.text for row in rows if row.role == "assistant")


def test_지난_대화를_AI에게_이어_보낸다(app):
    browser = _member(app)
    _ask(browser, "부산에서 LA로 화장품을 보냅니다")

    with patch.object(support_chat_service.ai_client, "available", return_value=True), \
         patch.object(support_chat_service.ai_client, "chat", return_value=ANSWER) as call:
        browser.post("/api/support-chat", json={"question": "그 건은 언제 출항인가요?"})

    sent = str(call.call_args[0][0])
    # 브라우저가 아무것도 보내지 않아도 서버가 기억해 둔 대화를 넣습니다.
    assert "부산에서 LA로 화장품을 보냅니다" in sent


def test_계좌번호는_기억에도_남기지_않는다(app):
    browser = _member(app)

    _ask(browser, "대금은 Shinhan Bank A/C 100-200-300400으로 받습니다")

    saved = " ".join(row.text for row in ChatMessage.query.all())
    assert "100-200-300400" not in saved and "[계좌번호]" in saved


def test_로그인_전에는_남기지_않는다(app, anon_client):
    with patch.object(support_chat_service.ai_client, "available", return_value=True), \
         patch.object(support_chat_service.ai_client, "chat", return_value=ANSWER):
        response = anon_client.post("/api/support-chat", json={"question": "FOB가 뭔가요?"})

    assert response.status_code == 200
    assert ChatMessage.query.count() == 0


def test_오래된_대화는_요약으로_접고_원문은_남긴다(app):
    from app.models import User

    user = User.query.filter_by(email=app.config["MASTER_EMAIL"]).one()
    for no in range(1, 16):
        memory.remember(user, "user", f"질문 {no}")
        memory.remember(user, "assistant", f"답 {no}")

    with patch.object(memory.ai_client, "available", return_value=True), \
         patch.object(memory.ai_client, "chat",
                      return_value={"success": True, "source": "api",
                                    "data": "부산→LA 화장품 건. 조건 FOB로 정함."}):
        summary = memory.summarize(user)

    assert "FOB" in summary
    thread = ChatThread.query.filter_by(user_id=user.id).one()
    assert thread.summary == summary and thread.summarized_until_id > 0
    # 원문은 지우지 않습니다. 나중에 다시 볼 수 있어야 합니다.
    assert ChatMessage.query.filter_by(user_id=user.id).count() == 30

    kept = memory.context(user)
    assert kept["summary"] == summary
    assert len(kept["history"]) == memory.RECENT_TURNS      # AI에는 요약 + 최근 몇 턴만


def test_AI_키가_없으면_요약하지_않고_기억은_그대로다(app):
    from app.models import User

    user = User.query.filter_by(email=app.config["MASTER_EMAIL"]).one()
    for no in range(30):
        memory.remember(user, "user", f"질문 {no}")

    with patch.object(memory.ai_client, "available", return_value=False):
        assert memory.summarize(user) == ""
    assert ChatMessage.query.filter_by(user_id=user.id).count() == 30


def test_지난_상담을_다시_볼_수_있고_새_대화로_지운다(app):
    browser = _member(app)
    _ask(browser, "FOB가 뭔가요?")

    data = browser.get("/api/chat-memory").get_json()["data"]
    assert [row["role"] for row in data["messages"]] == ["user", "assistant"]
    assert data["messages"][0]["text"] == "FOB가 뭔가요?"

    assert browser.delete("/api/chat-memory").status_code == 200
    assert browser.get("/api/chat-memory").get_json()["data"]["messages"] == []
    assert ChatMessage.query.count() == 0 and ChatThread.query.count() == 0


def test_회원마다_기억이_따로다(app):
    alice, bob = _member(app, "a@example.com"), _member(app, "b@example.com")
    _ask(alice, "앨리스의 건입니다")
    _ask(bob, "밥의 건입니다")

    mine = bob.get("/api/chat-memory").get_json()["data"]["messages"]
    assert [row["text"] for row in mine if row["role"] == "user"] == ["밥의 건입니다"]


# --- State: 운송 계획·서류 작성은 값만 남깁니다 ---------------------------------------------

def test_서류_계획은_대화_원문이_아니라_값만_저장한다(app):
    browser = _member(app)
    browser.put("/api/work-draft", json={"source": "chat", "fields": {
        "exporter_name": "FORWARD CO", "origin_code": "KRPUS", "destination_code": "USLAX",
        "incoterms": "FOB", "currency": "USD"},
        "items": [{"product_description": "Cream", "quantity": "500"}]})

    draft = WorkDraft.query.one()
    saved = str(draft.data)
    assert draft.data["fields"]["origin_code"] == "KRPUS"
    assert draft.data["items"][0]["quantity"] == "500"
    # 대화 문장은 들어가지 않습니다. 허용한 칸 이름만 남습니다.
    assert "?" not in saved and "합니다" not in saved
    from app.services import work_draft_service

    assert set(draft.data["fields"]) <= set(work_draft_service.SHARED_FIELDS)
    # 서류·계획 쪽은 상담 기억 표를 쓰지 않습니다.
    assert ChatMessage.query.count() == 0


@pytest.mark.parametrize("field", ["buyer_email", "notify_party", "attention"])
def test_State에는_바이어_연락처를_두지_않는다(app, field):
    """연락처는 서버에 남기지 않습니다. (주소는 2026-09부터 남깁니다 — 아래 테스트)"""

    browser = _member(app)
    browser.put("/api/work-draft", json={"source": "document",
                                         "fields": {"exporter_name": "A", field: "비밀 값"},
                                         "items": []})

    assert "비밀 값" not in str(WorkDraft.query.one().data)


def test_바이어_주소는_남깁니다(app):
    """같은 바이어에게 다시 보낼 때 주소를 또 적게 하면 오타가 납니다.

    그 오타는 B/L과 송장에 그대로 찍히고, 도착지에서 화물을 못 찾는 일로 이어집니다.
    (2026-09 사용자 결정 — 계좌번호·SWIFT는 여전히 어디에도 남기지 않습니다)
    """

    browser = _member(app)
    browser.put("/api/work-draft", json={
        "source": "document",
        "fields": {"buyer_name": "ABC", "buyer_address": "1 Secret Ave, Istanbul",
                   "buyer_email": "a@b.com"},
        "items": []})

    stored = str(WorkDraft.query.one().data)
    assert "1 Secret Ave, Istanbul" in stored      # 주소는 남습니다
    assert "a@b.com" not in stored                 # 연락처는 남기지 않습니다


# --- 대화에 적은 화물 정보 담아 두기 (State) ---------------------------------------------

CARGO_TALK = ("부산에서 로스앤젤레스로 화장품 500박스 보냅니다. "
              "한 박스 40x30x25cm에 12kg이고 FOB, USD 결제입니다.")


def test_대화에_적은_화물_정보를_담아_둔다(app):
    from app.services import chat_capture_service

    browser = _member(app)
    response = _ask(browser, CARGO_TALK)
    captured = response.get_json()["data"].get("captured") or []

    assert "출발지" in captured and "수량" in captured
    fields = browser.get("/api/work-draft/planning").get_json()["data"]["fields"]
    assert fields["quantity"] == "500" and fields["length_cm"] == "40"
    assert fields["weight_per_package_kg"] == "12" and fields["currency"] == "USD"
    # 항구는 코드로 바꿔 둡니다. 화면이 그대로 씁니다.
    data = browser.get("/api/work-draft").get_json()["data"]["fields"]
    assert data["origin_code"] == "KRPUS" and data["destination_code"] == "USLAX"
    assert data["incoterms"] == "FOB"
    assert chat_capture_service.read("안녕하세요") == {}


def test_대화가_말한_것만_덮고_나머지는_그대로_둔다(app):
    """**방금 말한 것이 이깁니다.** 다만 말하지 않은 칸은 건드리지 않습니다.

    예전에는 "이미 담아 둔 값은 대화가 덮지 않는다"였습니다. 화면에서 적은 값을
    지키려던 것인데, 그러면 대화로는 아무것도 **고칠 수가 없었습니다.**
    "부산에서 로스앤젤레스로 보냅니다"라고 적어도 지난 건이 그대로 남아,
    다음 질문의 머리글에 엉뚱한 구간이 붙었습니다. 사람이 방금 적은 말보다
    더 새로운 값은 없습니다. (2026-09-26)
    """

    browser = _member(app)
    browser.put("/api/work-draft", json={
        "source": "document", "items": [],
        "fields": {"origin_code": "KRINC", "incoterms": "CIF", "buyer_name": "OLD BUYER"}})

    _ask(browser, CARGO_TALK)

    fields = browser.get("/api/work-draft").get_json()["data"]["fields"]
    # 대화에서 말한 것 — 덮습니다.
    assert fields["origin_code"] == "KRPUS"
    assert fields["incoterms"] == "FOB"
    assert fields["destination_code"] == "USLAX"
    # 대화에 없던 것 — 그대로 둡니다.
    assert fields["buyer_name"] == "OLD BUYER"


def test_로그인_전에는_담지_않는다(app, anon_client):
    from app.models import WorkDraft

    with patch.object(support_chat_service.ai_client, "available", return_value=True), \
         patch.object(support_chat_service.ai_client, "chat", return_value=ANSWER):
        response = anon_client.post("/api/support-chat", json={"question": CARGO_TALK})

    assert response.status_code == 200
    assert "captured" not in response.get_json()["data"]
    assert WorkDraft.query.count() == 0


def test_담아_둔_값에는_대화_원문이_없다(app):
    from app.models import WorkDraft

    browser = _member(app)
    _ask(browser, CARGO_TALK)

    saved = str(WorkDraft.query.one().data)
    assert "보냅니다" not in saved and "결제입니다" not in saved


def test_캐시가_남의_화물정보를_흘리지_않는다(app, anon_client):
    """캐시는 질문으로만 찾습니다. 사람별 값이 담기면 다음 사람에게 그대로 보입니다.

    회원이 "부산에서 LA로 …"라고 적으면 그 값이 담기고(captured), 같은 질문을 한
    로그인하지 않은 사람에게 캐시가 그 답을 돌려줍니다. 그때 담아 둔 값까지 따라가면
    남의 화물 내용이 새어 나갑니다.
    """

    from app.services import faq_cache

    browser = _member(app)
    mine = _ask(browser, CARGO_TALK).get_json()
    assert mine["data"].get("captured"), "회원 답에는 담아 둔 값이 붙어야 합니다"

    # 같은 질문을 로그인하지 않은 사람이 합니다. (캐시에서 나올 수 있습니다)
    with patch.object(support_chat_service.ai_client, "available", return_value=True), \
         patch.object(support_chat_service.ai_client, "chat", return_value=ANSWER):
        response = anon_client.post("/api/support-chat", json={"question": CARGO_TALK})

    assert "captured" not in response.get_json()["data"]
    # 캐시에 담긴 내용 자체에도 없어야 합니다.
    assert all("captured" not in row["payload"] for row in faq_cache._store.values())
