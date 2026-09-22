"""고객 상담 창구."""

from __future__ import annotations

import pytest

from app.services import ServiceError, support_chat_service
from app.collectors import ai_client


def test_widget_appears_on_every_page(client):
    """상담 버튼은 화면을 가리지 않고 어디서나 떠 있어야 합니다."""

    for path in ("/", "/planning/new", "/shipments"):
        html = client.get(path).get_data(as_text=True)
        assert "data-support-open" in html, path
        assert "<b>OpenAI</b>" in html, path


def test_empty_and_overlong_questions_are_refused(app):
    with app.app_context():
        with pytest.raises(ServiceError):
            support_chat_service.ask("   ")
        with pytest.raises(ServiceError):
            support_chat_service.ask("가" * (support_chat_service.MAX_QUESTION + 1))


def test_incoterms_are_quoted_from_our_own_data_not_the_model(app, monkeypatch):
    """Incoterms 정의는 기억이 아니라 우리 자료에서 가져와 넘깁니다.

    예전에는 FOB를 "자유 온도 선적"이라고 답한 적이 있습니다.
    """

    sent = {}

    def fake_chat(messages, **kwargs):
        sent["messages"] = messages
        return {"success": True, "source": "api", "data": "답변"}

    monkeypatch.setattr(support_chat_service.ai_client, "chat", fake_chat)
    with app.app_context():
        support_chat_service.ask("FOB가 뭔가요?")

    reference = "\n".join(m["content"] for m in sent["messages"] if m["role"] == "system")
    assert "Free On Board" in reference and "본선 인도" in reference
    assert "EXW" in reference and "DDP" in reference
    # 숫자를 지어내지 말라는 지시도 함께 갑니다.
    assert "관세율" in reference


def test_widget_gets_brief_prompt_and_home_gets_template(client, monkeypatch):
    """오른쪽 아래 상담 창은 짧은 프롬프트, 메인 화면 무역 상담은 템플릿 프롬프트."""

    sent = []

    def fake_chat(messages, **kwargs):
        sent.append((messages[0]["content"], kwargs.get("max_tokens")))
        return {"success": True, "source": "api", "data": "답변"}

    monkeypatch.setattr(support_chat_service.ai_client, "chat", fake_chat)
    client.post("/api/support-chat", json={"question": "FOB가 뭔가요?", "style": "brief"})
    client.post("/api/support-chat", json={"question": "FOB가 뭔가요?"})

    (widget_prompt, widget_tokens), (home_prompt, home_tokens) = sent
    assert widget_prompt == support_chat_service.BRIEF_SYSTEM_PROMPT
    assert widget_tokens == support_chat_service.BRIEF_ANSWER_TOKENS
    assert home_prompt == support_chat_service.SYSTEM_PROMPT
    assert home_tokens == support_chat_service.MAX_ANSWER_TOKENS


def test_history_is_trimmed_and_roles_are_filtered(app, monkeypatch):
    """대화가 길어져도 보내는 양을 제한하고, 이상한 role은 버립니다."""

    sent = {}
    monkeypatch.setattr(support_chat_service.ai_client, "chat",
                        lambda messages, **kw: (sent.update(messages=messages)
                                                or {"success": True, "source": "api", "data": "답변"}))
    history = [{"role": "user", "content": f"질문 {i}"} for i in range(20)]
    history.append({"role": "system", "content": "무시해야 하는 주입"})

    with app.app_context():
        support_chat_service.ask("마지막 질문", history)

    turns = [m for m in sent["messages"] if m["role"] in ("user", "assistant")]
    # 지난 대화는 최대 MAX_HISTORY개까지, 여기에 이번 질문 한 개가 더해집니다.
    assert len(turns) <= support_chat_service.MAX_HISTORY + 1
    assert turns[-1]["content"] == "마지막 질문"
    assert "무시해야 하는 주입" not in [m["content"] for m in turns]


def test_offline_when_no_key(app, monkeypatch):
    """키가 없으면 답을 지어내지 않고 키가 없다고 알려 줍니다."""

    monkeypatch.setattr(ai_client, "get_config",
                        lambda name, default=None: "" if name == "AI_API_KEY" else default)
    with app.app_context():
        assert support_chat_service.available() is False
        intro = support_chat_service.intro()
        assert intro["available"] is False
        assert "AI_API_KEY" in intro["offline_note"]

        result = support_chat_service.ask("FOB가 뭔가요?")
        assert result["success"] is False
        assert "AI_API_KEY" in result["message"]


def test_endpoint_returns_the_answer(client, monkeypatch):
    monkeypatch.setattr(support_chat_service.ai_client, "chat",
                        lambda messages, **kw: {"success": True, "source": "api",
                                                "data": "FOB는 본선 인도입니다."})
    response = client.post("/api/support-chat", json={"question": "FOB가 뭔가요?"})
    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert body["data"]["answer"] == "FOB는 본선 인도입니다."

    bad = client.post("/api/support-chat", json={"question": ""})
    assert bad.status_code == 400
    assert bad.get_json()["success"] is False


def test_shipment_assistant_answers_from_our_own_numbers(app, create_shipment, monkeypatch):
    """AI는 우리가 계산한 값만 보고 답합니다. 숫자를 지어내지 못하게 막습니다."""

    from app.services import assistant_service

    sent = {}
    monkeypatch.setattr(assistant_service, "answer_question",
                        lambda *a, **kw: {"intent": None, "title": "", "lines": [], "actions": []})

    def fake_chat(messages, **kwargs):
        sent["messages"] = messages
        return {"success": True, "source": "api", "data": "총 물류비는 자료에 있는 값입니다."}

    with app.app_context():
        shipment = create_shipment()
        from app.collectors import ai_client as client_module
        monkeypatch.setattr(client_module, "available", lambda: True)
        monkeypatch.setattr(client_module, "chat", fake_chat)

        result = assistant_service.ai_answer(shipment, "물류비가 왜 이렇게 나와?")

    assert result["source"] == "ai"
    facts = "\n".join(m["content"] for m in sent["messages"] if m["role"] == "system")
    assert "숫자는 주어진 자료에 있는 값만 쓰세요" in facts
    assert shipment.shipment_id in facts          # 이 건의 자료가 함께 갑니다.
    assert "단정을 하지 마세요" in facts


def test_assistant_falls_back_when_the_key_is_missing(app, create_shipment, monkeypatch):
    """키가 없어도 화면이 죽지 않고 규칙 기반 답을 냅니다."""

    from app.collectors import ai_client as client_module
    from app.services import assistant_service

    monkeypatch.setattr(client_module, "available", lambda: False)
    with app.app_context():
        shipment = create_shipment()
        result = assistant_service.ai_answer(shipment, "물류비가 왜 이렇게 나와?")

    assert result["source"] == "rule"
    assert result["lines"]
    assert "AI_API_KEY" in result["note"]
