"""선사·항공사 실데이터 연동을 확인합니다.

바깥 응답은 실제 모양을 줄여 흉내 냅니다. (HMM 공개 명세의 예시, 관세청 응답,
인천공항 화물기 시간표) 네트워크 없이 돕니다.
"""

from __future__ import annotations

import json
from datetime import date

from app.collectors import carrier_client, schedule_client

SHIP_LIST_XML = """<?xml version="1.0" encoding="UTF-8"?>
<shipCoLstQryRtnVo><tCnt>2</tCnt>
<shipCoLstQryRsltVo><shipCoSgn>MAEU</shipCoSgn><shipCoEnglNm>MAERSK KOREA LIMITED</shipCoEnglNm>
 <shipCoKoreNm>한국머스크(주)</shipCoKoreNm><rppnNm>박재서외 1명</rppnNm></shipCoLstQryRsltVo>
<shipCoLstQryRsltVo><shipCoSgn></shipCoSgn><shipCoEnglNm>빈 줄</shipCoEnglNm></shipCoLstQryRsltVo>
</shipCoLstQryRtnVo>"""

SHIP_DETAIL_XML = """<?xml version="1.0" encoding="UTF-8"?>
<shipCoBrkdQryRtnVo><tCnt>1</tCnt><shipCoBrkdQryRsltVo>
<brno>1028126284</brno><shipAgncNm>한국머스크</shipAgncNm><rppnNm>박재서외 1명</rppnNm>
<cntyNm>덴마크</cntyNm><shipCoNat>DK</shipCoNat><rgsrNo>KM-C-0155</rgsrNo>
<rgsrDt>20230116</rgsrDt><telno>0220544610</telno>
</shipCoBrkdQryRsltVo></shipCoBrkdQryRtnVo>"""

# HMM 공개 명세(apiportal.hmm21.com)의 응답 예시를 줄인 것
HMM_JSON = json.dumps({"resultCode": "200", "resultData": [
    {"loadingPortCode": "KRPUS", "loadingTerminalName": "PUSAN NEW PORT",
     "vesselOperatorName": "YML", "departureDate": "2026-10-03T14:49:00",
     "transshipPortName": "KAOHSIUNG", "transshipPortCode": "TWKHH",
     "arrivalDate": "2026-11-30T20:40:00", "dischargePortCode": "DEHAM",
     "dischargeTerminalName": "CTB BURCHARDKAI", "totalTransitDay": 58,
     "cargoCutOffTime": "2026-09-30T20:45:00",
     "vessel": [{"vesselSequence": 1, "vesselName": "YM WELCOME", "voyageNumber": "0123W"}]},
    {"loadingPortCode": "KRPUS", "vesselOperatorName": "HMM",
     "departureDate": "2026-10-05T09:00:00", "transshipPortCode": "",
     "arrivalDate": "2026-11-10T08:00:00", "dischargePortCode": "DEHAM",
     "totalTransitDay": 36, "vessel": [{"vesselName": "HMM ALGECIRAS", "voyageNumber": "0045E"}]},
]}, ensure_ascii=False)

ICN_JSON = json.dumps({"response": {"body": {"items": {"item": [
    {"airline": "대한항공", "flightid": "KE9269", "airport": "프랑크푸르트", "airportCode": "FRA",
     "st": "2130", "firstdate": "20260301", "lastdate": "20261031", "season": "S26",
     "monday": "Y", "tuesday": "N", "wednesday": "Y", "thursday": "N",
     "friday": "Y", "saturday": "N", "sunday": "N"},
    {"airline": "아시아나", "flightid": "OZ563", "airport": "로스앤젤레스", "airportCode": "LAX",
     "st": "1010", "monday": "Y", "tuesday": "Y", "wednesday": "Y", "thursday": "Y",
     "friday": "Y", "saturday": "Y", "sunday": "Y"},
]}}}}, ensure_ascii=False)

METRICS = {"container_quantity": 2, "container_type": "40GP",
           "billable_revenue_ton": 12.5, "chargeable_weight_kg": 800.0}


