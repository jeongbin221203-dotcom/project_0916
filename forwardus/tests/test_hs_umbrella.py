"""우산 HS 인식 — **호(4자리) 안에서 고르게 해 줍니다.** (2026-09-28)

무엇이 났나
  우산 오퍼시트로 HS 를 찾으니 1순위가 이랬습니다.
      3단 접이식 우산  ->  6601.10 정원용 산류 (마당 파라솔) "적합도 높음"
      장우산 자동      ->  6601.99-2000 **양산** (해가리개) "적합도 높음"
  둘 다 틀렸습니다. 정답은 6601.91-0000(절첩식)과 6601.99-9000(기타)입니다.

  **6601.91 은 후보 16개 안에 아예 없었습니다.**

왜
  후보를 소호(6자리) 형제까지만 모았습니다. 6601.99 와 6601.91 은 다른
  소호라 함께 나올 수 없었습니다. 그 사이 AI 가 낸 소재 낱말(폴리에스터·
  유리섬유)이 원료 수지 부호를 끌고 와 후보 열여섯 중 여덟을 차지했습니다.

  우산에서 소재는 **성질**이지 분류 기준이 아닙니다. 분류는 6601 호 안에서
  "대가 접히는가"로 갈립니다.
"""

from __future__ import annotations

import pytest

from app.collectors import hsk_catalog


# 우산을 부르는 말과, 그 말로 꼭 보여야 하는 세번
UMBRELLA_WORDS = [
    ("장우산", "6601"),
    ("삼단우산", "6601.91"),
    ("접이식우산", "6601.91"),
    ("자동우산", "6601"),
    ("파라솔", "6601.10"),
]


@pytest.mark.parametrize("word,want", UMBRELLA_WORDS)
def test_우산을_부르는_말로_찾힌다(word, want):
    """품목표에는 "산류(傘類)"·"절첩식"으로만 적혀 있어, 파는 이름으로는
    하나도 안 찾혔습니다. "장우산"은 0건이었습니다."""

    codes = [row["code"] for row in hsk_catalog.search(word, limit=6)]
    assert any(code.startswith(want) for code in codes), (word, codes)


def test_호_아래_세번을_통째로_내놓는다():
    """6601 호 아래 넷이 다 나와야 사람이 고를 수 있습니다.

        6601.10       정원용 산류 (마당 파라솔)
        6601.91       대가 절첩식인 것 (3단·접이식)
        6601.99-2000  양산
        6601.99-9000  기타 (장우산 따위)
    """

    codes = {row["code"] for row in hsk_catalog.children("6601", 12)}
    for want in ("6601.10-0000", "6601.91-0000", "6601.99-2000", "6601.99-9000"):
        assert want in codes, (want, sorted(codes))


def test_AI가_짚은_호의_형제를_후보에_넣는다(app):
    """AI 가 6601.99 를 짚어도 6601.91 이 함께 보여야 합니다.

    소호 형제만 보면 절첩식이 영영 안 보이고, 3단 우산에 마당용 파라솔이
    1순위로 나옵니다.
    """

    from app.services import hs_suggestion_service as service

    rows = service._heading_group({"6601999000": "AI 판단"})
    codes = {row["code"] for row in rows}
    assert "6601.91-0000" in codes, sorted(codes)
    assert "6601.10-0000" in codes, sorted(codes)


def test_품목표가_없으면_조용히_넘어간다(app, monkeypatch):
    """굳혀 둔 품목표가 없는 곳에서도 죽지 않아야 합니다."""

    from app.services import hs_suggestion_service as service

    monkeypatch.setattr(hsk_catalog, "available", lambda: False)
    assert service._heading_group({"6601999000": "AI 판단"}) == []


def test_실제_찾기_흐름에_형제가_들어간다(app, monkeypatch):
    """함수가 도는 것만으로는 모자랍니다. **search() 에 실제로 꽂혔는지**를 봅니다.

    이 테스트가 없으면 _heading_group 을 search() 에서 빼도 아무도 울지
    않습니다 — 함수는 그대로 도니까요. (2026-09-28 되돌림 검사에서 드러남)

    흉내도 실제처럼 내야 합니다. 검색어마다 같은 줄을 돌려주면 후보가 안
    차서 6601.91 이 그냥 들어갑니다. 소재 낱말이 **자리를 채우는** 상황을
    만들어야 뜻이 있습니다.

    바깥은 부르지 않습니다.
    """

    from app.collectors import customs_client, hs_ai_client
    from app.services import hs_suggestion_service as service

    # 관세청이 '우산'에 돌려주는 순서 그대로. **6601.91 은 여섯 번째입니다.**
    umbrella = [{"code": "6307.90-9000", "name": "기타"},
                {"code": "6601.10-0000", "name": "정원용 산류"},
                {"code": "6603.20-0000", "name": "산류의 틀"},
                {"code": "4404.10-0000", "name": "침엽수류"},
                {"code": "4404.20-0000", "name": "활엽수류"},
                {"code": "6601.91-0000", "name": "대가 절첩식인 것"}]
    # 소재 낱말은 원료 부호를 잔뜩 끌고 옵니다. 이것이 자리를 채웁니다.
    # **둘이 서로 다른 줄을 돌려줘야** 실제와 같습니다. 같은 줄이면 중복이
    # 걸러져 자리가 남고, 6601.91 이 그냥 들어가 버립니다.
    resin = [{"code": f"3907.{no:02d}-0000", "name": f"수지 {no}"} for no in range(10, 22)]
    glass = [{"code": f"7019.{no:02d}-0000", "name": f"유리섬유 {no}"} for no in range(11, 23)]

    def fake(term):
        if "우산" in term:
            return {"success": True, "source": "internal", "data": umbrella}
        if "폴리에스터" in term:
            return {"success": True, "source": "internal", "data": resin}
        if "유리섬유" in term:
            return {"success": True, "source": "internal", "data": glass}
        return {"success": True, "source": "internal", "data": []}

    monkeypatch.setattr(customs_client, "search_hs_codes", fake)
    # AI 는 6601.99 를 짚습니다. 소호 형제만 보면 6601.91 은 영영 안 나옵니다.
    monkeypatch.setattr(hs_ai_client, "analyze", lambda text: {
        "available": False, "message": "",
        # 실제로 AI 가 낸 가설은 **둘**이었습니다. 묶음이 늘수록 돌아가며
        # 뽑는 자리가 줄어, 뒤쪽에 있는 6601.91 이 잘립니다.
        "hypotheses": [{"code": "6601999000", "reason": "우산"},
                       {"code": "6601992000", "reason": "우산"}],
        "search_terms": ["우산", "폴리에스터", "유리섬유"]})

    found = service.search("3단 접이식 우산", order="frequency")
    codes = [row["code"] for row in found.get("data") or []]
    assert "6601.91-0000" in codes, codes
