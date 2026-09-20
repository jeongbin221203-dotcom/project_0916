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
