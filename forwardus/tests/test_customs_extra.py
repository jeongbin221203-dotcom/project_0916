"""관세청 나머지 서비스 연결.

관세청 「OPEN API 연계가이드 v2.0」에 실린 실제 응답 예시를 그대로 넣어
우리 파서가 맞게 읽는지 봅니다. (관세청이 멈춰도 돌아갑니다)
"""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from app.collectors import customs_extra_client as extra


def _reply(xml: str):
    return lambda *args, **kwargs: httpx.Response(
        200, text=xml, request=httpx.Request("GET", "https://x"))


@pytest.fixture()
def keyed(app, monkeypatch):
    """모든 서비스에 키가 있는 것처럼 둡니다. 값은 쓰지 않습니다."""

    from app.collectors import base_client

    real = base_client.get_config

    def fake(name, default=None):
        if name == "UNIPASS_API_KEYS":
            return {env for env, _, _ in extra.SERVICES.values()} and {
                env: "test-key" for env, _, _ in extra.SERVICES.values()}
        return real(name, default)

    monkeypatch.setattr(extra, "get_config", fake)
    return app


def test_export_requirement_laws_reads_the_customs_answer(keyed):
    """세관장확인대상은 응답 태그가 대문자로 시작합니다. (CcctLworCdQryRsltVo)"""

    xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>
    <CcctLworCdQryRtnVo><ntceInfo/><tCnt>1</tCnt>
      <CcctLworCdQryRsltVo>
        <hsSgn>3307902000</hsSgn><reqApreIttCd>243</reqApreIttCd><aplyEndDt/>
        <dcerCfrmLworNm>화장품법</dcerCfrmLworNm>
        <reqCfrmIstmNm>표준통관예정보고서(화장품)</reqCfrmIstmNm>
        <aplyStrtDt>20140101</aplyStrtDt>
        <reqApreIttNm>한국의약품수출입협회</reqApreIttNm>
        <dcerCrmLworCd/>
      </CcctLworCdQryRsltVo></CcctLworCdQryRtnVo>"""
    with patch("httpx.request", side_effect=_reply(xml)):
        result = extra.export_requirement_laws("3307902000")

    assert result["success"] and result["source"] == "api"
    law = result["data"][0]
    assert law["law_name"] == "화장품법"
    assert law["agency"] == "한국의약품수출입협회"
    assert law["document"] == "표준통관예정보고서(화장품)"
    assert law["start_date"] == "2014-01-01"
    assert law["end_date"] == ""          # 빈 칸은 빈 채로 둡니다.


def test_clearance_code_is_read_from_the_business_number(keyed):
    xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>
    <ecmQryRtnVo><ntceInfo/>
      <ecmQryRsltVo><useYn>Y</useYn><ecm>포워더스102011</ecm><conmNm>포워더스</conmNm>
        <bsnsNo>1078800075</bsnsNo><rppnNm>이정빈</rppnNm></ecmQryRsltVo>
      <tCnt>1</tCnt></ecmQryRtnVo>"""
    with patch("httpx.request", side_effect=_reply(xml)):
        result = extra.clearance_code(business_no="107-88-00075")

    assert result["data"][0]["clearance_code"] == "포워더스102011"
    assert result["data"][0]["in_use"] is True
    # 자릿수가 안 맞으면 부르지 않고 막습니다.
    assert extra.clearance_code(business_no="123")["success"] is False


