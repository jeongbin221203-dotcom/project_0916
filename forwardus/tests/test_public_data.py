"""공공데이터포털에서 받아오는 자료.

관세청 무역통계와 해양수산부 항만 통계입니다. 실제 응답을 그대로 넣어
파서가 맞게 읽는지 봅니다. (기관이 멈춰도 돌아갑니다)
"""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from app.collectors import port_stats_client as ports
from app.collectors import trade_stats_client as trade


def _reply(text: str):
    return lambda *args, **kwargs: httpx.Response(
        200, text=text, request=httpx.Request("GET", "https://x"))


def test_trade_stats_are_xml_even_when_we_ask_for_json(app):
    """type=json을 줘도 XML로 옵니다. 둘 다 읽어야 합니다."""

    xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <response><header><resultCode>00</resultCode></header><body><items>
      <item><balPayments>233991198</balPayments><expDlr>478169152</expDlr>
        <expWgt>56889994</expWgt><hsCd>-</hsCd><impDlr>244177954</impDlr>
        <impWgt>27767588</impWgt><statCd>-</statCd><statCdCntnKor1>-</statCdCntnKor1>
        <statKor>-</statKor><year>총계</year></item>
      <item><balPayments>39378</balPayments><expDlr>39378</expDlr><expWgt>2551</expWgt>
        <hsCd>330510</hsCd><impDlr>0</impDlr><impWgt>0</impWgt><statCd>AE</statCd>
        <statCdCntnKor1>아랍에미리트 연합</statCdCntnKor1><statKor>샴푸</statKor>
        <year>2026.01</year></item>
      <item><balPayments>100</balPayments><expDlr>200</expDlr><expWgt>50</expWgt>
        <hsCd>330510</hsCd><impDlr>100</impDlr><impWgt>20</impWgt><statCd>AE</statCd>
        <statCdCntnKor1>아랍에미리트 연합</statCdCntnKor1><statKor>샴푸</statKor>
        <year>2026.02</year></item>
    </items></body></response>"""

    with app.app_context():
        with patch("httpx.request", side_effect=_reply(xml)):
            result = trade.top_destinations("3305")

    assert result["success"] and result["source"] == "api"
    rows = result["data"]["rows"]
    # 같은 나라가 달마다 나뉘어 오므로 더해서 한 줄로 만듭니다.
    assert len(rows) == 1
    assert rows[0]["country"] == "아랍에미리트 연합"
    assert rows[0]["export_usd_thousand"] == 39378 + 200
    assert rows[0]["months"] == 2
    # 합계 줄은 표에서 빼고 따로 둡니다.
    assert result["data"]["total"]["export_usd_thousand"] == 478169152


def test_trade_stats_query_one_year_at_a_time(app):
    """관세청 통계는 해를 걸쳐 조회하면 한 건도 나오지 않습니다."""

    asked = []

    def record(*args, **kwargs):
        asked.append(kwargs.get("params", {}))
        return httpx.Response(200, text="<response><header><resultCode>00</resultCode>"
                                        "</header><body><items/></body></response>",
                              request=httpx.Request("GET", "https://x"))

    with app.app_context():
        with patch("httpx.request", side_effect=record):
            trade.item_trade("3305")

    for params in asked:
        assert params["strtYymm"][:4] == params["endYymm"][:4], params
        assert params["strtYymm"].endswith("01") and params["endYymm"].endswith("12")
    # 올해가 비면 지난해도 찾아봅니다.
    assert len(asked) == 2


def test_not_subscribed_says_what_to_apply_for(app):
    with app.app_context():
        with patch("httpx.request", side_effect=lambda *a, **k: httpx.Response(
                403, text="SERVICE_KEY_IS_NOT_REGISTERED_ERROR",
                request=httpx.Request("GET", "https://x"))):
            for call in (lambda: trade.item_trade("3305"),
                         lambda: ports.busiest_ports()):
                result = call()
                assert result["error_code"] == "API_NOT_SUBSCRIBED"
                assert "활용신청" in result["message"]


def test_port_stats_flatten_the_nested_detail_rows(app):
    """해수부 응답은 한 줄 안에 <details><detail>이 또 들어 있습니다."""

    xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <response><header><resultCode>00</resultCode></header><body><items>
      <item><useYm>202601</useYm><prtAgNm>부산</prtAgNm><details>
        <detail><nm>외항-입항</nm><intrvsslFcontnTeu>100.5</intrvsslFcontnTeu>
          <intrvsslEcontnTeu>10</intrvsslEcontnTeu><fnshpFcontnTeu>900</fnshpFcontnTeu>
          <fnshpEcontnTeu>90</fnshpEcontnTeu></detail>
        <detail><nm>외항-출항</nm><intrvsslFcontnTeu>50</intrvsslFcontnTeu>
          <intrvsslEcontnTeu>5</intrvsslEcontnTeu><fnshpFcontnTeu>450</fnshpFcontnTeu>
          <fnshpEcontnTeu>45</fnshpEcontnTeu></detail>
      </details></item>
      <item><useYm>202601</useYm><prtAgNm>광양</prtAgNm><details>
        <detail><nm>외항-입항</nm><intrvsslFcontnTeu>10</intrvsslFcontnTeu>
          <intrvsslEcontnTeu>1</intrvsslEcontnTeu><fnshpFcontnTeu>90</fnshpFcontnTeu>
          <fnshpEcontnTeu>9</fnshpEcontnTeu></detail>
      </details></item>
    </items></body></response>"""

    with app.app_context():
        with patch("httpx.request", side_effect=_reply(xml)):
            result = ports.busiest_ports()

    rows = result["data"]["rows"]
    assert [row["port"] for row in rows] == ["부산", "광양"]      # 많은 순
    # 부산: (100.5+900) + (50+450) 적재 + (10+90) + (5+45) 공컨
    assert rows[0]["full_teu"] == pytest.approx(1500.5)
    assert rows[0]["empty_teu"] == pytest.approx(150.0)
    assert rows[0]["total_teu"] == pytest.approx(1650.5)
    assert "TEU" in result["data"]["note"]


