"""CBM 기준 LCL·FCL 권고와, 답변 아래에 붙는 관련 링크."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.processors import answer_links, sea_mode_advisor
from app.services import support_chat_service

# --- CBM 기준 LCL · FCL ----------------------------------------------------------------


def test_짐이_적으면_LCL을_권한다():
    result = sea_mode_advisor.recommend(8, 3_000)

    assert result["mode"] == "LCL" and result["confidence"] == "clear"
    assert result["revenue_ton"] == 8
    assert "혼재" in result["reason"]
    # 대신 며칠 더 걸린다는 것을 함께 알립니다.
    assert any("일주일" in note for note in result["notes"])


def test_기준을_넘으면_FCL을_권한다():
    result = sea_mode_advisor.recommend(20, 8_000)

    assert result["mode"] == "FCL" and result["confidence"] == "clear"
    # 가장 작은 컨테이너(20GP)를 기준으로 봅니다. 40GP로 재면 빈자리가 커 보입니다.
    assert result["container_type"] == "20GP" and result["containers"] == 1
    assert f"{sea_mode_advisor.FCL_CLEAR_RT:g}" in result["reason"]


def test_경계_구간은_둘_다_받아_비교하라고_말한다():
    result = sea_mode_advisor.recommend(13, 6_000)

    assert result["confidence"] == "close"
    assert "비교" in result["reason"]


def test_무거운_화물은_부피가_작아도_FCL_쪽으로_본다():
    """LCL은 부피와 무게 중 큰 쪽으로 값을 매깁니다. 5 CBM이어도 9톤이면 9 R/T입니다."""

    light = sea_mode_advisor.recommend(5, 1_000)
    heavy = sea_mode_advisor.recommend(5, 9_000)

    assert light["mode"] == "LCL"
    assert heavy["mode"] == "FCL" and heavy["confidence"] == "close"
    assert any("무거운 화물" in note for note in heavy["notes"])


def test_한_대에_안_들어가면_대수를_세어_FCL이다():
    result = sea_mode_advisor.recommend(60, 20_000)

    assert result["mode"] == "FCL" and result["containers"] >= 1
    assert result["fill_rate"] > 0


def test_컨테이너를_반도_못_채우면_알려_준다():
    """무거워서 FCL로 가지만 공간은 많이 남는 경우. 빈자리 값을 내는 셈이라 알려 줍니다."""

    result = sea_mode_advisor.recommend(5, 9_000)

    assert result["mode"] == "FCL" and result["fill_rate"] < 0.5
    assert any("빈자리" in note for note in result["notes"])
    # 절반 넘게 채우면 그 말은 하지 않습니다.
    assert all("빈자리" not in note for note in sea_mode_advisor.recommend(20, 8_000)["notes"])


def test_숫자가_없으면_판단하지_않는다():
    result = sea_mode_advisor.recommend(0, 0)

    assert result["mode"] == "" and result["confidence"] == "none"
    assert "치수" in result["reason"]
    assert sea_mode_advisor.summary_line(result) == ""


def test_화물_계산_창구가_권고를_함께_준다(client):
    response = client.post("/planning/api/cargo", json={
        "length_cm": 120, "width_cm": 100, "height_cm": 110, "quantity": 12,
        "weight_per_package_kg": 300, "package_type": "pallet"})

    advice = response.get_json()["data"]["sea_mode_advice"]
    assert advice["mode"] == "FCL" and advice["reason"]


def test_운송_계획_화면이_권고_자리를_둔다(client):
    html = client.get("/planning/new").get_data(as_text=True)
    assert "data-sea-advice" in html


# --- 답변 아래의 관련 링크 ---------------------------------------------------------------

@pytest.mark.parametrize("question, expect_url", [
    ("상업송장은 어떻게 쓰나요?", "/documents/new"),
    ("부산에서 LA까지 운임이 얼마쯤 하나요?", "/planning/new"),
    ("관세율은 어디서 보나요?", "/lookup/"),
    ("컨테이너가 지금 어디 있는지 보고 싶어요", "/tracking/container"),
])
def test_질문에_맞는_화면_링크를_붙인다(question, expect_url):
    urls = [row["url"] for row in answer_links.pick(question)]
    assert expect_url in urls


def test_요건_질문에는_기관_창구를_붙인다():
    rows = answer_links.pick("화장품 수출할 때 요건이 있나요?")
    urls = [row["url"] for row in rows]

    assert any(url.startswith("https://") for url in urls)
    assert all(row["kind"] in ("screen", "agency") for row in rows)


def test_원산지_질문에는_발급_창구를_붙인다():
    rows = answer_links.pick("원산지증명서는 어디서 받나요?")
    labels = " ".join(row["label"] for row in rows)

    assert "상공회의소" in labels or "관세청" in labels
    # "어디서"만 보고 컨테이너 조회를 붙이지 않습니다.
    assert all("/tracking" not in row["url"] for row in rows)


def test_HS부호_질문에는_그_품명으로_검색_창을_연다():
    rows = answer_links.pick("립스틱 HS 코드 알려줘")

    assert any(row["url"] == "#hs:립스틱" for row in rows)
    # 답이 이미 그 링크를 넣었으면 또 붙이지 않습니다.
    again = answer_links.pick("립스틱 HS 코드 알려줘", "자세한 것은 [조회](#hs:립스틱)를 보세요")
    assert all(not row["url"].startswith("#hs:") for row in again)


def test_관계없는_질문에는_붙이지_않는다():
    assert answer_links.pick("오늘 날씨 어때요?") == []


def test_링크는_최대_네_개까지():
    rows = answer_links.pick("화장품 식품 검역 원산지 서류 관세 운임 컨테이너 전략물자 위험물")
    assert len(rows) <= answer_links.MAX_LINKS


def test_상담_답변이_링크를_함께_돌려준다(app):
    """AI가 답한 건에도 우리 표에서 고른 링크가 붙습니다."""

    reply = {"success": True, "source": "api", "data": "그 건은 바이어와 먼저 정하셔야 합니다 …"}

    with patch.object(support_chat_service.ai_client, "available", return_value=True), \
         patch.object(support_chat_service.ai_client, "chat", return_value=reply):
        data = support_chat_service.ask("바이어가 서류를 다시 보내 달라는데 어떻게 하나요?")["data"]

    assert [row["url"] for row in data["links"]] == ["/documents/new"]


def test_저장해_둔_자료로_답하면_기관_링크가_앞에_온다(app):
    """바깥 창구를 먼저 보여 줍니다. 우리 화면은 왼쪽 줄에서 언제든 갈 수 있습니다.

    상담은 FAQ·지식·AI 중 어느 길로도 갈 수 있어, 길과 상관없이 지켜야 하는
    '링크 차례'만 여기서 봅니다. (어느 길로 가는지는 test_knowledge가 봅니다)
    """

    from app.services import knowledge_service

    data = knowledge_service.answer(knowledge_service.find("상업송장은 어떻게 쓰나요?"))
    data.setdefault("links", [])
    for link in answer_links.pick("상업송장은 어떻게 쓰나요?", data["answer"]):
        if link["url"] not in {row["url"] for row in data["links"]}:
            data["links"].append(link)
    data["links"].sort(key=lambda row: 0 if row["url"].startswith("http") else 1)
    urls = [row["url"] for row in data["links"]]
    outside = [url.startswith("http") for url in urls]
    assert outside and outside[0] is True
    assert sorted(outside, reverse=True) == outside, urls
    assert "/documents/new" in urls


def test_화면이_링크를_그린다():
    from pathlib import Path

    static = Path(__file__).parent.parent / "app" / "static"
    home = (static / "js/home.js").read_text(encoding="utf-8")
    support = (static / "js/support_chat.js").read_text(encoding="utf-8")
    css = (static / "css/base.css").read_text(encoding="utf-8")

    for source in (home, support):
        assert "function appendLinks" in source
        assert 'target="_blank" rel="noopener"' in source     # 바깥 주소는 새 창으로
    assert ".answer_links" in css and ".answer_link" in css
