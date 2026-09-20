"""관세청 HS부호검색 연동."""

from __future__ import annotations

import pytest

from app.collectors import customs_client

SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<hsSgnSrchRtnVo><ntceInfo></ntceInfo><tCnt>3</tCnt>
  <hsSgnSrchRsltVo><hsSgn>3304101000</hsSgn><korePrnm>립스틱</korePrnm>
    <englPrnm></englPrnm><wghtUt>KG</wghtUt><qtyUt></qtyUt><txrt>8</txrt><txtpSgn>A</txtpSgn></hsSgnSrchRsltVo>
  <hsSgnSrchRsltVo><hsSgn>3304101000</hsSgn><korePrnm>립스틱</korePrnm>
    <englPrnm></englPrnm><wghtUt>KG</wghtUt><qtyUt></qtyUt><txrt>0</txrt><txtpSgn>FAS1</txtpSgn></hsSgnSrchRsltVo>
  <hsSgnSrchRsltVo><hsSgn>3304991000</hsSgn><korePrnm>기초화장용 제품류</korePrnm>
    <englPrnm></englPrnm><wghtUt>KG</wghtUt><qtyUt></qtyUt><txrt>8</txrt><txtpSgn>A</txtpSgn></hsSgnSrchRsltVo>
</hsSgnSrchRtnVo>"""

ERROR_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<hsSgnSrchRtnVo><ntceInfo>한영구분(koenTp)은 필수입력입니다.</ntceInfo><tCnt>-1</tCnt></hsSgnSrchRtnVo>"""


@pytest.fixture
def with_key(app, monkeypatch):
    app.config["UNIPASS_API_KEYS"] = {**app.config.get("UNIPASS_API_KEYS", {}),
                                      "HS_CODE_SEARCH": "test-key"}
    return app


def _stub(monkeypatch, xml, captured=None):
    def request_text(method, url, **kwargs):
        if captured is not None:
            captured.update(kwargs.get("params") or {})
        return {"success": True, "data": xml, "source": "api"}
    monkeypatch.setattr(customs_client, "request_text", request_text)


def test_search_by_korean_name(with_key, monkeypatch):
    """한글 품명으로 찾고, 세율 종류만큼 반복되는 행은 한 번만 담습니다."""

    params = {}
    _stub(monkeypatch, SAMPLE_XML, params)
    result = customs_client.search_hs_codes("립스틱")

    assert result["source"] == "api"
    assert params["prnm"] == "립스틱" and params["koenTp"] == "1"
    # 같은 부호가 세 행으로 왔지만 두 건으로 정리됩니다.
    assert [item["code"] for item in result["data"]] == ["3304.10-1000", "3304.99-1000"]
    assert result["data"][0]["name"] == "립스틱"
    assert result["data"][0]["weight_unit"] == "KG"


def test_english_query_uses_english_mode(with_key, monkeypatch):
    """영문으로 입력하면 영문 품명으로 조회합니다."""

    params = {}
    _stub(monkeypatch, SAMPLE_XML, params)
    customs_client.search_hs_codes("lipstick")
    assert params["prnm"] == "lipstick" and params["koenTp"] == "2"


def test_ten_digit_code_queries_by_code(with_key, monkeypatch):
    """HS부호 10자리는 부호로 조회합니다. 점·하이픈은 떼어냅니다."""

    params = {}
    _stub(monkeypatch, SAMPLE_XML, params)
    customs_client.search_hs_codes("3304.10-1000")
    assert params["hsSgn"] == "3304101000" and "prnm" not in params


def test_short_code_is_not_sent(with_key, monkeypatch):
    """HS부호는 10자리 완전일치만 조회되므로 짧게 치면 보내지 않습니다."""

    called = []
    monkeypatch.setattr(customs_client, "request_text",
                        lambda *a, **k: called.append(1) or {"success": True, "data": SAMPLE_XML})
    result = customs_client.search_hs_codes("3304")
    assert result["source"] == "api" and result["data"] == []
    assert not called


