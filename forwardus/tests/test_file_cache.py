"""받아 둔 참고자료(UN 품목분류표·WITS 세율)를 파일로 다시 쓰는지 확인합니다.

conftest가 테스트마다 빈 캐시 폴더를 주므로 실제 data/cache는 건드리지 않습니다.
"""

from __future__ import annotations

import os
import time
from unittest.mock import patch

import httpx

from app.collectors import file_cache, hs_open_client as hs, tariff_client

UN_JSON = """{"results":[
 {"id":"TOTAL","text":"TOTAL - Total"},
 {"id":"2007","text":"2007 - Jams, fruit jellies, marmalades"},
 {"id":"200799","text":"200799 - Jams: other than citrus fruit"}
]}"""

WITS_XML = """<message:GenericData xmlns:generic="g"><generic:Series><generic:Obs>
 <generic:ObsDimension value="2023"/><generic:ObsValue value="4.5"/>
 <generic:Attributes><generic:Value id="TARIFFTYPE" value="MFN"/></generic:Attributes>
</generic:Obs></generic:Series></message:GenericData>"""


def _counting(text: str, status: int = 200):
    calls = []

    def reply(method, url, **kwargs):
        calls.append(url)
        return httpx.Response(status, text=text, request=httpx.Request(method, url))
    return reply, calls


def _age(name: str, days: float) -> None:
    path = file_cache.cache_dir() / f"{name}.json"
    past = time.time() - days * 86400
    os.utime(path, (past, past))


def test_cache_round_trip_and_broken_file_is_a_miss():
    file_cache.write("demo/a", {"x": 1})
    data, age = file_cache.read("demo/a")
    assert data == {"x": 1} and age < 1
    (file_cache.cache_dir() / "demo" / "a.json").write_text("{broken", encoding="utf-8")
    assert file_cache.read("demo/a") is None
    assert file_cache.read("demo/missing") is None


def test_un_table_is_downloaded_once_and_reused_after_restart(app):
    reply, calls = _counting(UN_JSON)
    with patch("httpx.request", side_effect=reply):
        assert hs.heading_names("2007991000")["subheading"] == "Jams: other than citrus fruit"
        hs.clear_cache()                                   # 서버를 다시 켠 것과 같습니다.
        assert hs.heading_names("2007991000")["heading"] == "Jams, fruit jellies, marmalades"
    assert len(calls) == 1
    assert file_cache.read("un_hs/HS2022")[0]["edition"] == "HS2022"


def test_un_download_failure_is_not_remembered(app):
    down, down_calls = _counting("", status=503)
    with patch("httpx.request", side_effect=down):
        assert hs.heading_names("2007991000") == {"heading": "", "subheading": ""}
    assert file_cache.read("un_hs/HS2022") is None
    up, _ = _counting(UN_JSON)
    with patch("httpx.request", side_effect=up):
        assert hs.heading_names("2007991000")["heading"]


def test_stale_un_table_is_kept_when_refresh_fails(app):
    up, _ = _counting(UN_JSON)
    with patch("httpx.request", side_effect=up):
        hs.heading_names("2007991000")
    _age("un_hs/HS2022", hs.UN_REFRESH_DAYS + 1)
    hs.clear_cache()
    down, calls = _counting("", status=503)
    with patch("httpx.request", side_effect=down):
        assert hs.heading_names("2007991000")["heading"]
    assert len(calls) >= 1                                  # 새로 받아 보긴 합니다.


def test_wits_rate_is_reused_from_file(app):
    reply, calls = _counting(WITS_XML)
    with patch("httpx.request", side_effect=reply):
        first = tariff_client.fetch_wits("840", "000", "200799")
        second = tariff_client.fetch_wits("840", "000", "200799")
    assert first["data"]["rate"] == 4.5 and second == first
    assert len(calls) == 1


def test_wits_failure_is_not_stored_but_old_rate_is_used(app):
    down, _ = _counting("", status=503)
    with patch("httpx.request", side_effect=down):
        assert not tariff_client.fetch_wits("840", "000", "200799")["success"]
    assert file_cache.read("wits/840_000_200799") is None

    up, _ = _counting(WITS_XML)
    with patch("httpx.request", side_effect=up):
        tariff_client.fetch_wits("840", "000", "200799")
    _age("wits/840_000_200799", tariff_client.WITS_REFRESH_DAYS + 1)
    with patch("httpx.request", side_effect=down):
        stale = tariff_client.fetch_wits("840", "000", "200799")
    assert stale["success"] and stale["source"] == "cache" and stale["data"]["rate"] == 4.5


def test_wits_no_data_is_remembered_as_none(app):
    missing, calls = _counting("", status=404)
    with patch("httpx.request", side_effect=missing):
        assert tariff_client.fetch_wits("840", "000", "999999")["data"] is None
        assert tariff_client.fetch_wits("840", "000", "999999")["data"] is None
    assert len(calls) == 1
