"""대표 항구·공항 목록 — 코드 오타를 잡고, 정렬이 실제로 좋아졌는지 봅니다."""

import pytest

from app.collectors import location_client, primary_gateways


def test_목록의_모든_코드가_위치_자료에_있다():
    known = {item["code"]: item for item in location_client._all_locations()}
    for table, kind in ((primary_gateways.PORTS, "port"), (primary_gateways.AIRPORTS, "airport")):
        for country, codes in table.items():
            for code in codes:
                assert code in known, f"{country} {code}"
                assert known[code]["kind"] == kind and known[code]["country_code"] == country, code


@pytest.mark.parametrize("country, kind, expected_first", [
    ("ZA", "port", "ZADUR"), ("KE", "port", "KEMBA"), ("NG", "port", "NGAPP"), ("CN", "port", "CNSGH"),
    ("IS", "airport", "KEF"), ("EC", "airport", "UIO"), ("VE", "airport", "CCS"), ("MV", "airport", "MLE"),
    ("PG", "airport", "POM"), ("KE", "airport", "NBO"),
])
def test_나라별_첫_후보가_대표_관문이다(country, kind, expected_first):
    rows = location_client.search_locations("", kind, country=country)["data"]
    assert rows[0]["code"] == expected_first


def test_해상_유전_터미널은_대표_항구가_아니다():
    codes = {i["code"]: i for i in location_client._all_locations()}
    assert not codes["NGABM"]["major"] and not codes["NGAKP"]["major"]


def test_한국_출발지_정렬은_그대로():
    rows = location_client.search_locations("", "port", country="KR")["data"]
    assert rows and rows[0]["code"].startswith("KR")


@pytest.mark.parametrize("code", ["SEGOT", "DKAAR", "NOOSL", "FIHEL", "COCTG", "ECGYE", "INCCU", "GHTEM", "CMDLA",
                                   "OMSLL", "IRBND", "AEDXB", "NGAPP", "VNHPH", "CNNSA", "GBLGP"])
def test_더한_세계_주요_항구가_목록과_항로에_있다(code):
    item = location_client.find_location(code)
    assert item and item["kind"] == "port" and item["lat"] is not None
    route = location_client.sea_route("KRPUS", code)
    assert route and route["distance_km"] > 500


def test_더한_항구까지_소요일이_계산된다(app):
    from app.services import planning_service
    summary = planning_service.transit_summary("KRPUS", "SEGOT")
    assert summary["sea"]["FCL"]["min"] >= 20


@pytest.mark.parametrize("real, internal", [("CNSHA", "CNSGH"), ("CNNGB", "CNNBO"), ("CNSZX", "CNSNZ"),
                                             ("CNTAO", "CNQIN"), ("CNXMN", "CNXAM")])
def test_실제_UNLOCODE로도_같은_항구를_찾는다(real, internal):
    assert location_client.find_location(real)["code"] == internal
    assert internal in [i["code"] for i in location_client.search_locations(real, "port")["data"]]
    assert location_client.sea_route("KRPUS", real) == location_client.sea_route("KRPUS", internal)


def test_원자료에_있던_항구는_더하지_않는다():
    import json
    import pathlib
    root = pathlib.Path(location_client.__file__).resolve().parents[2] / "data" / "mock"
    base = {item["code"] for item in json.loads((root / "locations.json").read_text(encoding="utf-8"))}
    extra = {item["code"] for item in json.loads((root / "locations_extra.json").read_text(encoding="utf-8"))}
    assert not (base & extra)