def test_too_short_query_is_not_sent(with_key, monkeypatch):
    """한 글자로는 조회하지 않습니다. 응답이 지나치게 크고 쓸모도 없습니다."""

    called = []
    monkeypatch.setattr(customs_client, "request_text",
                        lambda *a, **k: called.append(1) or {"success": True, "data": SAMPLE_XML})
    assert customs_client.search_hs_codes("립")["data"] == []
    assert customs_client.search_hs_codes("co")["data"] == []
    assert not called


def test_api_error_message_is_surfaced(with_key, monkeypatch):
    """관세청이 돌려준 오류 문구를 그대로 알려줍니다."""

    _stub(monkeypatch, ERROR_XML)
    result = customs_client.search_hs_codes("립스틱")
    assert result["success"] is False
    assert "koenTp" in result["message"]


def test_without_key_uses_examples(app, monkeypatch):
    """키가 없으면 예시 목록으로 동작합니다."""

    app.config["UNIPASS_API_KEYS"] = {}
    result = customs_client.search_hs_codes("화장품")
    assert result["source"] == "mock"


def test_format_hs_code():
    """HSK 10자리를 읽기 쉽게 끊습니다."""

    assert customs_client.format_hs_code("3304991000") == "3304.99-1000"
    assert customs_client.format_hs_code("3304") == "3304"


TARIFF_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<trrtQryRtnVo><ntceInfo></ntceInfo><tCnt>4</tCnt>
  <trrtQryRsltVo><hsSgn>3304991000</hsSgn><trrtTpcd>A</trrtTpcd><trrtTpNm>기본세율</trrtTpNm>
    <trrt>8</trrt><prutXamt/><basePrc/><aplyStrtDt>20260101</aplyStrtDt><aplyEndDt>20261231</aplyEndDt></trrtQryRsltVo>
  <trrtQryRsltVo><hsSgn>3304991000</hsSgn><trrtTpcd>C</trrtTpcd><trrtTpNm>WTO협정세율</trrtTpNm>
    <trrt>6.5</trrt><prutXamt/><basePrc/><aplyStrtDt>20260101</aplyStrtDt><aplyEndDt>20261231</aplyEndDt></trrtQryRsltVo>
  <trrtQryRsltVo><hsSgn>3304991000</hsSgn><trrtTpcd>FEU1</trrtTpcd><trrtTpNm>한ㆍEU FTA협정세율(선택1)</trrtTpNm>
    <trrt>0</trrt><prutXamt/><basePrc/><aplyStrtDt>20260101</aplyStrtDt><aplyEndDt>20261231</aplyEndDt></trrtQryRsltVo>
  <trrtQryRsltVo><hsSgn>3304991000</hsSgn><trrtTpcd>FUS1</trrtTpcd><trrtTpNm>한ㆍ미 FTA 협정세율(선택1)</trrtTpNm>
    <trrt>0</trrt><prutXamt/><basePrc/><aplyStrtDt>20260101</aplyStrtDt><aplyEndDt>20261231</aplyEndDt></trrtQryRsltVo>
</trrtQryRtnVo>"""


@pytest.fixture
def with_tariff_key(app):
    app.config["UNIPASS_API_KEYS"] = {**app.config.get("UNIPASS_API_KEYS", {}),
                                      "TARIFF_RATE": "test-key"}
    return app


def test_tariff_rates_parse_lowercase_root(with_tariff_key, monkeypatch):
    """응답 루트 태그가 소문자(trrtQryRtnVo)여도 읽습니다."""

    params = {}
    _stub(monkeypatch, TARIFF_XML, params)
    result = customs_client.fetch_tariff_rates("3304.99-1000")

    assert result["success"] and params["hsSgn"] == "3304991000"
    assert [row["code"] for row in result["data"]] == ["A", "C", "FEU1", "FUS1"]
    assert result["data"][0]["rate"] == "8"


def test_tariff_requires_ten_digits(with_tariff_key):
    """HS부호가 10자리가 아니면 조회하지 않습니다."""

    result = customs_client.fetch_tariff_rates("3304")
    assert result["success"] is False and "10자리" in result["message"]
