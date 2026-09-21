"""도착국 관세율 자료(WITS·미국 HTS·영국·일본)를 읽는 부분을 확인합니다.

실제 응답 형식을 그대로 줄인 조각으로 시험해 네트워크 없이 돕니다.
"""

from __future__ import annotations

from app.collectors import tariff_client
from app.services import planning_service

WITS_XML = """<?xml version="1.0"?>
<message:GenericData xmlns:generic="g">
<generic:Series>
<generic:Obs>
 <generic:ObsDimension value="2021"/><generic:ObsValue value="4.5"/>
 <generic:Attributes><generic:Value id="TARIFFTYPE" value="MFN"/><generic:Value id="MIN_RATE" value="0"/>
 <generic:Value id="MAX_RATE" value="6.5"/><generic:Value id="TOTALNOOFLINES" value="2"/></generic:Attributes>
</generic:Obs>
<generic:Obs>
 <generic:ObsDimension value="2023"/><generic:ObsValue value="3.25"/>
 <generic:Attributes><generic:Value id="TARIFFTYPE" value="MFN"/><generic:Value id="MIN_RATE" value="0"/>
 <generic:Value id="MAX_RATE" value="6.5"/><generic:Value id="TOTALNOOFLINES" value="2"/></generic:Attributes>
</generic:Obs>
</generic:Series></message:GenericData>"""

JAPAN_HTML = """<table id="datatable"><tbody>
<tr><th colspan="2">Statistical code</th><th rowspan="2">Description</th><th colspan="5">Tariff rate</th>
<th colspan="3">Tariff rate (EPA)</th><th colspan="2">Unit</th><th rowspan="2">Law</th></tr>
<tr><th>H.S.code</th><th>&nbsp;</th><th>General</th><th>Temporary</th><th>WTO</th><th>GSP</th><th>LDC</th>
<th>EU</th><th>China<br>(RCEP)</th><th>Korea<br>(RCEP)</th><th>I</th><th>II</th></tr>
<tr><td>33.04</td><td></td><td>Beauty or make-up preparations</td><td></td><td></td><td></td><td></td><td></td>
<td></td><td></td><td></td><td></td><td></td><td></td></tr>
<tr><td>3304.91</td><td>000</td><td>Powders</td><td>5.8%</td><td></td><td>Free</td><td>Free</td><td></td>
<td>Free</td><td>Free</td><td>Free</td><td>KG</td><td></td><td>IL</td></tr>
<tr><td>3304.99</td><td></td><td>Other</td><td>5.8%</td><td></td><td>Free</td><td>Free</td><td></td>
<td></td><td></td><td></td><td></td><td></td><td></td></tr>
<tr><td></td><td>010</td><td>- Creams</td><td></td><td></td><td></td><td></td><td></td>
<td>Free</td><td>Free</td><td>Free</td><td>KG</td><td></td><td></td></tr>
<tr><td></td><td>090</td><td>- Other</td><td></td><td></td><td></td><td></td><td></td>
<td>Free</td><td>Free</td><td>Free</td><td>KG</td><td></td><td></td></tr>
</tbody></table>"""

US_ROWS = [
    {"code": "3304", "indent": 0, "description": "Beauty preparations", "general": "", "special": "", "other": ""},
    {"code": "3304.91.00", "indent": 2, "description": "Powders", "general": "Free", "special": "", "other": ""},
    {"code": "3304.91.00.10", "indent": 3, "description": "Rouges", "general": "", "special": "", "other": ""},
    {"code": "", "indent": 2, "description": "Other:", "general": "", "special": "", "other": ""},
    {"code": "3304.99.10.00", "indent": 3, "description": "Petroleum jelly", "general": "Free", "special": "", "other": "75%"},
    {"code": "3304.99.50.00", "indent": 3, "description": "Other", "general": "2.5%",
     "special": "Free (A, AU, BH, CL, KR, SG) 1.2% (JO)", "other": "75%"},
    {"code": "3305.10.00.00", "indent": 1, "description": "Shampoos", "general": "Free", "special": "", "other": ""},
]