def test_sources_report_which_keys_are_missing(app):
    """어떤 자료원이 살아 있는지 화면에서 솔직하게 알리려면 상태를 알아야 합니다."""

    by_key = {s["key"]: s for s in carrier_client.sources()}
    assert set(by_key) == {"unipass_carriers", "hmm", "icn_cargo"}
    # 관세청 선사 등록부 키는 이미 있습니다.
    assert by_key["unipass_carriers"]["ready"] is True
    # 키 이름만 알리고 값은 어디에도 싣지 않습니다.
    assert by_key["hmm"]["env"] == "HMM_API_KEY"
    assert by_key["icn_cargo"]["env"] == "DATA_GO_KR_SERVICE_KEY"


def test_shipping_company_lookup(app, monkeypatch):
    """관세청 등록부에서 선사 공식 부호와 상호를 읽습니다."""

    monkeypatch.setattr(carrier_client, "request_text",
                        lambda *a, **k: {"success": True, "data": SHIP_LIST_XML, "source": "api"})
    rows = carrier_client.search_shipping_companies("머스크")["data"]
    # 부호가 없는 줄은 버립니다.
    assert len(rows) == 1
    assert rows[0] == {"code": "MAEU", "english_name": "MAERSK KOREA LIMITED",
                       "korean_name": "한국머스크(주)", "representative": "박재서외 1명"}
    assert carrier_client.search_shipping_companies("")["success"] is False


def test_shipping_company_detail(app, monkeypatch):
    monkeypatch.setattr(carrier_client, "request_text",
                        lambda *a, **k: {"success": True, "data": SHIP_DETAIL_XML, "source": "api"})
    detail = carrier_client.shipping_company("maeu")["data"]
    assert detail["code"] == "MAEU" and detail["agency_name"] == "한국머스크"
    assert detail["country_code"] == "DK" and detail["registered_on"] == "2023-01-16"


def test_hmm_rows_map_to_our_schedule_shape(app, monkeypatch):
    """HMM 응답에서 환적 여부·소요일·화물 마감을 읽습니다."""

    monkeypatch.setattr(carrier_client, "get_config", lambda key, default="": "test-key"
                        if key == "HMM_API_KEY" else default)
    monkeypatch.setattr(carrier_client, "request_text",
                        lambda *a, **k: {"success": True, "data": HMM_JSON, "source": "api"})

    rows = carrier_client.fetch_hmm_schedules("KRPUS", "DEHAM", date(2026, 10, 1))["data"]
    assert rows[0]["etd"] == "2026-10-03" and rows[0]["eta"] == "2026-11-30"
    assert rows[0]["transit_days"] == 58
    # 환적항이 있으면 직항이 아닙니다.
    assert rows[0]["direct"] is False and rows[0]["transship_port"] == "KAOHSIUNG"
    assert rows[0]["vessel_or_flight"] == "YM WELCOME" and rows[0]["voyage_no"] == "0123W"
    # 슬롯 운항사가 제휴 선사면 그 이름을 그대로 씁니다. HMM으로 단정하지 않습니다.
    assert rows[0]["carrier"] == "YML"
    assert rows[0]["cargo_cutoff"] == "2026-09-30 20:45"
    assert rows[1]["direct"] is True and rows[1]["carrier"] == "HMM"

    # 항구 코드는 UN/LOCODE 다섯 자리여야 합니다.
    assert carrier_client.fetch_hmm_schedules("PUS", "DEHAM", date(2026, 10, 1))["success"] is False


def test_missing_keys_say_where_to_get_them(app):
    """키가 없을 때 "API가 없다"가 아니라 어디서 받는지 알려줍니다."""

    sea = carrier_client.fetch_hmm_schedules("KRPUS", "DEHAM", date(2026, 10, 1))
    assert sea["success"] is False and "HMM_API_KEY" in sea["message"]
    air = carrier_client.fetch_icn_cargo_flights("FRA")
    assert air["success"] is False and "DATA_GO_KR_SERVICE_KEY" in air["message"]


def test_icn_timetable_reads_operating_days(app, monkeypatch):
    """화물기 시간표의 요일 표시(Y/N)를 실제 운항 요일로 바꿉니다."""

    monkeypatch.setattr(carrier_client, "get_config", lambda key, default="": "test-key"
                        if key == "DATA_GO_KR_SERVICE_KEY" else default)
    monkeypatch.setattr(carrier_client, "request_text",
                        lambda *a, **k: {"success": True, "data": ICN_JSON, "source": "api"})

    rows = carrier_client.fetch_icn_cargo_flights("FRA")["data"]
    assert rows[0]["carrier"] == "대한항공" and rows[0]["vessel_or_flight"] == "KE9269"
    assert rows[0]["days"] == ["월", "수", "금"] and rows[0]["scheduled_time"] == "21:30"
    assert rows[0]["valid_to"] == "2026-10-31"
    assert rows[1]["days_label"] == "월·화·수·목·금·토·일"