def test_refund_rate_reads_the_published_table(keyed):
    xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>
    <simlXamrttXtrnUserQryRtnVo><ntceInfo/><tCnt>1</tCnt>
      <simlXamrttXtrnUserQryRsltVo>
        <prutDrwbWncrAmt>250</prutDrwbWncrAmt><stsz>Down</stsz>
        <drwbAmtBaseTpcd>2</drwbAmtBaseTpcd><aplyDd>20260101</aplyDd>
        <ceseDt>20261231</ceseDt><hs10>0505100000</hs10>
      </simlXamrttXtrnUserQryRsltVo></simlXamrttXtrnUserQryRtnVo>"""
    with patch("httpx.request", side_effect=_reply(xml)):
        result = extra.refund_rate("0505100000")

    row = result["data"][0]
    assert row["amount_krw"] == "250"
    assert row["basis"] == "수출금액 1만원당"       # 코드 2
    assert row["start_date"] == "2026-01-01"


def test_declaration_verification_returns_match_or_not(keyed):
    def answer(code, label):
        return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>
        <expDclrCrfnVrfcQryRsltVo><ntceInfo/><tCnt>{code}</tCnt>
          <vrfcRsltCn>{label}</vrfcRsltCn></expDclrCrfnVrfcQryRsltVo>"""

    args = dict(publication_no="1234567890123", declaration_no="122100900340033",
                business_no="1078800075", origin_country="KR",
                product_name="SHAMPOO", net_weight_kg="250")

    with patch("httpx.request", side_effect=_reply(answer(1, "일치함"))):
        assert extra.verify_export_declaration(**args)["data"]["match"] is True
    with patch("httpx.request", side_effect=_reply(answer(0, "일치하지않음"))):
        result = extra.verify_export_declaration(**args)["data"]
        assert result["match"] is False and result["system_error"] is False
    with patch("httpx.request", side_effect=_reply(answer(-1, ""))):
        assert extra.verify_export_declaration(**args)["data"]["system_error"] is True

    # 사업자등록번호가 10자리가 아니면 부르지 않습니다.
    assert extra.verify_export_declaration(**{**args, "business_no": "1"})["success"] is False


def test_airlines_and_forwarders_share_the_same_shape(keyed):
    airline_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>
    <flcoLstQryRtnVo><ntceInfo/>
      <flcoLstQryRsltVo><flcoEngNm>KOREAN AIR</flcoEngNm><flcoKoreNm>대한항공</flcoKoreNm>
        <flcoSgn>KE</flcoSgn><rppnNm>조원태</rppnNm></flcoLstQryRsltVo></flcoLstQryRtnVo>"""
    forwarder_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>
    <frwrLstQryRtnVo><ntceInfo/><tCnt>1</tCnt>
      <frwrLstQryRsltVo><frwrEnglNm>KOREA MARITIME CO., LTD</frwrEnglNm>
        <frwrSgn>KMCL</frwrSgn><frwrKoreNm>한국해운(주)</frwrKoreNm>
        <rppnNm>김철수</rppnNm></frwrLstQryRsltVo></frwrLstQryRtnVo>"""

    with patch("httpx.request", side_effect=_reply(airline_xml)):
        rows = extra.search_airlines("대한항공")["data"]
        assert rows[0]["code"] == "KE" and rows[0]["korean_name"] == "대한항공"
    with patch("httpx.request", side_effect=_reply(forwarder_xml)):
        rows = extra.search_forwarders("한국")["data"]
        assert rows[0]["code"] == "KMCL" and rows[0]["korean_name"] == "한국해운(주)"


def test_missing_keys_say_so_instead_of_calling(app, monkeypatch):
    """키가 없으면 부르지 않고 키가 없다고 알려 줍니다."""

    monkeypatch.setattr(extra, "get_config",
                        lambda name, default=None: {} if name == "UNIPASS_API_KEYS" else default)
    with patch("httpx.request", side_effect=AssertionError("불러서는 안 됩니다")):
        for call in (lambda: extra.export_requirement_laws("3305100000"),
                     lambda: extra.clearance_code(business_no="1078800075"),
                     lambda: extra.refund_rate("3305100000")):
            result = call()
            assert result["success"] is False
            assert "키가 없습니다" in result["message"]


def test_every_service_has_a_key_name_and_endpoint():
    """서비스 표에 빠진 것이 없어야 합니다."""

    from config import UNIPASS_SERVICES

    for key, (env, svc, op) in extra.SERVICES.items():
        assert env in UNIPASS_SERVICES, f"{key}: 알 수 없는 키 이름 {env}"
        assert svc and op, key