def test_wits_parser_keeps_latest_year():
    """여러 해가 오면 가장 최근 연도의 값만 씁니다."""

    row = tariff_client._parse_wits(WITS_XML)
    assert row == {"year": 2023, "rate": 3.25, "min": 0.0, "max": 6.5, "lines": 2, "type": "MFN"}
    assert tariff_client._parse_wits("<message:GenericData/>") is None


def test_wits_rates_are_rounded_to_two_decimals():
    """WITS는 세율을 32비트 실수로 줍니다. 1.70000004768372를 그대로 보여주면 안 됩니다."""

    xml = WITS_XML.replace('ObsValue value="3.25"', 'ObsValue value="1.70000004768372"') \
                  .replace('id="MAX_RATE" value="6.5"', 'id="MAX_RATE" value="3.90000009536743"')
    row = tariff_client._parse_wits(xml)
    assert row["rate"] == 1.7 and row["max"] == 3.9


def test_wits_reporter_uses_un_numeric_codes():
    """WITS는 ISO 문자코드가 아니라 UN 숫자코드를 받고, EU 회원국은 EU로 묶입니다."""

    assert tariff_client.reporter_for("CA") == "124"
    assert tariff_client.reporter_for("KR") == tariff_client.KOREA
    assert tariff_client.reporter_for("DE", ("DE", "FR")) == tariff_client.EU_REPORTER
    assert tariff_client.reporter_for("XX") == ""


def test_lookup_page_points_to_official_tariff_site():
    """EU 회원국은 TARIC, 미국·영국·일본은 자국 관세율표, 그 밖은 WITS 조회 페이지입니다."""

    assert "taric" in tariff_client.lookup_page("DE", "330499", ("DE",))["url"]
    assert "Taric=330499" in tariff_client.lookup_page("FR", "330499", ("FR",))["url"]
    assert "usitc" in tariff_client.lookup_page("US", "330499")["url"]
    assert "VNM" in tariff_client.lookup_page("VN", "330499")["url"]


def test_japan_table_parser_reads_codes_and_korea_rate(monkeypatch):
    """일본 관세율표 HTML에서 통계부호와 기본·WTO·한국(RCEP) 세율을 읽습니다."""

    monkeypatch.setattr(tariff_client, "japan_edition", lambda: "2026_08_08")
    tariff_client._japan_chapter.cache_clear()
    monkeypatch.setattr(tariff_client, "request_text",
                        lambda *a, **k: {"success": True, "data": JAPAN_HTML, "source": "api"})

    result = tariff_client.fetch_japan_tariff("330499")
    assert result["success"] and result["data"]["edition"] == "2026-08-08"
    codes = [row["code"] for row in result["data"]["lines"]]
    # 헤딩(33.04)과 소호(3304.99)와 그 아래 통계부호만. 3304.91은 빠집니다.
    assert codes == ["33.04", "3304.99", "3304.99-010", "3304.99-090"]
    creams = result["data"]["lines"][2]
    assert creams["korea"] == "Free" and creams["description"] == "- Creams"
    assert result["data"]["lines"][1]["general"] == "5.8%" and result["data"]["lines"][1]["wto"] == "Free"
    tariff_client._japan_chapter.cache_clear()


def test_us_lines_under_hs6_inherit_parent_rates_and_pick_korea():
    """HTS 목록에서 6자리 아래 줄만 남기고, 특별세율 난에서 KR 세율을 뽑습니다."""

    lines = planning_service._us_lines_under(US_ROWS, "330499")
    assert [line["code"] for line in lines] == ["3304.99.10.00", "3304.99.50.00"]
    assert lines[1]["general"] == "2.5%" and lines[1]["korea"] == "Free"
    assert lines[0]["korea"] == ""

    assert planning_service._us_korea_rate("1.2% (JO) Free (A, KR)", "2.5%") == "Free"
    assert planning_service._us_korea_rate("Free (A, AU, BH)", "2.5%") == ""

    # 통계용 10자리 줄은 세율이 비어 있어 8자리 줄의 값을 물려받습니다.
    inherited = planning_service._inherit_rates(planning_service._us_lines_under(US_ROWS, "330491"), ["general"])
    assert [line["general"] for line in inherited] == ["Free", "Free"]