def test_live_sea_schedules_replace_the_examples(app, monkeypatch):
    """키가 있으면 예시 대신 실제 배선을 씁니다. 운임은 그래도 추정값입니다."""

    monkeypatch.setattr(schedule_client, "_sea_schedules", lambda *a: [{
        "carrier": "HMM", "vessel_or_flight": "HMM ALGECIRAS", "etd": "2026-10-05",
        "eta": "2026-11-10", "transit_days": 36, "direct": True, "transship_port": "",
        "origin_code": "KRPUS", "destination_code": "DEHAM", "source": "api",
        "schedule_id": "HMM-1", "service": "직항", "reliability": None}])

    result = schedule_client.fetch_schedules(
        transport_mode="SEA", sea_mode="FCL", origin={"code": "KRPUS"},
        destination={"code": "DEHAM", "region": "europe"},
        departure_date=date(2026, 10, 1), metrics=METRICS)

    assert result["source"] == "api"
    item = result["data"][0]
    assert item["carrier"] == "HMM" and item["transit_days"] == 36
    # 운임은 어느 선사도 API로 주지 않으므로 추정으로 표시합니다.
    assert item["freight_source"] == "estimate" and item["freight_usd"] > 0
    assert item["freight_basis"] == "2 × 40GP"
    assert "운임은 추정" in result["note"]


def test_example_schedules_name_the_missing_key(app):
    """예시로 돌아갈 때 무엇이 없어서인지 정확히 적습니다."""

    result = schedule_client.fetch_schedules(
        transport_mode="SEA", sea_mode="FCL", origin={"code": "KRPUS"},
        destination={"code": "DEHAM", "region": "europe"},
        departure_date=date(2026, 10, 1), metrics=METRICS)
    assert result["source"] == "mock"
    assert "HMM_API_KEY" in result["note"] and "apiportal.hmm21.com" in result["note"]
    assert all(item["freight_source"] == "estimate" for item in result["data"])

    air = schedule_client.fetch_schedules(
        transport_mode="AIR", sea_mode=None, origin={"code": "ICN"},
        destination={"code": "FRA", "region": "europe"},
        departure_date=date(2026, 10, 1), metrics=METRICS)
    assert "DATA_GO_KR_SERVICE_KEY" in air["note"]


def test_air_timetable_expands_into_dated_departures(app, monkeypatch):
    """요일 시간표를 출발 희망일 이후의 실제 날짜로 펼칩니다."""

    monkeypatch.setattr(carrier_client, "get_config", lambda key, default="": "test-key"
                        if key == "DATA_GO_KR_SERVICE_KEY" else default)
    monkeypatch.setattr(carrier_client, "request_text",
                        lambda *a, **k: {"success": True, "data": ICN_JSON, "source": "api"})

    result = schedule_client.fetch_schedules(
        transport_mode="AIR", sea_mode=None, origin={"code": "ICN"},
        destination={"code": "FRA", "region": "europe", "transit_days": 3},
        departure_date=date(2026, 10, 1), metrics=METRICS)   # 2026-10-01은 목요일

    assert result["source"] == "api"
    etds = [item["etd"] for item in result["data"]]
    # 월·수·금 운항이므로 목요일 다음은 금(10/2) -> 월(10/5) -> 수(10/7) 순입니다.
    assert etds[:3] == ["2026-10-02", "2026-10-05", "2026-10-07"]
    assert result["data"][0]["carrier"] == "대한항공"
    assert result["data"][0]["eta"] == "2026-10-05"        # 출발 + 3일
    assert result["data"][0]["freight_source"] == "estimate"

    # 인천 출발이 아니면 이 시간표를 쓸 수 없습니다.
    busan = schedule_client.fetch_schedules(
        transport_mode="AIR", sea_mode=None, origin={"code": "PUS"},
        destination={"code": "FRA", "region": "europe"},
        departure_date=date(2026, 10, 1), metrics=METRICS)
    assert busan["source"] == "mock"
