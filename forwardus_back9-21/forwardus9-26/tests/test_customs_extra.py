"""관세청 나머지 서비스 연결.

관세청 「OPEN API 연계가이드 v2.0」에 실린 실제 응답 예시를 그대로 넣어
우리 파서가 맞게 읽는지 봅니다. (관세청이 멈춰도 돌아갑니다)
"""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from app.collectors import customs_extra_client as extra


@pytest.fixture(autouse=True)
def _fake_keys(app):
    """가짜 키를 넣어 둡니다.

    테스트 설정은 바깥 기관 키를 모두 비웁니다(실수로 진짜를 부르지 않게).
    그런데 이 파일은 **응답을 흉내 내서 파서를 보는** 테스트라, 키가 없으면
    수집기가 부르기도 전에 "키가 없습니다"로 멈춥니다.
    진짜 키가 아니어도 됩니다. 바깥으로는 나가지 않습니다(conftest가 막습니다).
    """

    app.config["DATA_GO_KR_SERVICE_KEY"] = "test-key"
    import config as _config

    app.config["UNIPASS_API_KEYS"] = {name: "test-key" for name in _config.UNIPASS_SERVICES}
    yield


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


def test_export_requirement_laws_reads_the_customs_answer(keyed, monkeypatch):
    """세관장확인대상은 공공데이터포털에서 옵니다. (UNI-PASS가 아니라 apis.data.go.kr)

    응답은 <items><item> 모양이고, 적용시작일은 YYYYMMDD로 옵니다.
    2026-09-24에 실제 응답으로 확인한 모양입니다.
    """

    xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <response><header><resultCode>00</resultCode><resultMsg>정상서비스.</resultMsg></header>
      <body><items><item>
        <aplyStrtDt>20140101</aplyStrtDt><bfhnAffcRtmTpcd>2</bfhnAffcRtmTpcd>
        <dcerCfrmLworCd>15</dcerCfrmLworCd><dcerCfrmLworNm>화장품법</dcerCfrmLworNm>
        <hsSgn>3307902000</hsSgn><reqApreIttCd>243</reqApreIttCd>
        <reqApreIttNm>한국의약품수출입협회</reqApreIttNm>
        <reqCfrmIstmNm>표준통관예정보고서(화장품)</reqCfrmIstmNm>
      </item></items></body></response>"""

    monkeypatch.setattr(extra, "get_config",
                        lambda name, default="": "test-key"
                        if name == "CUSTOMS_CONFIRM_API_KEY" else default)
    seen = {}

    def fake_request(method, url, **kwargs):
        seen["url"] = url
        seen["params"] = kwargs.get("params") or {}
        return {"success": True, "source": "api", "data": xml}

    monkeypatch.setattr(extra, "request_text", fake_request)
    result = extra.export_requirement_laws("3307902000")

    assert result["success"] and result["source"] == "api"
    assert seen["url"] == extra.CUSTOMS_CONFIRM_URL
    assert seen["params"]["hsSgn"] == "3307902000" and seen["params"]["imexTpcd"] == "1"
    law = result["data"][0]
    assert law["law_name"] == "화장품법"
    assert law["agency"] == "한국의약품수출입협회"
    assert law["document"] == "표준통관예정보고서(화장품)"
    assert law["start_date"] == "2014-01-01"
    assert law["timing_code"] == "2"
    assert law["end_date"] == ""


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
        # 관세청은 서비스마다 키가 따로, 공공데이터포털은 키 하나,
        # 국제 출처(UN·미국·영국)는 키가 아예 없습니다.
        assert (row["env"].startswith("UNIPASS_KEY_")
                or row["env"] == "DATA_GO_KR_SERVICE_KEY"
                or (row["env"] == "" and row["ready"] is True)), row
        assert row["about"] and row["hint"] and row["example"]

    # 키 없이 되는 조회는 늘 쓸 수 있어야 합니다. 관세청이 멈춰도 마찬가지입니다.
    no_key = [row for row in catalog if not row["env"]]
    assert no_key and all(row["ready"] for row in no_key)

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


def test_data_source_page_counts_what_is_connected(app, client, monkeypatch):
    """연결된 자료원 현황. 코드가 부르지 않는 서비스가 남아 있으면 드러납니다.

    이 화면은 실제로 기관을 두드려 보는 것이 아니라 **키가 있는지와 코드가
    부르는지**만 셉니다. 그래도 일부 수집기가 상태를 보려고 한 번 불러 보므로,
    바깥으로 나가지 않게 막아 둡니다. 세는 결과는 달라지지 않습니다.
    """

    # httpx.request 한 곳만 막습니다.
    #
    # base_client.request_text를 갈면 안 됩니다. 수집기들이 `from ... import
    # request_text`로 **각자 참조를 들고 있어** 갈아도 그대로 진짜를 부릅니다.
    # 그러면 conftest의 차단에 걸리고, base_client가 그 기관을 "불통"으로 적어
    # **다음 테스트까지 영향**을 줍니다. (실제로 뒤 테스트가 API_TIMEOUT을 받았습니다)
    monkeypatch.setattr("httpx.request",
                        lambda *a, **k: httpx.Response(
                            503, text="", request=httpx.Request("GET", "https://x")))

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

    # 검사마다 제 답을 따로 줍니다.
    #
    # 예전에는 반복자 하나를 셋이 나눠 next()로 꺼냈는데, health_check가
    # 스레드로 한꺼번에 돌리는 바람에 누가 무엇을 받을지가 그때그때 달랐습니다.
    # 그래서 이 테스트가 이따금 실패했습니다.
    def answer(result):
        return lambda *args, **kwargs: result

    real = answer({"success": True, "source": "api", "data": [1, 2]})
    mocked = answer({"success": True, "source": "mock", "data": [1]})
    broken = answer({"success": False, "source": "api", "data": None,
                     "message": "키가 없습니다."})

    monkeypatch.setattr(lookup_service, "HEALTH_CHECKS",
                        [("가짜1", "E1", real),
                         ("가짜2", "E2", mocked),
                         ("가짜3", "E3", broken)])

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