def test_port_traffic_keeps_entered_and_departed_apart(app):
    xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <response><header><resultCode>00</resultCode></header><body><items>
      <item><useYm>202601</useYm><prtAgNm>경인</prtAgNm><details>
        <detail><nm>외국선</nm><etrVsslCo>7</etrVsslCo><etrGrtg>29410</etrGrtg>
          <satVsslCo>8</satVsslCo><satGrtg>34660</satGrtg></detail>
      </details></item>
    </items></body></response>"""

    with app.app_context():
        with patch("httpx.request", side_effect=_reply(xml)):
            result = ports.port_traffic()

    row = result["data"]["rows"][0]
    assert row["port"] == "경인" and row["kind"] == "외국선"
    assert row["entered_ships"] == 7 and row["departed_ships"] == 8
    assert row["entered_tonnage"] == 29410


def test_period_stops_two_months_short(app):
    """통계는 한두 달 늦게 올라옵니다. 오늘 달을 물으면 비어 있습니다."""

    from datetime import date

    start, end = ports._period(6)
    today = date.today()
    assert len(start) == 6 and len(end) == 6
    assert end < f"{today.year}{today.month:02d}"
    assert start < end


def test_error_codes_from_the_portal_are_reported(app):
    """필수 파라미터가 빠지면 99, 잘못되면 11이 옵니다. 그대로 알려 줍니다."""

    xml = ("<response><header><resultCode>99</resultCode>"
           "<resultMsg>필수 요청변수가 누락되었습니다.</resultMsg></header><body/></response>")
    with app.app_context():
        with patch("httpx.request", side_effect=_reply(xml)):
            result = ports.port_traffic()
    assert result["success"] is False
    assert "필수 요청변수" in result["message"]