def test_lookup_page_lists_every_service_and_its_key(app, client):
    """조회 화면은 무엇을 찾을 수 있고 무엇이 준비됐는지 솔직하게 보여줍니다."""

    from app.services import lookup_service

    with app.app_context():
        catalog = lookup_service.catalog()

    assert {row["key"] for row in catalog} == set(lookup_service.LOOKUPS)
    for row in catalog:
        # 관세청 서비스는 서비스마다 키가 따로이고, 공공데이터포털은 키 하나입니다.
        assert row["env"].startswith("UNIPASS_KEY_") or row["env"] == "DATA_GO_KR_SERVICE_KEY"
        assert row["about"] and row["hint"] and row["example"]

    html = client.get("/lookup/").get_data(as_text=True)
    for row in catalog:
        assert row["label"] in html


def test_lookup_refuses_unknown_kinds_and_empty_queries(app):
    from app.services import ServiceError, lookup_service

    with app.app_context():
        with pytest.raises(ServiceError):
            lookup_service.run("없는종류", "x")
        with pytest.raises(ServiceError):
            lookup_service.run("hs_code", "   ")


def test_data_source_page_counts_what_is_connected(app, client):
    """연결된 자료원 현황. 코드가 부르지 않는 서비스가 남아 있으면 드러납니다."""

    from app.services import lookup_service

    with app.app_context():
        data = lookup_service.data_sources()

    assert data["total"] == sum(len(group["rows"]) for group in data["groups"])
    assert 0 < data["ready"] <= data["total"]
    # 관세청 서비스는 모두 코드에서 부르고 있어야 합니다.
    unipass = next(group for group in data["groups"] if group["title"].startswith("관세청"))
    unused = [row["label"] for row in unipass["rows"] if not row["used"]]
    assert unused == [], f"아직 안 쓰는 관세청 서비스: {unused}"

    assert client.get("/lookup/sources").status_code == 200


def test_declaration_verification_needs_all_six_fields(app):
    from app.services import ServiceError, lookup_service

    with app.app_context():
        with pytest.raises(ServiceError) as caught:
            lookup_service.verify_declaration({"publication_no": "1"})
        assert "신고번호" in str(caught.value)


def test_trade_stats_says_what_to_apply_for_when_not_subscribed(app, monkeypatch):
    """공공데이터포털은 API마다 활용신청이 따로입니다.

    키가 있어도 신청을 안 하면 403이 옵니다. 키가 틀린 것과 다르므로
    무엇을 어디서 신청하면 되는지 알려 줘야 합니다.
    """

    from app.collectors import trade_stats_client as ts

    def not_subscribed(*args, **kwargs):
        return httpx.Response(403, text="SERVICE_KEY_IS_NOT_REGISTERED_ERROR",
                              request=httpx.Request("GET", "https://x"))

    with app.app_context():
        with patch("httpx.request", side_effect=not_subscribed):
            result = ts.item_trade("3305")
        assert result["success"] is False
        assert result["error_code"] == "API_NOT_SUBSCRIBED"
        assert "활용신청" in result["message"]
        assert ts.SIGNUP["url"].startswith("https://www.data.go.kr")