def test_destination_tariff_combines_wits_and_national_codes(app, monkeypatch):
    """도착국별로 WITS 6단위 세율과 그 나라 세분 부호(있으면)를 함께 줍니다."""

    def fake_wits(reporter, partner, hs6):
        assert hs6 == "330499"
        if partner == tariff_client.WORLD:
            return {"success": True, "data": {"year": 2023, "rate": 3.25, "min": "0", "max": "6.5",
                                              "lines": "2", "type": "MFN"}, "source": "api"}
        return {"success": True, "data": None, "source": "api"}

    monkeypatch.setattr(tariff_client, "fetch_wits", fake_wits)
    monkeypatch.setattr(tariff_client, "fetch_us_hts",
                        lambda hs4: {"success": True, "data": US_ROWS, "source": "api"})

    us = planning_service.destination_tariff("3304.99-1000", "US")
    assert us["available"] and us["country"] == "미국" and us["hs6"] == "3304.99"
    assert us["rates"][0]["label"].startswith("MFN") and us["rates"][0]["rate"] == 3.25
    # MFN이 0%가 아닌데 특혜 자료가 없으면 그렇게 알립니다.
    assert us["rates"][1]["rate"] is None and "특혜세율이 없습니다" in us["rates"][1]["note"]
    assert us["advice"] is None          # 비교할 특혜세율이 없으면 조언하지 않습니다.
    assert us["national"]["label"].startswith("미국 HTS")
    assert [line["code"] for line in us["national"]["lines"]] == ["3304.99.10.00", "3304.99.50.00"]
    assert us["national"]["lines"][1]["korea"] == "Free"
    assert "usitc" in us["link"]["url"]

    # EU 회원국은 EU(918) 세율을 쓰고 세분 부호는 TARIC 링크로 안내합니다.
    seen = []
    monkeypatch.setattr(tariff_client, "fetch_wits",
                        lambda reporter, partner, hs6: (seen.append(reporter) or
                                                        {"success": True, "data": None, "source": "api"}))
    germany = planning_service.destination_tariff("3304991000", "DE")
    assert set(seen) == {tariff_client.EU_REPORTER}
    assert germany["in_eu"] is True and germany["national"] is None
    assert germany["link"]["label"] == "EU TARIC" and "Area=KR" in germany["link"]["url"]
    # 세율을 못 받아도 공식 관세율표 링크는 늘 안내합니다.
    assert germany["available"] is True and germany["rates"] == []

    # 부호가 6자리에 못 미치면 조회하지 않습니다.
    assert planning_service.destination_tariff("3304", "US")["available"] is False


def test_tariff_advice_tells_when_fta_is_not_worth_using():
    """FTA 특혜세율은 의무가 아닙니다. MFN보다 높으면 쓰지 말라고 알려줘야 합니다."""

    advice = planning_service._tariff_advice
    mfn = {"rate": 10.0}
    # 한ㆍ중 FTA처럼 단계적 철폐 중이라 특혜세율이 MFN보다 높은 구간이 실제로 있습니다.
    worse = advice(mfn, {"rate": 14.6}, "중국")
    assert worse["kind"] == "use_mfn" and "원산지증명서 없이" in worse["text"]

    better = advice(mfn, {"rate": 0.0}, "독일")
    assert better["kind"] == "use_fta" and "10.0%p 낮습니다" in better["text"]

    assert advice(mfn, {"rate": 10.0}, "베트남")["kind"] == "same"
    assert advice(mfn, None, "호주") is None
    assert advice(mfn, {"rate": None}, "호주") is None


def test_destination_tariff_api(client, monkeypatch):
    monkeypatch.setattr(planning_service, "destination_tariff",
                        lambda hs, country: {"available": True, "country": country, "hs6": hs[:4]})
    response = client.get("/planning/api/destination-tariff?hs=3304991000&country=VN")
    assert response.status_code == 200
    assert response.get_json()["data"] == {"available": True, "country": "VN", "hs6": "3304"}
