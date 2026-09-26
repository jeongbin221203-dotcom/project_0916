"""이용자에게 **이용자의 말**로 알려 주는가.

AI 키가 없을 때 화면에 이렇게 나갔습니다.
  "AI 상담 키(AI_API_KEY)가 없습니다. .env에 키를 넣으면 바로 동작합니다."
수출자에게 할 말이 아닙니다. 키 이름·.env 는 운영하는 사람의 말이고, 그대로
보여 주면 이용자는 자기가 뭘 잘못한 줄 알고 멈춥니다. 무엇이 막혔고 **대신
무엇을 쓸 수 있는지**를 적어야 합니다. 설정 이야기는 서버 기록에만 남깁니다.

그리고 실패 사유(error_code)가 떨어져 나가 우리 쪽 키 문제도 502(기관이 죽음)로
나갔습니다. 화면·감시 도구는 그걸 "바깥이 죽었다"로 읽습니다. (2026-09-26)
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# 이용자 화면으로 나가는 글을 만드는 곳. (조회처 설정 화면은 운영자용이라 뺍니다)
USER_FACING = [
    "app/collectors/ai_client.py",
    "app/services/support_chat_service.py",
    "app/services/assistant_service.py",
    "app/services/document_extract_service.py",
    "app/services/intake_service.py",
    "app/services/translate_service.py",
]
SETTING_WORDS = (".env", "AI_API_KEY", "환경변수를 넣", "config.py")


@pytest.mark.parametrize("where", USER_FACING)
def test_이용자에게_설정_이야기를_하지_않는다(where):
    """키 이름·.env 는 운영하는 사람의 말입니다."""

    leaks = []
    for line in (ROOT / where).read_text(encoding="utf-8").split("\n"):
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith('"""'):
            continue
        if "logger" in line:                      # 서버 기록에는 적어도 됩니다
            continue
        if not re.search(r'["\'].*[가-힣]', line):  # 한국어 글자열만 봅니다
            continue
        for word in SETTING_WORDS:
            if word in line:
                leaks.append(line.strip()[:100])
    assert not leaks, f"{where} 에서 이용자에게 설정 이야기를 합니다: {leaks}"


def test_AI가_없어도_무엇을_쓸_수_있는지_알려_준다(client):
    response = client.post("/api/support-chat", json={"question": "서류 뭐가 필요해요?"})
    if response.status_code == 200:
        pytest.skip("이 환경에는 AI 키가 있습니다")
    message = response.get_json()["message"]
    assert ".env" not in message and "AI_API_KEY" not in message
    assert "쓰실 수 있습니다" in message, "대신 무엇을 쓸 수 있는지 알려 주어야 합니다"


def test_우리_쪽_키_문제는_502가_아니라_503이다(client):
    """502 는 '바깥 기관이 죽었다'는 뜻입니다. 관세청은 멀쩡합니다."""

    response = client.post("/api/support-chat", json={"question": "서류 뭐가 필요해요?"})
    if response.status_code == 200:
        pytest.skip("이 환경에는 AI 키가 있습니다")
    assert response.status_code == 503
    assert response.get_json()["error_code"] == "API_AUTH_FAILED"


def test_빈_질문은_400이다(client):
    response = client.post("/api/support-chat", json={"question": ""})
    assert response.status_code == 400
    assert response.get_json()["error_code"] == "VALIDATION_ERROR"


def test_지식으로_답할_수_있는_질문은_AI가_없어도_답한다(client):
    response = client.post("/api/support-chat", json={"question": "CBM이 뭐예요?"})
    assert response.status_code == 200
    assert response.get_json()["data"]["answer"]