def test_trade_stats_reads_the_customs_numbers(app, monkeypatch):
    """수출 실적은 금액이 천 달러 단위로 옵니다. 그대로 읽어야 합니다."""

    from app.collectors import trade_stats_client as ts

    payload = """{"response":{"header":{"resultCode":"00"},"body":{"items":[
      {"year":"2026","statCd":"US","statKor":"미국","hsCd":"3305",
       "expDlr":"12,345","expWgt":"6,789","impDlr":"100","impWgt":"50","balPayments":"12,245"},
      {"year":"2026","statCd":"CN","statKor":"중국","hsCd":"3305",
       "expDlr":"9,000","expWgt":"4,000","impDlr":"0","impWgt":"0","balPayments":"9,000"},
      {"year":"2026","statCd":"","statKor":"총계","hsCd":"3305",
       "expDlr":"21,345","expWgt":"10,789","impDlr":"100","impWgt":"50","balPayments":"21,245"}
    ]}}}"""

    with app.app_context():
        with patch("httpx.request", side_effect=lambda *a, **k: httpx.Response(
                200, text=payload, request=httpx.Request("GET", "https://x"))):
            result = ts.top_destinations("3305")

    assert result["success"]
    rows = result["data"]["rows"]
    # 합계 줄은 표에서 빼고 따로 둡니다.
    assert [row["country"] for row in rows] == ["미국", "중국"]
    assert rows[0]["export_usd_thousand"] == 12345          # 쉼표를 떼고 읽습니다.
    assert rows[0]["export_weight_kg"] == 6789
    assert result["data"]["total"]["country"] == "총계"
    assert "천 달러" in result["data"]["unit_note"]


def test_incheon_cargo_flights_are_connected(app):
    """인천공항 화물기 정기운항은 키가 있어 지금 쓸 수 있어야 합니다."""

    from app.collectors import carrier_client

    with app.app_context():
        rows = {row["key"]: row for row in carrier_client.sources()}
    assert rows["icn_cargo"]["ready"] is True
    assert rows["icn_cargo"]["env"] == "DATA_GO_KR_SERVICE_KEY"


def test_health_check_tells_real_answers_apart_from_fallbacks(app, monkeypatch):
    """키가 있다는 것과 실제로 응답이 온다는 것은 다릅니다.

    예시 데이터로 대체된 것을 "연결됨"이라고 하면 사람이 실데이터로 믿습니다.
    """

    from app.services import lookup_service

    answers = iter([
        {"success": True, "source": "api", "data": [1, 2]},      # 진짜 응답
        {"success": True, "source": "mock", "data": [1]},        # 예시로 대체
        {"success": False, "source": "api", "data": None,
         "message": "키가 없습니다."},                             # 안 됨
    ])

    def one(*args, **kwargs):
        try:
            return next(answers)
        except StopIteration:
            return {"success": True, "source": "api", "data": []}

    monkeypatch.setattr(lookup_service, "HEALTH_CHECKS",
                        [("가짜1", "E1", one), ("가짜2", "E2", one), ("가짜3", "E3", one)])
    # 뒤에 덧붙는 검사들도 같은 답을 주게 둡니다.
    for module, name in (("customs_client", "search_hs_codes"),):
        pass

    with app.app_context():
        with patch("httpx.request", side_effect=lambda *a, **k: httpx.Response(
                200, text="<a/>", request=httpx.Request("GET", "https://x"))):
            result = lookup_service.health_check()

    states = {row["label"]: row for row in result["rows"]}
    assert states["가짜1"]["ok"] is True and states["가짜1"]["state"] == "응답함"
    assert states["가짜2"]["ok"] is False and "예시" in states["가짜2"]["state"]
    assert states["가짜3"]["ok"] is False and states["가짜3"]["state"] == "안 됨"
    assert result["live"] >= 1
    assert "예시" in result["note"]


def test_health_check_survives_a_collector_that_raises(app, monkeypatch):
    """진단 도중 하나가 터져도 나머지는 계속 봐야 합니다."""

    from app.services import lookup_service

    def boom():
        raise RuntimeError("터짐")

    monkeypatch.setattr(lookup_service, "HEALTH_CHECKS", [("터지는 것", "E", boom)])
    with app.app_context():
        with patch("httpx.request", side_effect=lambda *a, **k: httpx.Response(
                200, text="<a/>", request=httpx.Request("GET", "https://x"))):
            result = lookup_service.health_check()

    row = next(r for r in result["rows"] if r["label"] == "터지는 것")
    assert row["ok"] is False and row["state"] == "터짐"
    assert "RuntimeError" in row["detail"]
    # 나머지 검사도 함께 돌았어야 합니다.
    assert len(result["rows"]) > 1
