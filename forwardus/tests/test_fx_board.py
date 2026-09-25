"""사이드바 [💱 환율] — 실시간 환율 시세표와 계산기가 쓰는 환율.

바깥은 부르지 않습니다. 한국수출입은행·Open Exchange Rates의 실제 응답 모양을 흉내 냅니다.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from app.collectors import exchange_client, file_cache, fx_board_client as fx


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    fx.clear_cache()
    exchange_client.clear_cache()
    store = {}
    monkeypatch.setattr(file_cache, "read", lambda name: (store[name], 0.0) if name in store else None)
    monkeypatch.setattr(file_cache, "write", lambda name, data: store.__setitem__(name, data))
    yield
    fx.clear_cache()


def _keys(monkeypatch, **values):
    real = fx.get_config
    monkeypatch.setattr(fx, "get_config", lambda name, default=None: values.get(name, real(name, default)))


def _ok(body) -> dict:
    return {"success": True, "source": "api", "data": json.dumps(body, ensure_ascii=False)}


# --- 한국수출입은행 --------------------------------------------------------------------

EXIM_TODAY = [
    {"result": 1, "cur_unit": "USD", "cur_nm": "미국 달러", "ttb": "1,366.47", "tts": "1,394.08",
     "deal_bas_r": "1,380.28", "bkpr": "1,380"},
    {"result": 1, "cur_unit": "JPY(100)", "cur_nm": "일본 옌", "ttb": "858.1", "tts": "875.44",
     "deal_bas_r": "866.77", "bkpr": "866"},
    {"result": 1, "cur_unit": "KRW", "cur_nm": "한국 원", "ttb": "0", "tts": "0", "deal_bas_r": "1"},
]
EXIM_PREV = [{"result": 1, "cur_unit": "USD", "cur_nm": "미국 달러", "ttb": "1,356", "tts": "1,384",
              "deal_bas_r": "1,370.28"}]


def test_수출입은행_고시를_읽고_주말이면_최근_영업일로_거슬러_간다(app, monkeypatch):
    _keys(monkeypatch, EXCHANGE_API_KEY="k")
    days = {"20260921": EXIM_TODAY, "20260918": EXIM_PREV}      # 월요일 · 지난 금요일
    asked = []

    def fake(method, url, **kwargs):
        day = kwargs["params"]["searchdate"]
        asked.append(day)
        return _ok(days.get(day, []))

    monkeypatch.setattr(fx, "request_text", fake)
    with app.app_context():
        result = fx.from_koreaexim(today=date(2026, 9, 22))["data"]

    assert result["as_of"] == "2026-09-21" and result["prev_date"] == "2026-09-18"
    assert result["spread"] == "bank"
    usd, jpy = result["rows"]
    assert (usd["deal"], usd["ttb"], usd["tts"]) == (1380.28, 1366.47, 1394.08)
    assert usd["change"] == 10.0 and usd["change_pct"] == 0.73
    assert (jpy["cur_unit"], jpy["unit"], jpy["name"]) == ("JPY(100)", 100, "일본 옌")
    assert jpy["change"] is None                      # 전일 고시에 없던 통화
    assert all(row["code"] != "KRW" for row in result["rows"])
    assert asked[:2] == ["20260922", "20260921"]


def test_수출입은행_인증키_오류면_실패로_보고_다음_곳으로_간다(app, monkeypatch):
    _keys(monkeypatch, EXCHANGE_API_KEY="bad")
    monkeypatch.setattr(fx, "request_text", lambda *a, **k: _ok([{"result": 3}]))
    with app.app_context():
        assert fx.from_koreaexim(today=date(2026, 9, 22))["success"] is False


# --- Open Exchange Rates --------------------------------------------------------------

OXR_LATEST = {"timestamp": 1790056800, "base": "USD",
              "rates": {"USD": 1, "KRW": 1356.7, "JPY": 157.5, "EUR": 0.872, "MXN": 17.22,
                        "XAU": 0.0004, "BTC": 0.00001}}
OXR_PREV = {"rates": {"USD": 1, "KRW": 1373.9, "JPY": 157.9, "EUR": 0.875}}
OXR_NAMES = {"MXN": "Mexican Peso", "EUR": "Euro"}


def _oxr(monkeypatch):
    calls = []

    def fake(method, url, **kwargs):
        calls.append(url)
        if "latest" in url:
            return _ok(OXR_LATEST)
        if "historical" in url:
            return _ok(OXR_PREV)
        return _ok(OXR_NAMES)

    monkeypatch.setattr(fx, "request_text", fake)
    return calls


def test_시장_환율을_원화_매매기준율로_바꾸고_전일과_견준다(app, monkeypatch):
    _keys(monkeypatch, OPEN_EXCHANGE_RATES_APP_ID="app")
    calls = _oxr(monkeypatch)
    with app.app_context():
        data = fx.from_open_exchange_rates()["data"]

    rows = {row["code"]: row for row in data["rows"]}
    assert rows["USD"]["deal"] == 1356.7
    assert rows["USD"]["change"] == pytest.approx(-17.2) and rows["USD"]["change_pct"] == -1.25
    assert rows["JPY"]["unit"] == 100 and rows["JPY"]["deal"] == pytest.approx(1356.7 / 157.5 * 100, abs=1e-3)
    assert rows["EUR"]["name"] == "유로" and rows["MXN"]["name_en"] == "Mexican Peso"
    assert rows["MXN"]["change"] is None                  # 전일 값이 없던 통화
    assert "XAU" not in rows and "BTC" not in rows        # 금·암호화폐는 통화가 아닙니다
    # 송금 환율은 주지 않는 곳입니다. 지어내지 않고 비우고, 추정이라고 밝힙니다.
    assert rows["USD"]["ttb"] is None and data["spread"] == "estimate"
    assert "추정" in data["note"]
    assert data["as_of"] == "2026-09-22 15:00" and data["prev_date"] == "2026-09-21"
    assert [row["code"] for row in data["rows"]][:3] == ["USD", "EUR", "JPY"]
    assert any("2026-09-21" in url for url in calls)


def test_시세표는_앞의_곳이_안_되면_다음_곳을_쓰고_한_시간_기억한다(app, monkeypatch):
    _keys(monkeypatch, EXCHANGE_API_KEY="", OPEN_EXCHANGE_RATES_APP_ID="app")
    calls = _oxr(monkeypatch)
    with app.app_context():
        first = fx.board()
        again = fx.board()

    assert first["data"]["source"] == "openexchangerates"
    assert "EXCHANGE_API_KEY" in first["data"]["tried"][0]
    assert first["data"]["default_spread_pct"] == 1.0
    assert again is first and len(calls) == 3           # 두 번째는 부르지 않습니다


def test_둘_다_안_되면_관세환율이나_고정_환율로_버티고_그렇다고_밝힌다(app, monkeypatch):
    _keys(monkeypatch, EXCHANGE_API_KEY="", OPEN_EXCHANGE_RATES_APP_ID="")
    monkeypatch.setattr(exchange_client, "fetch_unipass_rates",
                        lambda: {"success": False, "error_code": "API_TIMEOUT", "source": "api", "message": "x"})
    with app.app_context():
        result = fx.board()

    assert result["source"] == "mock" and result["data"]["source"] == "mock"
    assert "실제 거래에 쓰지 마세요" in result["data"]["note"]
    assert any(row["code"] == "USD" for row in result["data"]["rows"])


def test_시세표_창구(client, monkeypatch):
    _keys(monkeypatch, EXCHANGE_API_KEY="", OPEN_EXCHANGE_RATES_APP_ID="app")
    _oxr(monkeypatch)
    body = client.get("/planning/api/fx-board").get_json()
    assert body["success"] and body["data"]["rows"][0]["code"] == "USD"


# --- 화면 ------------------------------------------------------------------------

def test_사이드바는_기본_아이콘_레일이고_토글과_말풍선과_환율_센터가_있다(client):
    import re

    html = client.get("/").get_data(as_text=True)
    rail = html[html.index('class="home_rail"'):html.index('class="home_stage"')]

    # 기본은 접힘. ☰ 토글은 "사이드바 열기"로 시작합니다.
    toggle = re.search(r"<button[^>]*data-rail-toggle[^>]*>", rail, re.S).group(0)
    assert 'aria-expanded="false"' in toggle and 'data-tip="사이드바 열기"' in toggle
    # 메뉴마다 말풍선 이름이 있습니다. (접혔을 때 아이콘만 보이므로)
    for name in ("홈", "운송 예상 견적", "수출서류작성", "환율"):
        assert f'data-tip="{name}"' in rail, name
    assert "title=" not in rail           # 브라우저 기본 말풍선과 겹치지 않게
    # 펼쳐 둔 상태는 그리기 전에 붙여 번쩍임이 없게 합니다. (isSidebarExpanded)
    assert html.index("isSidebarExpanded") < html.index("<body")
    assert "data-fx-open" in html and "data-fx-modal" in html and "fx_center.js" in html
    for part in ("data-fx-search", "data-fx-from", "data-fx-to", "data-fx-swap",
                 'value="ttb"', 'value="tts"', "수출 대금을 원화로 받을 때", "외화로 송금 보낼 때"):
        assert part in html, part
    # 예전의 옆으로 펼치는 작은 계산기는 없습니다.
    assert "data-rail-fx" not in html and "fx_basis" not in html
