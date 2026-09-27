"""관세청 말고 HS부호를 받아오는 곳.

UN Comtrade · 미국 USITC · 영국 Trade Tariff. 모두 무료이고 키가 없습니다.
관세청이 멈췄을 때 쓰는 자리라, 관세청 없이도 도는지가 핵심입니다.
"""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from app.collectors import hs_open_client as hs


def _reply(text: str):
    return lambda *args, **kwargs: httpx.Response(
        200, text=text, request=httpx.Request("GET", "https://x"))


UN_JSON = """{"results":[
 {"id":"TOTAL","text":"TOTAL - Total"},
 {"id":"33","text":"33 - Essential oils"},
 {"id":"3305","text":"3305 - Hair preparations"},
 {"id":"330510","text":"330510 - Hair preparations; shampoos"},
 {"id":"330610","text":"330610 - Dentifrices"}
]}"""


def test_un_gives_six_digit_codes_that_are_the_same_worldwide(app):
    hs.clear_cache()
    with app.app_context():
        with patch("httpx.request", side_effect=_reply(UN_JSON)):
            result = hs.search_un("shampoo")

    rows = result["data"]
    assert rows[0]["code"] == "330510"
    assert rows[0]["digits"] == 6 and rows[0]["level"] == "소호(Subheading)"
    # "TOTAL" 같은 숫자가 아닌 줄은 버립니다.
    assert all(row["code"].isdigit() for row in rows)


def test_un_search_by_number_narrows_from_the_top(app):
    """숫자로 찾으면 큰 갈래(류·호)부터 보여 줍니다."""

    hs.clear_cache()
    with app.app_context():
        with patch("httpx.request", side_effect=_reply(UN_JSON)):
            rows = hs.search_un("3305")["data"]

    assert [row["code"] for row in rows] == ["3305", "330510"]
    assert rows[0]["level"] == "호(Heading)"


def test_usitc_keeps_the_first_six_digits_separately(app):
    """미국은 10자리입니다. 우리와 같은 것은 앞 6자리뿐입니다."""

    payload = '[{"htsno":"3305.10.00.00","description":"Shampoos"}]'
    with app.app_context():
        with patch("httpx.request", side_effect=_reply(payload)):
            rows = hs.search_usitc("shampoo")["data"]

    assert rows[0]["code"] == "3305.10.00.00"
    assert rows[0]["hs6"] == "330510"


def test_search_merges_the_three_sources(app):
    """세 곳에서 같이 나온 부호를 먼저 보여 줍니다. 더 믿을 만합니다."""

    hs.clear_cache()

    def route(method, url, **kwargs):
        if "comtradeapi" in url:
            return httpx.Response(200, text=UN_JSON, request=httpx.Request("GET", url))
        if "usitc" in url:
            return httpx.Response(200, text='[{"htsno":"3305.10.00.00","description":"Shampoos"}]',
                                  request=httpx.Request("GET", url))
        return httpx.Response(200, text='{"data":[{"attributes":'
                                        '{"referenced_id":"3307900000","title":"dog shampoo"}}]}',
                              request=httpx.Request("GET", url))

    with app.app_context():
        with patch("httpx.request", side_effect=route):
            data = hs.search("shampoo")["data"]

    first = data["rows"][0]
    assert first["hs6"] == "330510"
    assert set(first["sources"]) == {"un", "usitc"}          # 두 곳에서 나왔습니다
    assert data["failed"] == []
    assert "6자리" in data["limit_note"]


def test_search_keeps_going_when_one_source_is_down(app):
    """한 곳이 죽어도 나머지로 답해야 합니다. 그게 이 기능의 목적입니다."""

    hs.clear_cache()

    def route(method, url, **kwargs):
        if "comtradeapi" in url:
            raise httpx.ConnectError("끊김")
        if "usitc" in url:
            return httpx.Response(200, text='[{"htsno":"3305.10.00.00","description":"Shampoos"}]',
                                  request=httpx.Request("GET", url))
        raise httpx.ReadTimeout("느림")

    with app.app_context():
        with patch("httpx.request", side_effect=route):
            result = hs.search("shampoo")

    assert result["success"]
    assert result["data"]["rows"][0]["hs6"] == "330510"
    assert {row["source"] for row in result["data"]["failed"]} == {"un", "uk"}


def test_short_queries_are_refused(app):
    with app.app_context():
        for call in (hs.search, hs.search_un, hs.search_usitc, hs.search_uk):
            assert call("s")["success"] is False


def test_planning_falls_back_to_open_sources_when_customs_is_down(app, monkeypatch):
    """관세청이 멈추면 국제 출처로 6자리라도 찾아 주고, 그렇다고 밝힙니다."""

    from app.collectors import customs_client, hs_open_client
    from app.services import planning_service

    monkeypatch.setattr(customs_client, "search_hs_codes", lambda q: {
        "success": True, "source": "mock", "data": [], "message": ""})
    monkeypatch.setattr(hs_open_client, "search", lambda q, limit=20: {
        "success": True, "source": "api", "data": {
            "query": q, "rows": [{"hs6": "330510", "names": ["Shampoos"],
                                  "sources": ["un"], "codes": ["330510"]}],
            "tried": ["un"], "failed": [], "limit_note": hs_open_client.LIMIT_NOTE,
            "sources": hs_open_client.SOURCES}})

    with app.app_context():
        result = planning_service.search_hs_codes("shampoo")

    assert result["source"] == "open"
    assert result["data"][0]["code"] == "330510"
    assert result["data"][0]["partial"] is True        # 신고에 그대로 못 씁니다
    assert "10자리" in result["partial_note"]


def test_real_customs_answers_win_over_open_sources(app, monkeypatch):
    """관세청이 실데이터를 주면 그것이 먼저입니다. 10자리가 나와야 신고가 됩니다."""

    from app.collectors import customs_client, hs_open_client
    from app.services import planning_service

    monkeypatch.setattr(customs_client, "search_hs_codes", lambda q: {
        "success": True, "source": "api",
        "data": [{"code": "3305.10-0000", "name": "샴푸"}], "message": ""})
    monkeypatch.setattr(hs_open_client, "search",
                        lambda q, limit=20: pytest.fail("관세청이 답했으면 부르면 안 됩니다"))

    with app.app_context():
        result = planning_service.search_hs_codes("샴푸")

    assert result["source"] == "api"
    assert result["data"][0]["code"] == "3305.10-0000"
