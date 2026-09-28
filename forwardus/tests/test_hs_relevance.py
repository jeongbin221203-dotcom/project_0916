"""적합도 판정 — **품명에 적힌 것을 다시 묻지 않습니다.** (2026-09-28)

무엇이 났나
    품명: Straight automatic-open umbrella
    화면: "자동 개폐 기능"을 확인하라고 세 후보 모두에 붙음

  서류에 적혀 있는 것을 다시 묻는 셈입니다. 세 후보에 다 붙으면 화면이
  노랗게 물들어 **진짜로 확인해야 할 것이 묻힙니다.**

  품명은 영어인데 확인 요청은 한국어로 옵니다. 글자만 견주면 못 걸러냅니다.
  구조·재질처럼 소호를 가르는 말만 이어 두었습니다 — 넓게 잡으면 정말
  확인해야 할 것까지 지워집니다.
"""

from __future__ import annotations

import pytest

from app.collectors.hs_ai_client import _known_already


STRAIGHT = "Straight automatic-open umbrella 23-inch ribs, polyester canopy, fiberglass ribs"
FOLDING = "3-fold manual umbrella 21-inch ribs, polyester canopy, steel shaft"


@pytest.mark.parametrize("detail", [
    "자동 개폐 기능",     # automatic-open 이 품명에 있습니다
    "폴리에스터 소재",     # polyester
    "유리섬유",          # fiberglass
])
def test_품명에_있는_것은_묻지_않는다(detail):
    assert _known_already([detail], STRAIGHT) == []


@pytest.mark.parametrize("detail", [
    "우산의 구체적인 종류",
    "원산지 증명",
    "최소 주문 수량",
    "접이 여부",          # 장우산에는 없는 말입니다 — 물어야 합니다
])
def test_품명에_없는_것은_남긴다(detail):
    assert _known_already([detail], STRAIGHT) == [detail]


def test_같은_말이라도_품목이_바뀌면_달라진다():
    """3단 수동 우산에는 "접이"·"수동"이 적혀 있고 "자동"은 없습니다."""

    assert _known_already(["접이 여부"], FOLDING) == []
    assert _known_already(["수동 여부"], FOLDING) == []
    assert _known_already(["자동 개폐 기능"], FOLDING) == ["자동 개폐 기능"]


def test_품명이_비면_아무것도_빼지_않는다():
    """견줄 것이 없으면 그대로 둡니다. 함부로 지우지 않습니다."""

    assert _known_already(["자동 개폐 기능"], "") == ["자동 개폐 기능"]


def test_꼬리말만으로는_빼지_않는다():
    """"기능"·"소재" 같은 말은 뜻을 더하지 않습니다.

    그것만 보고 빼면 "무슨 기능인지"를 통째로 지우게 됩니다.
    """

    assert _known_already(["기능"], STRAIGHT) == ["기능"]
    assert _known_already(["소재 확인"], STRAIGHT) == ["소재 확인"]


def test_실제_판정_흐름에서_빠진다(app, monkeypatch):
    """함수가 도는 것만으로는 모자랍니다. **review() 에 꽂혔는지**를 봅니다.

    이 테스트가 없으면 _known_already 를 review() 에서 빼도 아무도 울지
    않습니다. (2026-09-28 되돌림 검사에서 드러남)

    바깥은 부르지 않습니다. AI 응답을 흉내 냅니다.
    """

    from app.collectors import hs_ai_client

    monkeypatch.setattr(hs_ai_client, "_ask", lambda *args, **kwargs: {
        "success": True,
        "data": {"assessments": [
            {"code": "6601999000", "match": "medium", "reason": "우산으로 볼 수 있다.",
             # 품명에 이미 있는 것과 없는 것을 섞어 줍니다.
             "missing_details": ["자동 개폐 기능", "최소 주문 수량"]}]}})

    got = hs_ai_client.review(STRAIGHT, {"summary": ""},
                              [{"code": "6601.99-9000", "name": "기타"}])
    details = got["assessments"]["6601999000"]["missing_details"]
    assert details == ["최소 주문 수량"], details
