"""대화에 화물을 적으면 CBM과 LCL/FCL을 바로 알려 줍니다.

"수건 300박스, 한 박스 40x61x70cm에 50kg"이라고 적으면 사람은 그 다음에 꼭
"몇 CBM이고 LCL인가요 FCL인가요"를 묻습니다. 그건 계산이라 AI를 기다릴 이유가 없습니다.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services import chat_capture_service, support_chat_service

ANSWER = {"success": True, "source": "api", "data": {"answer": "수건 수출은 …"}}
TALK = "수건 300박스, 한 박스 40x61x70cm에 50kg입니다"


def test_적어_주신_치수로_CBM을_계산한다(app):
    item = chat_capture_service.read(TALK)["items"][0]
    cargo = chat_capture_service.cargo_summary(item)

    # 0.40 × 0.61 × 0.70 = 0.1708 CBM, × 300 = 51.24
    assert cargo["per_package_cbm"] == 0.1708
    assert cargo["total_cbm"] == 51.24
    assert cargo["total_weight_kg"] == 15000


def test_운임톤으로_LCL_FCL을_정한다(app):
    cargo = chat_capture_service.cargo_summary(chat_capture_service.read(TALK)["items"][0])

    # 부피(51.24)가 무게(15t)보다 크니 운임톤은 부피 쪽입니다.
    assert cargo["revenue_ton"] == 51.24
    assert cargo["mode"] == "FCL" and cargo["containers"] >= 1
    assert cargo["container_type"] in ("20GP", "40GP", "40HC")
    assert "R/T" in cargo["reason"]


def test_작은_화물은_LCL이라고_답한다(app):
    item = chat_capture_service.read("비누 30박스, 한 박스 30x20x20cm에 5kg입니다")["items"][0]
    cargo = chat_capture_service.cargo_summary(item)

    assert cargo["total_cbm"] == 0.36
    assert cargo["mode"] == "LCL"


@pytest.mark.parametrize("말", [
    "수건 300박스 보냅니다",                       # 치수가 없습니다
    "한 박스 40x61x70cm입니다",                    # 수량이 없습니다
    "미국에 수출하려면 어떻게 하나요",              # 화물 이야기가 아닙니다
])
def test_값이_모자라면_계산하지_않는다(app, 말):
    read = chat_capture_service.read(말)
    item = (read.get("items") or [{}])[0] if read else {}
    assert chat_capture_service.cargo_summary(item) is None


def test_상담_답변에_계산이_함께_온다(app, anon_client):
    """로그인하지 않아도 계산은 해 드립니다. (담아 두는 것만 로그인이 필요합니다)"""

    with patch.object(support_chat_service.ai_client, "available", return_value=True), \
         patch.object(support_chat_service.ai_client, "chat", return_value=ANSWER):
        response = anon_client.post("/api/support-chat", json={"question": TALK})

    cargo = response.get_json()["data"]["cargo"]
    assert cargo["total_cbm"] == 51.24 and cargo["mode"] == "FCL"


def test_화면이_계산을_그린다():
    from pathlib import Path

    js = (Path(__file__).parent.parent / "app/static/js/home.js").read_text(encoding="utf-8")
    assert "function appendCargo" in js and "response.data.cargo" in js
    css = (Path(__file__).parent.parent / "app/static/css/home.css").read_text(encoding="utf-8")
    assert ".answer_cargo" in css
