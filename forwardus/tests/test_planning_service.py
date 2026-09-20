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


def test_cargo_hubs_listed_first(app):
    """항공화물 거점이 목록 맨 위에 옵니다."""

    items = planning_service.search_locations("", "AIR", "destination", country="US")["data"]
    assert items[0]["cargo_hub"] and items[0]["direct_from_korea"]
    ke = [item["code"] for item in items if item["korean_air_cargo"]]
    assert {"LAX", "JFK", "ORD", "SFO"} <= set(ke)   # 대한항공 화물 취항지

    flags = [item["cargo_hub"] and item["direct_from_korea"] for item in items]
    assert flags.index(False) > max(i for i, v in enumerate(flags) if v)


def test_korean_names_listed_first(app):
    """한글 표기는 가나다순으로 위에, 영문 표기는 알파벳순으로 아래에 둡니다."""

    items = planning_service.search_locations("", "SEA", "destination", country="US")["data"]
    korean = [item["name"] for item in items if item["name"] != item["name_en"]]
    english = [item["name"] for item in items if item["name"] == item["name_en"]]
    assert korean and english
    korean_idx = [i for i, item in enumerate(items) if item["name"] != item["name_en"]]
    english_idx = [i for i, item in enumerate(items) if item["name"] == item["name_en"]]
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
