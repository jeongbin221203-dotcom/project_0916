"""닿지 않는 기관을 매번 다시 기다리지 않습니다.

실제로 났던 일입니다. 관세청이 회선에서 막힌 상태에서 HS 검색을 누르면
한 번에 여덟 번을 부르며 29초가 걸렸고, 화면은 20초에 끊어
"서버 응답 시간이 초과되었습니다"만 보였습니다. 아무것도 못 본 것입니다.

여기서 지키려는 것은 두 가지입니다.
  1. 한 번 닿지 않으면 그다음부터는 기다리지 않는다
  2. 그래도 **답은 나온다** (되돌아갈 길이 이미 있습니다)
"""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from app.collectors import base_client


@pytest.fixture()
def skipping(app):
    """건너뛰기를 켭니다. 평소 테스트에서는 꺼 둡니다."""

    app.config["API_OUTAGE_SECONDS"] = 60.0
    base_client.clear_outages()
    yield app
    base_client.clear_outages()


def _count_calls(error):
    """바깥을 실제로 몇 번 불렀는지 셉니다."""

    calls = []

    def answer(*args, **kwargs):
        calls.append(args)
        raise error

    return calls, answer


def test_닿지_않으면_두_번째부터는_기다리지_않는다(skipping):
    calls, answer = _count_calls(httpx.ConnectError("끊김"))

    with skipping.app_context():
        with patch("httpx.request", side_effect=answer):
            for _ in range(5):
                base_client.request_text("GET", "https://막힌곳.example/api")

    # 다섯 번 불렀지만 실제로 나간 것은 한 번뿐이어야 합니다.
    assert len(calls) == 1


def test_건너뛸_때도_이유를_말해_준다(skipping):
    """조용히 사라지면 고장과 구별이 안 됩니다."""

    _, answer = _count_calls(httpx.ReadTimeout("느림"))

    with skipping.app_context():
        with patch("httpx.request", side_effect=answer):
            base_client.request_text("GET", "https://막힌곳.example/api")
            result = base_client.request_text("GET", "https://막힌곳.example/api")

    assert result["success"] is False
    assert "막힌곳.example" in result["message"]      # 어느 기관인지
    assert "초 동안" in result["message"]             # 언제까지인지


def test_기관마다_따로_센다(skipping):
    """한 곳이 막혔다고 멀쩡한 곳까지 건너뛰면 안 됩니다."""

    calls = []

    def answer(method, url, **kwargs):
        calls.append(url)
        if "막힌곳" in url:
            raise httpx.ConnectError("끊김")
        return httpx.Response(200, text="<ok/>")

    with skipping.app_context():
        with patch("httpx.request", side_effect=answer):
            base_client.request_text("GET", "https://막힌곳.example/api")
            base_client.request_text("GET", "https://막힌곳.example/api")
            good = base_client.request_text("GET", "https://멀쩡한곳.example/api")

    assert good["success"] is True
    assert sum(1 for url in calls if "막힌곳" in url) == 1
    assert sum(1 for url in calls if "멀쩡한곳" in url) == 1


def test_응답이_온_오류는_건너뛰기로_세지_않는다(skipping):
    """404·500은 기관이 살아 있다는 뜻입니다. 막힌 것과 다릅니다."""

    calls = []

    def answer(*args, **kwargs):
        calls.append(args)
        return httpx.Response(500, text="서버 오류")

    with skipping.app_context():
        with patch("httpx.request", side_effect=answer):
            for _ in range(3):
                base_client.request_text("GET", "https://아픈곳.example/api")

    assert len(calls) == 3


def test_다시_응답하면_바로_잊는다(skipping):
    """회선이 돌아왔는데 계속 건너뛰면 그게 더 나쁩니다."""

    state = {"down": True}

    def answer(method, url, **kwargs):
        if state["down"]:
            raise httpx.ConnectError("끊김")
        return httpx.Response(200, text="<ok/>")

    with skipping.app_context():
        with patch("httpx.request", side_effect=answer):
            base_client.request_text("GET", "https://돌아온곳.example/api")
            state["down"] = False
            base_client.clear_outages()                 # 차단 시간이 지난 상황
            assert base_client.request_text("GET", "https://돌아온곳.example/api")["success"]
            # 성공했으니 기록이 지워져, 다음 호출도 그대로 나가야 합니다.
            assert base_client._skip_seconds("돌아온곳.example") == 0


def test_관세청이_막혀도_HS_검색은_답을_내놓는다(skipping):
    """건너뛰기의 목적은 빨리 포기하는 것이 아니라 빨리 답하는 것입니다."""

    from app.collectors import customs_client

    skipping.config["UNIPASS_API_KEYS"] = {"HS_CODE_SEARCH": "있는척"}

    with skipping.app_context():
        with patch("httpx.request", side_effect=httpx.ConnectError("끊김")):
            first = customs_client.search_hs_codes("샴푸")
            second = customs_client.search_hs_codes("치약")

    for result in (first, second):
        assert result["success"] is True
        assert result["source"] == "internal"       # 내부 품목표로 답했습니다
    assert any(row["code"] == "3305.10-0000" for row in first["data"])
    assert any(row["code"] == "3306.10-0000" for row in second["data"])


def test_꺼_두면_예전처럼_매번_부른다(app):
    """기본 테스트 설정입니다. 끌 수 없으면 원인을 가려낼 수 없습니다."""

    calls, answer = _count_calls(httpx.ConnectError("끊김"))

    assert app.config["API_OUTAGE_SECONDS"] == 0.0
    with app.app_context():
        with patch("httpx.request", side_effect=answer):
            for _ in range(3):
                base_client.request_text("GET", "https://막힌곳.example/api")

    assert len(calls) == 3
