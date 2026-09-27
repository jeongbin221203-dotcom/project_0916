"""관세청 UNI-PASS 환율 연동 테스트. (실제 API를 호출하지 않습니다)"""

from __future__ import annotations

import pytest

from app.collectors import exchange_client

SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<trifFxrtInfoQryRtnVo><tCnt>3</tCnt>
  <trifFxrtInfoQryRsltVo><cntySgn>US</cntySgn><fxrt>1358.72</fxrt><currSgn>USD</currSgn></trifFxrtInfoQryRsltVo>
  <trifFxrtInfoQryRsltVo><cntySgn>JP</cntySgn><fxrt>8.7631</fxrt><currSgn>JPY</currSgn></trifFxrtInfoQryRsltVo>
  <trifFxrtInfoQryRsltVo><cntySgn>XX</cntySgn><fxrt>1.0</fxrt><currSgn>XXX</currSgn></trifFxrtInfoQryRsltVo>
</trifFxrtInfoQryRtnVo>"""


@pytest.fixture()
def with_key(app, monkeypatch):
    app.config["UNIPASS_API_KEYS"] = {"CUSTOMS_EXCHANGE_RATE": "test-key"}
    return app


def test_parses_customs_rates(with_key, monkeypatch):
    monkeypatch.setattr(exchange_client, "request_text",
                        lambda *args, **kwargs: {"success": True, "data": SAMPLE_XML, "source": "api"})
    result = exchange_client.fetch_krw_rates()
    assert result["source"] == "api"
    assert result["data"]["USD"] == 1358.72
    # 엔화는 100엔 단위로 고시되므로 1엔 기준으로 환산합니다.
    assert result["data"]["JPY"] == pytest.approx(0.087631)
    assert "XXX" not in result["data"]


def test_falls_back_to_mock_on_api_failure(with_key, monkeypatch):
    monkeypatch.setattr(exchange_client, "request_text",
                        lambda *args, **kwargs: {"success": False, "error_code": "API_TIMEOUT",
                                                 "message": "시간 초과", "source": "api"})
    result = exchange_client.fetch_krw_rates()
    assert result["source"] == "mock"
    assert result["data"]["USD"] > 0


def _offline(app, tmp_path):
    """바깥을 하나도 못 부르는 상태로 만듭니다.

    저장해 둔 환율도 안 보이게 빈 폴더를 가리킵니다. 그래야 "맨 마지막
    예시 환율"까지 내려가는 길을 볼 수 있습니다. (테스트가 진짜 인터넷을
    타면 그날 환율에 따라 결과가 달라집니다)
    """

    app.config["UNIPASS_API_KEYS"] = {}
    app.config["OPEN_EXCHANGE_RATES_APP_ID"] = ""
    app.config["CACHE_DIR"] = str(tmp_path)
    exchange_client.clear_cache()      # 앞 테스트가 기억해 둔 값을 쓰지 않게


def test_falls_back_without_key(app, tmp_path):
    _offline(app, tmp_path)
    result = exchange_client.fetch_krw_rates()
    assert result["source"] == "mock"


def test_고시환율을_못_받으면_시장_환율로_내려간다(app, tmp_path, monkeypatch):
    """예시 고정 환율보다 먼저, 실제 시장 환율을 씁니다."""

    _offline(app, tmp_path)
    app.config["OPEN_EXCHANGE_RATES_APP_ID"] = "test-key"
    monkeypatch.setattr(exchange_client, "request_text", lambda *a, **k: {
        "success": True, "source": "api",
        "data": '{"timestamp": 1790000000, "rates": {"KRW": 1300, "JPY": 130, "XAU": 0.0004}}'})

    result = exchange_client.fetch_krw_rates()
    assert result["source"] == "market"
    assert result["data"]["USD"] == pytest.approx(1300)      # 1달러 = 1,300원
    assert result["data"]["JPY"] == pytest.approx(10)        # 1,300 ÷ 130
    assert "XAU" not in result["data"]                       # 금은 통화가 아닙니다


def test_받아_낸_환율은_파일로_남고_다_막히면_그것을_쓴다(app, tmp_path, monkeypatch):
    """서버를 다시 켜도 예시 환율로 떨어지지 않게 합니다."""

    _offline(app, tmp_path)
    app.config["OPEN_EXCHANGE_RATES_APP_ID"] = "test-key"
    monkeypatch.setattr(exchange_client, "request_text", lambda *a, **k: {
        "success": True, "source": "api",
        "data": '{"timestamp": 1790000000, "rates": {"KRW": 1300, "EUR": 0.9}}'})
    exchange_client.fetch_krw_rates()                        # 한 번 받아서 저장

    # 이제 바깥이 통째로 막혔습니다.
    app.config["OPEN_EXCHANGE_RATES_APP_ID"] = ""
    exchange_client.clear_cache()
    result = exchange_client.fetch_krw_rates()

    assert result["source"] == "stored"
    assert result["data"]["USD"] == pytest.approx(1300)       # 예시(1,380)가 아닙니다
    assert "지난번에 받아 둔 환율" in exchange_client.rate_basis(result)


def test_저장본이_너무_오래되면_쓰지_않는다(app, tmp_path, monkeypatch):
    _offline(app, tmp_path)
    monkeypatch.setattr(exchange_client.file_cache, "read",
                        lambda name: ({"krw_per_unit": {"USD": 1300}}, 99.0))
    assert exchange_client._last_good() is None


def test_예시_환율만은_실제_값이_아니라고_말한다():
    assert exchange_client.rate_is_real({"source": "api"}) is True
    assert exchange_client.rate_is_real({"source": "market"}) is True
    assert exchange_client.rate_is_real({"source": "stored"}) is True
    assert exchange_client.rate_is_real({"source": "mock"}) is False
    assert "실제 거래에 쓰지 마세요" in exchange_client.rate_basis({"source": "mock"})


def test_missing_usd_is_an_error(with_key, monkeypatch):
    xml = SAMPLE_XML.replace("USD", "AUD")
    monkeypatch.setattr(exchange_client, "request_text",
                        lambda *args, **kwargs: {"success": True, "data": xml, "source": "api"})
    assert exchange_client.fetch_unipass_rates()["error_code"] == "API_MISSING_FIELD"


# --- 받아 온 환율 표 거르기 ----------------------------------------------------------
#
# 환율은 견적 금액에 그대로 곱해집니다. 기관이 자릿수를 하나 틀리면 견적이
# 1,000배 틀립니다. 예전에는 받아 온 표를 아무 검사 없이 썼습니다. (2026-09-26)

@pytest.mark.parametrize("rates,why", [
    ({"USD": 1.3805, "KRW": 1.0}, "달러가 1,000배 작음 (달러 기준 표를 잘못 읽은 모양)"),
    ({"USD": 1380500.0, "KRW": 1.0}, "달러가 1,000배 큼"),
    ({"USD": 0, "KRW": 1.0}, "달러가 0"),
    ({"USD": -1380.5, "KRW": 1.0}, "달러가 음수"),
    ({"USD": "1380.5", "KRW": 1.0}, "달러가 글자"),
    ({"USD": None, "KRW": 1.0}, "달러가 없음"),
    ({"USD": True, "KRW": 1.0}, "달러가 참/거짓"),
    ({}, "빈 표"),
    ({"KRW": 1.0}, "달러가 아예 빠짐"),
    (None, "표가 아님"),
])
def test_못_믿을_환율_표는_쓰지_않는다(rates, why):
    assert exchange_client.sound_rates(rates) is None, why


def test_원화는_표가_뭐라_하든_1이다():
    """KRW 가 1이 아니면 모든 환산이 그 배수만큼 틀립니다."""

    got = exchange_client.sound_rates({"USD": 1380.5, "KRW": 1000.0})
    assert got["KRW"] == 1.0


def test_이상한_통화만_버리고_나머지는_살린다():
    """표 하나가 이상하다고 멀쩡한 통화까지 버리면 견적을 못 냅니다."""

    got = exchange_client.sound_rates({
        "USD": 1380.5, "EUR": 1495.2, "VND": 0.055, "KWD": 4500.0,   # 정상
        "JPY": 0.0072,      # 1달러 기준 값이 섞여 들어옴 — 너무 작습니다
        "CNY": -190.3, "GBP": "1760", "AUD": None,
        "XAU": 3_000_000.0,   # 금 — 통화가 아닙니다 (ISO 4217 의 X 계열)
    })
    # 모르는 통화라도 모양이 맞으면 남깁니다. 버리면 관세청이 새로 실어 준
    # 진짜 통화가 조용히 사라집니다.
    assert set(got) == {"USD", "EUR", "VND", "KWD", "KRW"}


def test_못_믿을_표가_오면_다음_단계로_내려간다(app, monkeypatch):
    """틀린 숫자를 진짜처럼 보여 주느니 '예시 환율'이라고 적는 편이 낫습니다."""

    monkeypatch.setattr(exchange_client, "fetch_unipass_rates",
                        lambda *a, **k: {"success": True, "data": {"USD": 1.38},
                                         "applied_date": "2026-09-26", "source": "api"})
    monkeypatch.setattr(exchange_client, "_from_open_exchange_rates", lambda: None)
    monkeypatch.setattr(exchange_client, "_last_good", lambda: None)
    exchange_client.clear_cache()
    try:
        got = exchange_client.fetch_krw_rates()
    finally:
        exchange_client.clear_cache()
    assert got["source"] == "mock"
    assert not exchange_client.rate_is_real(got)
    assert "예시" in exchange_client.rate_basis(got)
    assert 300 <= got["data"]["USD"] <= 5000
