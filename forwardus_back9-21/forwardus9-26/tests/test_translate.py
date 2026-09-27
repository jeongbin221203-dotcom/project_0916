"""그대로 보내기 글을 바이어의 언어로 옮깁니다.

숫자와 계좌번호가 걸린 자리라 세 가지를 봅니다.
  1. 계좌번호는 가린 채 AI로 나가고, 돌아온 뒤 제자리로 돌아옵니다.
  2. 실패하면 반쯤 옮긴 글 대신 실패를 알립니다.
  3. 남의 Shipment 글은 옮겨 주지 않습니다.
"""

from __future__ import annotations

import pytest

from app.services import ServiceError, translate_service


@pytest.fixture()
def fake_ai(monkeypatch):
    """AI를 부르지 않고 흉내만 냅니다. (보낸 내용은 sent에 남깁니다)"""

    sent: dict = {}

    def fake_chat(messages, **kwargs):
        sent["messages"] = messages
        sent["max_tokens"] = kwargs.get("max_tokens")
        return {"success": True, "source": "api",
                "data": "[EN] " + messages[-1]["content"]}

    monkeypatch.setattr(translate_service.ai_client, "chat", fake_chat)
    monkeypatch.setattr(translate_service.ai_client, "available", lambda: True)
    return sent


def test_고른_언어로_옮긴다(app, fake_ai):
    result = translate_service.translate("수출자 상호: 포워더스", "en")

    assert result["code"] == "en" and "영어" in result["language"]
    assert result["text"].startswith("[EN] 수출자 상호")
    # 어느 언어로 옮길지 AI에게 분명히 알립니다.
    assert "English" in fake_ai["messages"][0]["content"]


def test_계좌번호는_가린_채_보내고_돌아온_뒤_되돌린다(app, fake_ai):
    text = "■ 결제\n - 입금계좌: 신한은행 110-123-456789\n - 신고가격: USD 6,250.00"

    result = translate_service.translate(text, "ja")

    sent = fake_ai["messages"][-1]["content"]
    assert "110-123-456789" not in sent and "[ACCOUNT_1]" in sent
    # 되돌려 주지 않으면 이용자가 보낼 글에서 계좌번호가 사라집니다.
    assert "110-123-456789" in result["text"]
    # 금액은 가리지 않습니다. 가리면 바이어가 금액을 못 읽습니다.
    assert "6,250.00" in sent


def test_빈_글과_모르는_언어는_거절한다(app, fake_ai):
    for text, code in (("", "en"), ("   ", "en"), ("수출자", "kl"), ("수출자", "")):
        with pytest.raises(ServiceError):
            translate_service.translate(text, code)


def test_너무_길면_거절한다(app, fake_ai):
    with pytest.raises(ServiceError):
        translate_service.translate("가" * (translate_service.MAX_CHARS + 1), "en")


def test_AI_키가_없으면_그렇게_알린다(app, monkeypatch):
    monkeypatch.setattr(translate_service.ai_client, "available", lambda: False)

    with pytest.raises(ServiceError) as error:
        translate_service.translate("수출자 상호: 포워더스", "en")
    assert error.value.error_code == "AI_UNAVAILABLE"


def test_AI가_실패하면_반쯤_옮긴_글을_주지_않는다(app, monkeypatch):
    monkeypatch.setattr(translate_service.ai_client, "available", lambda: True)
    monkeypatch.setattr(translate_service.ai_client, "chat",
                        lambda messages, **kwargs: {"success": False, "source": "api",
                                                    "error_code": "API_TIMEOUT",
                                                    "message": "응답 시간이 초과되었습니다."})

    with pytest.raises(ServiceError) as error:
        translate_service.translate("수출자 상호: 포워더스", "en")
    assert error.value.status == 502


def test_화면에서_언어를_고르고_옮긴다(client, create_shipment, fake_ai):
    shipment = create_shipment()

    page = client.get(f"/documents/{shipment.shipment_id}/customs-filing").get_data(as_text=True)
    assert "번역할 언어" in page and 'data-translate-run' in page

    response = client.post(f"/documents/{shipment.shipment_id}/customs-filing/translate",
                           json={"text": "수출자 상호: 포워더스", "language": "en"})
    assert response.status_code == 200
    assert response.get_json()["data"]["text"].startswith("[EN]")


def test_모르는_언어는_400으로_답한다(client, create_shipment, fake_ai):
    shipment = create_shipment()

    response = client.post(f"/documents/{shipment.shipment_id}/customs-filing/translate",
                           json={"text": "수출자", "language": "kl"})
    assert response.status_code == 400


def test_남의_Shipment는_옮겨_주지_않는다(app, create_shipment, fake_ai):
    from app.models import User

    shipment = create_shipment()
    other = app.test_client()
    other.post("/auth/signup", data={"email": "other@example.com",
                                     "password": "secret123", "password_confirm": "secret123"})
    assert User.query.filter_by(email="other@example.com").count() == 1

    response = other.post(f"/documents/{shipment.shipment_id}/customs-filing/translate",
                          json={"text": "수출자", "language": "en"})
    assert response.status_code == 404
