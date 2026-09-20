"""Schedule, reverse schedule, and shipment creation tests."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.processors.schedule_calculator import (
    calculate_cargo_ready_date,
    calculate_eta,
    calculate_reverse_schedule,
    check_buyer_deadline,
)
from app.services import planning_service
from app.validators import ValidationError


def test_reverse_schedule_matches_spec_example():
    plan = calculate_reverse_schedule(date(2026, 11, 20), "SEA", 14)
    assert plan["recommended_eta"] == date(2026, 11, 16)
    assert plan["recommended_etd"] == date(2026, 11, 2)
    assert plan["cargo_ready_date"] == date(2026, 10, 29)


def test_reverse_schedule_air_defaults():
    plan = calculate_reverse_schedule(date(2026, 11, 20), "AIR")
    assert plan["transit_days"] == 2
    assert plan["recommended_eta"] == date(2026, 11, 18)
    assert plan["recommended_etd"] == date(2026, 11, 16)
    assert plan["cargo_ready_date"] == date(2026, 11, 14)


def test_schedule_date_calculation():
    assert calculate_eta(date(2026, 12, 28), 14) == date(2027, 1, 11)
    assert calculate_cargo_ready_date(date(2026, 11, 2), "SEA") == date(2026, 10, 29)


def test_buyer_deadline_check():
    ok = check_buyer_deadline(date(2026, 11, 10), date(2026, 11, 20), "SEA")
    assert ok["on_time"] and ok["margin_days"] == 6
    late = check_buyer_deadline(date(2026, 11, 19), date(2026, 11, 20), "SEA")
    assert not late["on_time"] and late["margin_days"] == -3
    assert check_buyer_deadline(date(2026, 11, 19), None, "SEA") is None


def test_departure_margin_levels(app):
    """출발 희망일 여유를 구간별 소요일로 판정합니다."""

    today = date.today()

    def check(destination, departure_days, buyer_days, mode="SEA", sea_mode="FCL"):
        return planning_service.check_departure_date({
            "transport_mode": mode, "sea_mode": sea_mode, "destination_code": destination,
            "requested_departure_date": (today + timedelta(days=departure_days)).isoformat(),
            "buyer_required_date": (today + timedelta(days=buyer_days)).isoformat(),
        })

    # 같은 납기라도 먼 구간일수록 여유가 줄어듭니다.
    close = check("VNSGN", 7, 45)
    far = check("BRSSZ", 7, 45)
    assert close["transit_days"] < far["transit_days"]
    assert close["margin_days"] > far["margin_days"]
    # 실제 항로 기준 부산→호찌민 6일, 부산→산투스 29일이라 등급이 한 단계 이상 떨어집니다.
    grade = ["ok", "caution", "tight", "late"]
    assert close["level"] == "ok" and grade.index(far["level"]) > grade.index(close["level"])

    # 납기가 가까울수록 등급이 나빠집니다.
    levels = [check("USLAX", 7, days)["level"] for days in (20, 30, 40, 60)]
    assert levels[0] == "late" and levels[-1] == "ok"

    # 항공은 소요일이 짧아 같은 납기에서 여유가 더 큽니다.
    assert check("LAX", 7, 20, mode="AIR", sea_mode=None)["margin_days"] > check("USLAX", 7, 20)["margin_days"]


def test_schedule_outlook(app):
    """달력 아래에 해상·항공 소요시간과 납기 여유를 함께 보여줍니다."""

    today = date.today()

    def outlook(destination, departure_days, buyer_days=None, origin="KRPUS"):
        return planning_service.schedule_outlook({
            "origin_code": origin,
            "destination_code": destination,
            "requested_departure_date": (today + timedelta(days=departure_days)).isoformat(),
            "buyer_required_date": (today + timedelta(days=buyer_days)).isoformat() if buyer_days else "",
        })

    result = outlook("DEHAM", 7, 40)
    assert result["available"] and result["destination"] == "함부르크항"
    # 해상은 FCL·LCL을 나눠서, 항공은 한 줄로 보여줍니다.
    modes = {mode["label"]: mode for mode in result["modes"]}
    assert set(modes) == {"해상 FCL", "해상 LCL", "항공"}

    # 같은 납기에서 해상은 촉박하고 항공은 여유가 있습니다.
    assert modes["해상 FCL"]["level"] == "late"
    assert modes["항공"]["level"] == "ok"
    assert modes["항공"]["margin_worst"] > modes["해상 FCL"]["margin_worst"]
    # 보수적으로 가장 오래 걸리는 일정으로 등급을 매깁니다.
    assert modes["해상 FCL"]["margin_worst"] <= modes["해상 FCL"]["margin_best"]
    # LCL은 CFS 작업이 더해져 FCL보다 오래 걸립니다.
    assert modes["해상 LCL"]["min_days"] > modes["해상 FCL"]["min_days"]

    # 납기가 넉넉하면 모두 여유 있음입니다.
    relaxed = {m["label"]: m for m in outlook("USLAX", 7, 80)["modes"]}
    assert {m["level"] for m in relaxed.values()} == {"ok"}

    # Buyer 요청일이 없으면 소요시간만 보여줍니다.
    without_buyer = outlook("USLAX", 7)["modes"][0]
    assert without_buyer["level"] == "none" and without_buyer["margin_worst"] is None
    assert without_buyer["eta_fastest"]

    # 출발일이나 도착지가 없으면 계산하지 않습니다.
    assert planning_service.schedule_outlook({})["available"] is False


def test_transit_summary(app):
    """실제 항로 거리로 해상(FCL·LCL)과 항공 소요일을 계산합니다."""

    la = planning_service.transit_summary("KRPUS", "USLAX")
    assert la["available"] and la["destination"] == "로스앤젤레스항"
    assert la["sea"]["FCL"]["min"] < la["sea"]["FCL"]["max"]
    assert la["air"]["max"] < la["sea"]["FCL"]["min"]     # 항공이 해상보다 빠릅니다.
    # LCL은 출발지·도착지 CFS 작업만큼 더 걸립니다.
    assert la["sea"]["LCL"]["min"] > la["sea"]["FCL"]["min"]

    # 실제 항로 거리를 함께 돌려줍니다 (부산→로스앤젤레스 약 9,800km).
    assert 9_000 < la["sea_route"]["distance_km"] < 11_000
    assert la["sea_route"]["origin"] == "부산항"

    # 먼 구간일수록 소요일이 깁니다.
    saigon = planning_service.transit_summary("KRPUS", "VNSGN")
    hamburg = planning_service.transit_summary("KRPUS", "DEHAM")
    assert saigon["sea"]["FCL"]["min"] < la["sea"]["FCL"]["min"] < hamburg["sea"]["FCL"]["min"]
    # 유럽 항로는 수에즈 운하를 지납니다.
    assert "suez" in hamburg["sea_route"]["passages"]

    # 공항을 골라도 가장 가까운 항구로 바꿔 해상 일정을 함께 보여줍니다.
    air = planning_service.transit_summary("ICN", "LAX")
    assert air["available"] and air["sea_route"]["origin"] == "인천항"
    assert planning_service.transit_summary("KRPUS", "ZZZZZ")["available"] is False


def test_departure_check_without_buyer_date(app):
    """Buyer 요청일이 없으면 도착 예정일만 알려줍니다."""

    result = planning_service.check_departure_date({
        "transport_mode": "SEA", "sea_mode": "FCL", "destination_code": "USLAX",
        "requested_departure_date": (date.today() + timedelta(days=7)).isoformat(),
    })
    assert result["available"] and result["level"] == "none"
    assert result["margin_days"] is None and result["eta"]

    # 출발일이 없으면 계산하지 않습니다.
    assert planning_service.check_departure_date({})["available"] is False


def test_reverse_schedule_service_validation(app):
    with pytest.raises(ValidationError):
        planning_service.reverse_schedule({"buyer_required_date": "not-a-date"})
    with pytest.raises(ValidationError):
        planning_service.reverse_schedule({"buyer_required_date": "2026-11-20", "transit_days": "0"})


def test_location_search_filters_by_mode_and_role(app):
    ports = planning_service.search_locations("부산", "SEA", "origin")["data"]
    codes = [p["code"] for p in ports]
    assert codes[:2] == ["KRPUS", "KRBNP"]  # 주요 항만·짧은 이름 우선
    assert "KRKCN" in codes  # 감천항(부산)
    assert all(p["country_code"] == "KR" and p["kind"] == "port" for p in ports)
    airports = planning_service.search_locations("los angeles", "AIR", "destination")["data"]
    assert [a["code"] for a in airports] == ["LAX"]
    assert planning_service.search_locations("USLAX", "SEA", "origin")["data"] == []


def test_origin_lists_only_korean_trade_ports(app):
    """출발지는 「항만법」상 무역항과 소속 부두만 노출합니다."""

    from app.collectors import location_client

    all_kr_ports = {
        item["code"] for item in location_client.load_mock("locations")
        if item["country_code"] == "KR" and item["kind"] == "port"
    }
    # 무역항 31곳 + 소속 부두
    assert 30 < len(all_kr_ports) < 50
    for code in ("KRPUS", "KRINC", "KRKAN", "KRUSN", "KRPTK", "KRMAS", "KRKPO", "KRMOK",
                 "KRSEL", "KRHAS", "KRBNP", "KRTGH"):
        assert code in all_kr_ports
        assert planning_service.search_locations(code, "SEA", "origin")["data"][0]["code"] == code
    # 어항·연안항과 중복 코드는 제외합니다.
    assert not (all_kr_ports & {"KRGRP", "KRHPO", "KRJMJ", "KRHDO", "KRULL", "KRTGA", "KRKWA"})
    # 국내 항구는 전부 주요 항구로 표시합니다.
    assert all(item["major"] for item in location_client.load_mock("locations")
               if item["country_code"] == "KR" and item["kind"] == "port")


def test_origin_lists_national_ports_before_local(app):
    """국가관리 무역항이 위, 지방관리 무역항이 아래에 오도록 정렬합니다."""

    ports = planning_service.search_locations("", "SEA", "origin")["data"]
    classes = [item["port_class"] for item in ports]
    assert set(classes) == {"national", "local"}
    # 국가관리가 모두 앞쪽에 모여 있어야 합니다.
    assert classes.index("local") > max(i for i, c in enumerate(classes) if c == "national")
    assert ports[0]["code"] == "KRPUS"

    by_code = {item["code"]: item for item in ports}
    assert by_code["KRSEL"]["port_class"] == "local"
    assert by_code["KRSEL"]["note"] == "법적 무역항"
    assert by_code["KRPUS"]["note"] == ""
    # 평택·당진항은 항만법 시행령상 국가관리무역항입니다.
    assert by_code["KRPTK"]["port_class"] == "national"
    assert by_code["KRTJI"]["port_class"] == "national"


def test_origin_sorted_by_cargo_volume(app):
    """국가관리 무역항은 물동량이 많은 항만부터 보여줍니다."""

    ports = planning_service.search_locations("", "SEA", "origin")["data"]
    national = [item for item in ports if item["port_class"] == "national"]
    volumes = [item["cargo_volume_mt"] for item in national if item["cargo_volume_mt"]]
    assert volumes == sorted(volumes, reverse=True)

    codes = [item["code"] for item in national]
    assert codes[0] == "KRPUS"                       # 물동량 1위 항만
    assert set(codes[1:3]) == {"KRBNP", "KRKCN"}     # 부산항 소속 부두가 바로 뒤에
    for parent, terminal in [("KRPUS", "KRBNP"), ("KRUSN", "KRONS"), ("KRKPO", "KRSHG")]:
        assert codes.index(parent) < codes.index(terminal)
    # 물동량 수치가 없는 항만은 뒤로 보냅니다.
    assert codes.index("KRTSN") < codes.index("KRKPO")


def test_every_listed_port_is_classified(app):
    """규모 정보가 없고 주요 항구도 아닌 항구는 목록에 두지 않습니다."""

    from app.collectors import location_client

    ports = [item for item in location_client.load_mock("locations") if item["kind"] == "port"]
    assert ports
    assert all(item["harbor_size"] or item["major"] for item in ports)


def test_search_lists_only_main_ports(app):
    """검색 결과에는 주요 항구만 나오고, 나머지는 직접 입력으로 찾습니다."""

    for country in ("US", "VN", "DE"):
        items = planning_service.search_locations("", "SEA", "destination", country=country)["data"]
        assert items and all(item["major"] for item in items)

    # 목록에서 빠진 소규모 항구도 직접 입력 검색에서는 실제 코드로 찾힙니다.
    found = planning_service.search_unlocode("Hoodsport", country="US")["data"]
    assert found and found[0]["code"] == "US9WA"


def test_airports_split_by_direct_route(app):
    """도착지 공항은 국내 직항 노선 여부로 나뉩니다."""

    from app.collectors import location_client

    airports = [item for item in location_client.load_mock("locations") if item["kind"] == "airport"]
    direct = {item["code"] for item in airports if item["direct_from_korea"]}
    assert 100 < len(direct) < 400
    # 인천발 직항이 있는 노선
    assert {"LAX", "JFK", "PVG", "NRT", "SGN", "FRA", "SIN", "BKK"} <= direct
    # 국내 직항편이 없는 공항
    assert not ({"ABQ", "BRE", "DRS"} & direct)

    items = planning_service.search_locations("", "AIR", "destination", country="US")["data"]
    flags = [item["direct_from_korea"] for item in items]
    assert flags[0] is True
    # 직항 공항이 모두 앞쪽에 모여 있어야 합니다.
    assert flags.index(False) > max(i for i, v in enumerate(flags) if v)


def test_destination_countries_and_country_filter(app):
    countries = planning_service.list_countries("SEA", "destination")["data"]
    codes = {c["code"] for c in countries}
    assert len(countries) > 150
    assert "KR" not in codes
    assert {"US", "VN", "DE", "AE", "ZA", "BR", "SI"} <= codes
    # 내륙국과 남극은 해상 목적지가 될 수 없습니다.
    assert not ({"AT", "CH", "NP", "HU", "RS", "UZ", "AQ"} & codes)

    vietnam = planning_service.search_locations("", "SEA", "destination", country="VN")["data"]
    assert vietnam and all(item["country_code"] == "VN" for item in vietnam)
    assert "VNSGN" in {item["code"] for item in vietnam}


@pytest.mark.parametrize("mode", ["SEA", "AIR"])
def test_top_trade_partners_are_ranked(app, mode):
    """상위 교역국 20개국은 어떤 운송 모드에서도 목록에 있고 순위가 매겨집니다."""

    countries = planning_service.list_countries(mode, "destination")["data"]
    ranked = {c["code"]: c["trade_rank"] for c in countries if c.get("trade_rank")}
    assert set(ranked) == set(planning_service.TOP_TRADE_PARTNERS)
    assert sorted(ranked.values()) == list(range(1, len(planning_service.TOP_TRADE_PARTNERS) + 1))
    assert ranked["CN"] == 1 and ranked["US"] == 2


def test_schedules_cover_every_region(app, shipment_payload):
    """Every destination region has mock rates (Middle East, Africa, South America…)."""

    fastest = {}
    for destination in ("VNSGN", "USLAX", "DEHAM", "AEJEA", "ZADUR", "BRSSZ", "AUSYD"):
        payload = {**shipment_payload, "destination_code": destination}
        items = planning_service.search_schedules(payload)["items"]
        assert items, f"{destination} 스케줄 없음"
        fastest[destination] = min(item["transit_days"] for item in items)

    # 남미는 북미와 다른 구간으로 계산합니다.
    assert fastest["BRSSZ"] > fastest["USLAX"]
    assert fastest["VNSGN"] < fastest["USLAX"] < fastest["DEHAM"]


def test_direct_input_location_accepted(app, shipment_payload):
    """목록에 없는 실제 항구를 코드로 직접 지정할 수 있습니다."""

    payload = {
        **shipment_payload,
        "destination_code": "US2SI",  # Sinton, Texas (UN/LOCODE 등재, 목록에는 없음)
        "destination_custom": {"name": "Sinton Terminal", "country_code": "US"},
    }
    schedules = planning_service.search_schedules(payload)
    assert schedules["items"]
    payload["schedule_id"] = schedules["items"][0]["schedule_id"]
    shipment = planning_service.create_shipment(payload)
    assert shipment.destination_code == "US2SI"
    # 서류에는 UN/LOCODE 공식 명칭을 씁니다.
    assert shipment.destination_name == "Sinton"
    assert shipment.destination_country == "US"


def test_direct_input_resolves_real_unlocode(app, shipment_payload):
    """코드를 비우면 이름으로 실제 UN/LOCODE를 찾아 씁니다."""

    payload = {
        **shipment_payload,
        "destination_code": "",
        "destination_custom": {"name": "Yantian Pt", "country_code": "CN"},
    }
    schedules = planning_service.search_schedules(payload)
    assert schedules["items"]
    payload["schedule_id"] = schedules["items"][0]["schedule_id"]
    shipment = planning_service.create_shipment(payload)
    assert shipment.destination_code == "CNYTN"  # 실제 UN/LOCODE
    assert shipment.destination_country == "CN"


def test_direct_input_finds_airports_in_air_mode(app):
    """항공 모드에서는 직접 입력이 공항을 찾습니다."""

    for query, code in [("대구", "TAE"), ("TAE", "TAE"), ("Incheon", "ICN")]:
        items = planning_service.search_unlocode(query, role="origin", transport_mode="AIR")["data"]
        assert items and items[0]["code"] == code
        assert all(item["kind"] == "airport" for item in items)

    china = planning_service.search_unlocode("광저우", country="CN", transport_mode="AIR")["data"]
    assert china[0]["code"] == "CAN"
    # 해상 모드는 기존대로 UN/LOCODE 항구를 찾습니다.
    sea = planning_service.search_unlocode("구룡포", role="origin")["data"]
    assert sea[0]["code"] == "KRGRP"


def test_direct_input_airport_used_for_shipment(app, shipment_payload, cargo_input):
    """공항 이름만 입력해도 스케줄 조회·생성이 됩니다."""

    payload = {
        **shipment_payload,
        "transport_mode": "AIR", "sea_mode": None, "incoterms": "CPT",
        "origin_code": "", "origin_custom": {"name": "대구"},
        "destination_code": "", "destination_custom": {"name": "광저우", "country_code": "CN"},
    }
    schedules = planning_service.search_schedules(payload)
    assert schedules["items"][0]["origin_code"] == "TAE"
    assert schedules["items"][0]["destination_code"] == "CAN"

    payload["schedule_id"] = schedules["items"][0]["schedule_id"]
    shipment = planning_service.create_shipment(payload)
    assert (shipment.origin_code, shipment.destination_code) == ("TAE", "CAN")


@pytest.mark.parametrize("name,code", [
    ("Guryongpo", "KRGRP"),
    ("구룡포항", "KRGRP"),
    ("후포항", "KRHPO"),
])
def test_direct_input_finds_korean_ports(app, shipment_payload, name, code):
    payload = {**shipment_payload, "origin_code": "", "origin_custom": {"name": name}}
    assert planning_service.search_schedules(payload)["items"][0]["origin_code"] == code


def test_direct_input_lists_country_ports(app):
    """직접 입력에 나라 이름을 치면 그 나라 항구를 주요·기타 모두 보여줍니다."""

    for query in ("베트남", "Vietnam"):
        items = planning_service.search_unlocode(query)["data"]
        assert len(items) > 20
        assert all(item["country_code"] == "VN" for item in items)
        codes = [item["code"] for item in items]
        assert "VNSGN" in codes                      # 목록에 있는 주요 항구
        assert any(not item["major"] for item in items)  # 목록에서 빠진 항구도 포함
        # 주요 항구가 먼저 나옵니다.
        flags = [item["major"] for item in items]
        assert flags.index(False) > max(i for i, v in enumerate(flags) if v)


def test_transfer_airports_suggest_hub(app):
    """환승이 필요한 공항에는 경유 가능한 공항을 함께 안내합니다."""

    from app.collectors import location_client

    airports = [item for item in location_client.load_mock("locations") if item["kind"] == "airport"]
    direct = {item["code"] for item in airports if item["direct_from_korea"]}
    transfers = [item for item in airports if not item["direct_from_korea"] and item["transfer_via"]]
    assert len(transfers) > 500

    for item in transfers:
        for code, name in item["transfer_via"]:
            assert name
            if item.get("gateway_only"):
                continue  # 국제선이 없는 공항은 같은 나라 관문 공항을 안내합니다.
            assert code in direct, f"{item['code']} 경유지 {code}는 국내 직항이 아닙니다"

    by_code = {item["code"]: item for item in airports}
    assert by_code["MIA"]["transfer_via"]           # 마이애미는 미국 내 환승
    assert not by_code["LAX"]["transfer_via"]       # 직항 공항에는 경유 안내가 없습니다


def test_korean_air_cargo_destinations(app):
    """대한항공 화물 취항지가 확인된 목록과 일치합니다."""

    from app.collectors import location_client

    airports = {item["code"]: item for item in location_client.load_mock("locations")
                if item["kind"] == "airport"}
    ke = {code for code, item in airports.items() if item["korean_air_cargo"]}
    assert 50 <= len(ke) <= 60
    # 공식 소개 페이지와 위키백과 화물 표기 노선에서 확인한 공항
    assert {"LAX", "JFK", "ORD", "SFO", "ATL", "ANC", "AMS", "FRA", "LHR", "CDG",
            "VIE", "BRU", "ZRH", "MAD", "ZAZ", "ARN", "BUD", "OSL",
            "NRT", "KIX", "KKJ", "PVG", "CGO", "TAS", "SGN", "HAN", "DEL", "MAA"} <= ke
    # 데이터에 없거나 운항이 끝난 노선은 제외합니다.
    assert "SVO" not in ke      # 모스크바: 운항 종료
    assert "CMH" not in ke      # 콜럼버스: 실제 취항지는 Rickenbacker(LCK)
    assert "NAV" not in ke      # NAV는 터키 네브셰히르, 나보이는 NVI
    assert all(airports[code]["cargo_hub"] for code in ke)


def test_cargo_hubs_listed_first(app):
    """항공화물 거점이 목록 맨 위에 옵니다."""

    items = planning_service.search_locations("", "AIR", "destination", country="US")["data"]
    assert items[0]["cargo_hub"] and items[0]["direct_from_korea"]
    ke = [item["code"] for item in items if item["korean_air_cargo"]]
    assert {"LAX", "JFK", "ORD", "SFO"} <= set(ke)   # 대한항공 화물 취항지

    flags = [item["cargo_hub"] and item["direct_from_korea"] for item in items]
    assert flags.index(False) > max(i for i, v in enumerate(flags) if v)


def test_korean_names_listed_first(app):
    """직기항 묶음 안에서 한글 표기가 위에(가나다순), 영문 표기가 아래에(알파벳순) 옵니다."""

    items = planning_service.search_locations("", "SEA", "destination", country="US")["data"]
    # 한국 직기항 항구를 먼저 보여주고, 환적이 필요한 항구는 그 아래에 둡니다.
    groups = [item["sea_direct"] for item in items]
    assert groups == sorted(groups, key=lambda value: {True: 0, None: 1, False: 2}[value])

    direct = [item for item in items if item["sea_direct"]]
    korean = [item["name"] for item in direct if item["name"] != item["name_en"]]
    english = [item["name"] for item in direct if item["name"] == item["name_en"]]
    assert korean and english
    korean_idx = [i for i, item in enumerate(direct) if item["name"] != item["name_en"]]
    english_idx = [i for i, item in enumerate(direct) if item["name"] == item["name_en"]]
    assert max(korean_idx) < min(english_idx)
    assert korean == sorted(korean)                              # 가나다순
    assert english == sorted(english, key=str.lower)             # 알파벳순
    assert korean[0] == "뉴욕·뉴저지항"


def test_airports_keep_gateway_order_then_alphabetical(app):
    """공항은 대표 관문 순서를 지키고, 나머지는 가나다순입니다."""

    items = planning_service.search_locations("", "AIR", "destination", country="CN")["data"]
    names = [item["name"] for item in items]
    assert names[0] == "상하이 푸둥 국제공항"          # 지정 순위 1위
    # 같은 분류(화물 거점·직항 여부) 안에서는 가나다순입니다.
    for cargo in (True, False):
        for direct in (True, False):
            group = [item["name"] for item in items
                     if (item["size_rank"] or 99) > 11
                     and bool(item["cargo_hub"]) is cargo and bool(item["direct_from_korea"]) is direct]
            assert group == sorted(group)


def test_korean_airports_have_no_transfer_notice(app):
    """국내 공항은 출발지이므로 직항·환승 판정을 하지 않습니다."""

    items = planning_service.search_locations("", "AIR", "origin")["data"]
    assert items
    for item in items:
        assert item["direct_from_korea"] is None
        assert item["transfer_via"] == []
        assert not item.get("gateway_only")


def test_domestic_only_airport_suggests_gateway(app):
    """국제선이 없는 공항은 같은 나라 관문 공항을 안내합니다."""

    from app.collectors import location_client

    airports = {item["code"]: item for item in location_client.load_mock("locations")
                if item["kind"] == "airport"}
    congonhas = airports["CGH"]            # 상파울루 콩고냐스 (국내선 전용)
    assert congonhas["gateway_only"] is True
    assert congonhas["transfer_via"][0][0] == "GRU"

    # 모든 대체 공항 안내는 같은 나라 안에서 이뤄집니다.
    for item in airports.values():
        if item.get("gateway_only"):
            gateway = airports[item["transfer_via"][0][0]]
            assert gateway["country_code"] == item["country_code"]


def test_direct_input_suggestions(app):
    """직접 입력 칸에서 이름 일부만 쳐도 실제 코드 후보가 나옵니다."""

    result = planning_service.search_unlocode("신항", role="origin")
    assert result["success"]
    codes = [item["code"] for item in result["data"]]
    assert "KRBNP" in codes and "KRSHG" in codes           # 부산신항, 포항신항
    assert all(item["country_code"] == "KR" for item in result["data"])

    # 코드로도 찾습니다.
    assert planning_service.search_unlocode("KRPUS", role="origin")["data"][0]["code"] == "KRPUS"
    # 도착지는 선택한 국가로 좁힙니다.
    china = planning_service.search_unlocode("Yantian", country="CN")["data"]
    assert china and china[0]["code"] == "CNYTN"
    # 검색어가 없으면 그 나라(출발지는 국내) 항구를 훑어볼 수 있습니다.
    korean = planning_service.search_unlocode("", role="origin")["data"]
    assert korean and all(item["country_code"] == "KR" for item in korean)
    assert korean[0]["major"]  # 무역항이 먼저
    # 나라도 검색어도 없으면 결과를 내지 않습니다.
    assert planning_service.search_unlocode("")["data"] == []


def test_airports_cover_major_countries(app):
    """주요 국가의 국제공항이 모두 들어 있습니다 (OurAirports 대형공항 기준)."""

    from app.collectors import location_client

    airports = [item for item in location_client.load_mock("locations") if item["kind"] == "airport"]
    assert len(airports) > 1000
    assert len({item["country_code"] for item in airports}) > 200
    codes = {item["code"] for item in airports}
    # 한국 국제공항과 주요 화물 거점
    assert {"ICN", "GMP", "PUS", "CJU", "TAE", "CJJ", "MWX", "YNY"} <= codes
    assert "KWJ" not in codes  # 광주공항: 국제선 없는 국내선 전용
    assert {"PVG", "SHA"} <= codes  # 상하이 푸둥·훙차오
    assert {"PVG", "PEK", "CAN", "SZX", "TAO", "CGO", "HGH"} <= codes   # 중국
    assert {"LAX", "JFK", "ORD", "MIA", "ATL", "DFW", "SFO", "SEA"} <= codes  # 미국
    assert {"NRT", "KIX", "HND", "NGO", "FUK", "CTS"} <= codes          # 일본
    assert {"FRA", "MUC", "BER", "CGN", "DUS", "HAM"} <= codes          # 독일
    assert {"SGN", "HAN", "DAD", "HPH"} <= codes                        # 베트남
    assert all(item["name_en"] and item["city"] for item in airports)


def test_top_trade_partner_airports_have_korean_names(app):
    """주요 무역국 20개국 공항은 모두 한글 표기를 갖습니다."""

    from app.collectors import location_client

    airports = [item for item in location_client.load_mock("locations") if item["kind"] == "airport"]
    targets = [item for item in airports if item["country_code"] in planning_service.TOP_TRADE_PARTNERS]
    assert len(targets) > 400
    missing = [item["code"] for item in targets if item["name"] == item["name_en"]]
    assert not missing, f"한글 표기 누락: {missing[:10]}"

    by_code = {item["code"]: item["name"] for item in airports}
    # 청두는 솽류(CTU)와 톈푸(TFU)가 다른 공항입니다.
    assert by_code["CTU"] == "청두 솽류 국제공항"
    assert by_code["TFU"] == "청두 톈푸 국제공항"


# 한국 기업(중견기업 이상)의 해외 생산·판매 거점이 있는 주요 진출국
KOREAN_BUSINESS_COUNTRIES = [
    "BD", "KH", "MM", "LA", "LK", "PK", "UZ", "KZ", "MN", "NP", "AZ",
    "BR", "CL", "PE", "CO", "AR", "PA", "GT", "DO", "HN", "CR",
    "GB", "FR", "IT", "ES", "BE", "AT", "CZ", "HU", "SK", "RO", "RU", "RS", "TR",
    "SE", "CH", "IE", "PT", "BG", "HR", "GR", "NO", "FI", "DK",
    "QA", "KW", "OM", "BH", "IQ", "IR", "IL", "JO",
    "EG", "ZA", "MA", "TN", "DZ", "NG", "KE", "ET", "TZ", "UG", "GH", "NZ", "FJ",
]


def test_business_country_airports_have_korean_names(app):
    """국내 기업 진출국 공항도 모두 한글 표기를 갖습니다."""

    from app.collectors import location_client

    airports = [item for item in location_client.load_mock("locations") if item["kind"] == "airport"]
    targets = [item for item in airports if item["country_code"] in KOREAN_BUSINESS_COUNTRIES]
    assert len(targets) > 400
    missing = [item["code"] for item in targets if item["name"] == item["name_en"]]
    assert not missing, f"한글 표기 누락: {missing[:10]}"


@pytest.mark.parametrize("country,gateway", [
    ("CZ", "PRG"), ("HU", "BUD"), ("SE", "ARN"), ("KZ", "ALA"),
    ("AR", "EZE"), ("OM", "MCT"), ("NP", "KTM"), ("BR", "GRU"),
])
def test_primary_gateway_listed_first(app, country, gateway):
    """각 나라의 대표 관문 공항이 목록 맨 앞에 옵니다."""

    items = planning_service.search_locations("", "AIR", "destination", country=country)["data"]
    assert items[0]["code"] == gateway


def test_airports_sorted_by_size(app):
    """공항은 국가 안에서 규모가 큰 곳부터 보여줍니다."""

    korea = [item["code"] for item in planning_service.search_locations("", "AIR", "origin")["data"]]
    assert korea[:3] == ["ICN", "GMP", "PUS"]
    usa = [item["code"] for item in
           planning_service.search_locations("", "AIR", "destination", country="US")["data"]]
    assert usa[:2] == ["LAX", "JFK"]
    china = [item["code"] for item in
             planning_service.search_locations("", "AIR", "destination", country="CN")["data"]]
    assert china[0] == "PVG"


def test_direct_input_rejects_codes_outside_unlocode(app, shipment_payload):
    """서류에 찍히는 값이므로 실제 코드가 아니면 거절합니다."""

    payload = {**shipment_payload, "destination_code": "USZZZ",
               "destination_custom": {"name": "Fake Terminal", "country_code": "US"}}
    with pytest.raises(ValidationError) as info:
        planning_service.search_schedules(payload)
    assert "UN/LOCODE" in str(info.value)

    payload = {**shipment_payload, "destination_code": "",
               "destination_custom": {"name": "Zzz Imaginary Port", "country_code": "US"}}
    with pytest.raises(ValidationError) as info:
        planning_service.search_schedules(payload)
    assert info.value.field == "destination_name"


@pytest.mark.parametrize("custom,field", [
    ({"name": "Los Angeles", "country_code": ""}, "destination_country"),
    ({"name": "", "country_code": "US"}, "destination_name"),
    ({"name": "Bad Code", "country_code": "US"}, "destination_code"),
    ({"name": "Busan", "country_code": "KR"}, "destination_code"),
])
def test_direct_input_validation(app, shipment_payload, custom, field):
    code = "A!" if custom["name"] == "Bad Code" else ""
    payload = {**shipment_payload, "destination_code": code, "destination_custom": custom}
    with pytest.raises(ValidationError) as info:
        planning_service.search_schedules(payload)
    assert info.value.field == field


def test_unknown_code_without_direct_input_rejected(app, shipment_payload):
    with pytest.raises(ValidationError) as info:
        planning_service.search_schedules({**shipment_payload, "destination_code": "ZZZZZ"})
    assert info.value.field == "destination_code"


def test_schedules_are_mock_labeled_and_sorted(app, shipment_payload):
    by_price = planning_service.search_schedules({**shipment_payload, "sort": "price"})
    prices = [item["freight_usd"] for item in by_price["items"]]
    assert prices == sorted(prices)
    assert by_price["source"] == "mock"
    assert all(item["source"] == "mock" for item in by_price["items"])
    assert all(item["etd"] >= shipment_payload["requested_departure_date"] for item in by_price["items"])

    by_duration = planning_service.search_schedules({**shipment_payload, "sort": "duration"})
    days = [item["transit_days"] for item in by_duration["items"]]
    assert days == sorted(days)


def test_air_rejects_sea_only_incoterms(app, shipment_payload):
    payload = {**shipment_payload, "transport_mode": "AIR", "origin_code": "ICN", "destination_code": "LAX",
               "incoterms": "FOB", "schedule_id": "x"}
    with pytest.raises(ValidationError) as info:
        planning_service.create_shipment(payload)
    assert info.value.field == "incoterms"


def test_route_rejects_port_for_air(app, shipment_payload):
    with pytest.raises(ValidationError) as info:
        planning_service.search_schedules({**shipment_payload, "transport_mode": "AIR"})
    assert info.value.field == "origin_code"


def test_create_shipment(create_shipment):
    shipment = create_shipment()
    assert shipment.shipment_id == f"EXP-{date.today().year}-00001"
    assert shipment.status == "quoted"
    assert shipment.schedule_source == "mock"
    assert shipment.cargo.total_cbm == 30.0
    assert shipment.planned_eta == shipment.eta
    assert shipment.cargo_ready_date == shipment.etd - timedelta(days=4)
    assert shipment.total_cost_krw > 0
    second = create_shipment()
    assert second.shipment_id.endswith("00002")


def test_create_shipment_rejects_unknown_schedule(app, shipment_payload):
    with pytest.raises(ValidationError) as info:
        planning_service.create_shipment({**shipment_payload, "schedule_id": "FAKE-2026-01-01"})
    assert info.value.field == "schedule_id"


def test_net_weight_cannot_exceed_gross(app, shipment_payload, cargo_input):
    payload = {**shipment_payload, "cargo": {**cargo_input, "net_weight_kg": 999_999}}
    payload["schedule_id"] = planning_service.search_schedules(payload)["items"][0]["schedule_id"]
    with pytest.raises(ValidationError):
        planning_service.create_shipment(payload)


def test_required_parties_not_invented(app, shipment_payload):
    payload = {**shipment_payload, "exporter_name": ""}
    payload["schedule_id"] = planning_service.search_schedules(payload)["items"][0]["schedule_id"]
    with pytest.raises(ValidationError) as info:
        planning_service.create_shipment(payload)
    assert info.value.field == "exporter_name"


def test_air_route_status_uses_real_routes(app):
    """출발 공항에서 목적 공항까지 실제 직항편이 있는지 확인합니다."""

    # 인천에서는 두바이 직항이 있지만, 제주·김해에서는 없습니다.
    assert planning_service.air_route_status("ICN", "DXB")["direct"] is True
    jeju = planning_service.air_route_status("CJU", "DXB")
    assert jeju["direct"] is False
    assert "ICN" in jeju["korea_alternatives"]

    # 나리타는 여러 국내 공항에서 직항이 있습니다.
    assert planning_service.air_route_status("PUS", "NRT")["direct"] is True

    # 항구 코드나 없는 코드는 판정하지 않습니다.
    assert planning_service.air_route_status("ICN", "KRPUS") == {"known": False}
    assert planning_service.air_route_status("ICN", "ZZZ") == {"known": False}


def test_schedule_outlook_adds_transfer_time(app):
    """직항이 없는 출발 공항은 환승 시간을 더하고 대체 공항을 안내합니다."""

    today = date.today()

    def air(origin):
        result = planning_service.schedule_outlook({
            "origin_code": origin,
            "destination_code": "DXB",
            "requested_departure_date": (today + timedelta(days=7)).isoformat(),
            "buyer_required_date": (today + timedelta(days=40)).isoformat(),
        })
        return next(mode for mode in result["modes"] if mode["mode"] == "AIR")

    direct, transfer = air("ICN"), air("CJU")
    assert direct["direct"] is True and direct["note"] == ""
    assert transfer["direct"] is False
    assert transfer["max_days"] == direct["max_days"] + planning_service.TRANSFER_EXTRA_DAYS
    assert "ICN" in transfer["note"]


def test_search_destination_reflects_origin_airport(app):
    """도착지 직항 표시는 고른 출발 공항 기준으로 계산합니다."""

    def direct(code, origin=None):
        result = planning_service.search_locations("두바이", "AIR", "destination", None, origin)
        return next(item["direct_from_korea"] for item in result["data"] if item["code"] == code)

    assert direct("DXB", "ICN") is True
    assert direct("DXB", "CJU") is False
    # 출발지를 고르기 전에는 국내 어디서든 직항이 있으면 직항으로 봅니다.
    assert direct("DXB") is True


def test_incoterms_cover_all_2020_rules(app):
    """Incoterms 2020 11개 규칙을 모두 담고, 처음 쓰는 분을 위한 설명을 붙입니다."""

    from app.processors.cost_calculator import INCOTERMS_INFO

    codes = [term["code"] for term in INCOTERMS_INFO]
    assert codes == ["EXW", "FCA", "FAS", "FOB", "CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP"]

    # 해상·내수로 전용 조건은 네 가지입니다.
    assert [t["code"] for t in INCOTERMS_INFO if t.get("sea_only")] == ["FAS", "FOB", "CFR", "CIF"]
    # 판매자에게 보험 의무가 있는 조건은 CIF와 CIP뿐입니다.
    assert [t["code"] for t in INCOTERMS_INFO if "보험" in t["seller_cost"]] == ["CIF", "CIP"]
    # 양하 의무가 있는 조건은 DPU 하나입니다.
    assert [t["code"] for t in INCOTERMS_INFO if "양하" in t["seller_cost"]] == ["DPU"]

    for term in INCOTERMS_INFO:
        assert term["detail"] and term["caution"], term["code"]
        assert term["group"] in "EFCD"


def test_incoterms_help_is_rendered(app, client):
    """카드마다 마우스를 올렸을 때 보여줄 설명이 화면에 들어 있습니다."""

    html = client.get("/planning/new").get_data(as_text=True)
    assert html.count('class="incoterm_card"') == 11
    assert html.count("incoterm_help_") == 22            # 카드 11개 × (aria-describedby + id)
    assert "Free Alongside Ship" in html and "ICC A" in html


def test_direct_call_guide_is_shown_for_sea(app, client):
    """해상 모드에서 직기항·환적이 무엇인지 설명을 보여줍니다."""

    html = client.get("/planning/new").get_data(as_text=True)
    assert 'data-sea-only' in html
    assert "배를 갈아타지 않고 곧바로 들어가는 정기 항로" in html
    assert "다른 배로 옮겨 실어야" in html
