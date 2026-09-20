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


def test_falls_back_without_key(app):
    app.config["UNIPASS_API_KEYS"] = {}
    result = exchange_client.fetch_krw_rates()
    assert result["source"] == "mock"


def test_missing_usd_is_an_error(with_key, monkeypatch):
    xml = SAMPLE_XML.replace("USD", "AUD")
    monkeypatch.setattr(exchange_client, "request_text",
                        lambda *args, **kwargs: {"success": True, "data": xml, "source": "api"})
    assert exchange_client.fetch_unipass_rates()["error_code"] == "API_MISSING_FIELD"
