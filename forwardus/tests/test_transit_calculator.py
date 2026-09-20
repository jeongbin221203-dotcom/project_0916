"""실제 항로 거리로 계산한 소요일이 공표 스케줄과 맞는지 확인합니다."""

from __future__ import annotations

import pytest

from app.collectors import location_client
from app.processors.transit_calculator import air_transit, great_circle_km, sea_transit
from app.services import planning_service

# 부산 출발 정기 컨테이너선의 공표 소요일 (직항 FCL, 항구에서 항구까지)
SEA_REFERENCE = {
    "JPYOK": (1, 3),      # 요코하마
    "HKHKG": (3, 5),      # 홍콩
    "SGSIN": (7, 9),      # 싱가포르
    "USLAX": (11, 14),    # 로스앤젤레스
    "AUSYD": (14, 18),    # 시드니
    "AEJEA": (18, 22),    # 제벨알리
    "USNYC": (27, 32),    # 뉴욕·뉴저지
    "NLRTM": (30, 35),    # 로테르담
    "DEHAM": (30, 36),    # 함부르크
    "BRSSZ": (32, 38),    # 산투스
}

# 인천 출발 항공 화물의 공표 소요일 (공항에서 공항까지)
AIR_REFERENCE = {"NRT": (1, 2), "DXB": (2, 3), "FRA": (2, 3), "LAX": (2, 3), "JFK": (2, 4)}


@pytest.mark.parametrize("code,expected", SEA_REFERENCE.items())
def test_sea_transit_matches_published_schedules(app, code, expected):
    """주요 항로의 계산값이 공표 스케줄 범위와 겹쳐야 합니다."""

    summary = planning_service.transit_summary("KRPUS", code)
    days = summary["sea"]["FCL"]
    assert days["min"] <= expected[1] and days["max"] >= expected[0], (
        f"{code}: 계산 {days['min']}~{days['max']}일 · 공표 {expected[0]}~{expected[1]}일")


@pytest.mark.parametrize("code,expected", AIR_REFERENCE.items())
def test_air_transit_matches_published_schedules(app, code, expected):
    """주요 노선의 항공 계산값이 공표 소요일과 겹쳐야 합니다."""

    days = planning_service.transit_summary("ICN", code)["air"]
    assert days["min"] <= expected[1] and days["max"] >= expected[0], (
        f"{code}: 계산 {days['min']}~{days['max']}일 · 공표 {expected[0]}~{expected[1]}일")


def test_sea_route_uses_real_distance(app):
    """해상 거리는 육지를 피한 실제 항로 거리입니다."""

    route = location_client.sea_route("KRPUS", "NLRTM")
    # 부산→로테르담은 수에즈 경유 약 20,200km로, 대권거리(약 8,600km)보다 훨씬 깁니다.
    assert 19_000 < route["distance_km"] < 21_500
    assert "suez" in route["passages"]

    busan = location_client.find_location("KRPUS")
    rotterdam = location_client.find_location("NLRTM")
    straight = great_circle_km((busan["lat"], busan["lon"]), (rotterdam["lat"], rotterdam["lon"]))
    assert route["distance_km"] > straight * 2


def test_lcl_adds_cfs_handling(app):
    """LCL은 출발지 혼재와 도착지 적출만큼 FCL보다 오래 걸립니다."""

    fcl = sea_transit(10_000, [], "FCL")
    lcl = sea_transit(10_000, [], "LCL")
    assert lcl["min"] - fcl["min"] == pytest.approx(7, abs=1)
    assert "출발지 CFS 혼재" in lcl["breakdown"] and "출발지 CFS 혼재" not in fcl["breakdown"]


def test_canal_and_transshipment_add_days(app):
    """운하 통항과 환적은 각각 소요일을 늘립니다."""

    plain = sea_transit(20_000, [], "FCL")
    suez = sea_transit(20_000, ["suez"], "FCL")
    feeder = sea_transit(20_000, [], "FCL", direct=False)
    assert suez["max"] >= plain["max"]
    assert feeder["min"] > plain["min"]
    assert "환적" in feeder["breakdown"]


def test_transshipment_shows_for_ports_without_korea_service(app):
    """한국 직기항이 없는 항구는 환적을 안내합니다."""

    gdansk = planning_service.transit_summary("KRPUS", "PLGDN")
    rotterdam = planning_service.transit_summary("KRPUS", "NLRTM")
    assert gdansk["sea_route"]["transship"] is True
    assert rotterdam["sea_route"]["transship"] is False
    # 환적하는 그단스크가 직기항하는 로테르담보다 오래 걸립니다.
    assert gdansk["sea"]["FCL"]["min"] > rotterdam["sea"]["FCL"]["min"]


def test_air_transfer_adds_a_day(app):
    """직항이 없으면 환승 하루를 더합니다."""

    direct = air_transit(9_000)
    via = air_transit(9_000, transfers=1)
    assert via["min"] > direct["min"] and "환승" in via["breakdown"]


def test_destination_ports_group_direct_before_transship(app):
    """도착 항구는 한국 직기항을 위에, 환적이 필요한 항구를 아래에 둡니다."""

    items = planning_service.search_locations("", "SEA", "destination", country="VN")["data"]
    order = [{True: 0, None: 1, False: 2}[item["sea_direct"]] for item in items]
    assert order == sorted(order)

    # 환적이 필요한 항구에는 어디서 갈아타는지 함께 알려줍니다.
    gdansk = location_client.find_location("PLGDN")
    assert gdansk["sea_direct"] is False
    assert [code for code, _ in gdansk["sea_transfer_via"]]
    # 그단스크는 북유럽 환적항을 거칩니다.
    assert gdansk["sea_transfer_via"][0][0].startswith(("DE", "NL", "BE"))


def test_destination_airports_group_by_selected_origin(app):
    """고른 국내 공항에서 직항이 있는 공항이 위로 옵니다."""

    def listing(origin):
        result = planning_service.search_locations("", "AIR", "destination", "VN", origin)
        return [(item["code"], item["direct_from_korea"]) for item in result["data"]]

    from_busan = listing("PUS")
    assert [direct for _, direct in from_busan] == sorted(
        (direct for _, direct in from_busan), reverse=True)

    # 하이퐁은 인천에서만 직항이라 김해를 고르면 환승 쪽으로 내려갑니다.
    assert dict(from_busan)["HPH"] is False
    assert dict(listing("ICN"))["HPH"] is True


def test_air_uses_published_flight_times(app):
    """직항이 있으면 공표 시간표의 실제 운항 시간을 씁니다."""

    narita = planning_service.transit_summary("ICN", "NRT")["air"]
    assert narita["scheduled"] is True
    assert 2 <= narita["flight_hours"] <= 3          # 인천~나리타는 2시간대입니다.

    saigon = planning_service.transit_summary("PUS", "SGN")["air"]
    assert saigon["scheduled"] is True and 4 <= saigon["flight_hours"] <= 6

    # 직항이 없으면 거리로 추정하고 환승 시간을 더합니다.
    dubai = planning_service.transit_summary("CJU", "DXB")["air"]
    assert dubai["scheduled"] is False and "환승" in dubai["breakdown"]


def test_flight_minutes_come_from_route_data(app):
    """운항 시간은 출발 공항별로 따로 기록됩니다."""

    frankfurt = location_client.find_location("FRA")
    assert set(frankfurt["flight_minutes"]) <= set(frankfurt["direct_from"])
    assert frankfurt["flight_minutes"]["ICN"] > 600      # 10시간 이상

    # 국내 공항은 출발지라 판정 대상이 아닙니다.
    assert location_client.find_location("ICN")["flight_minutes"] == {}
