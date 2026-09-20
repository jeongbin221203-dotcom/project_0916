"""실제 항로 데이터로 구간 소요일을 계산합니다.

해상은 searoute 해상 항로망에서 미리 구한 실제 항로 거리(data/mock/sea_routes.json)를,
항공은 공항 좌표 사이의 대권거리를 씁니다. 여기에 터미널 작업·운하 통항·환적·
CFS 혼재 같은 실제로 걸리는 시간을 더해 문전이 아닌 "항구에서 항구까지" 일수를 냅니다.

속력과 작업 일수는 아래 상수에 모아 두었고, 정기선 공표 스케줄과 맞는지는
tests/test_transit_calculator.py에서 주요 항로로 검증합니다.
"""

from __future__ import annotations

from math import asin, cos, radians, sin, sqrt

KM_PER_NAUTICAL_MILE = 1.852

# --- 해상 -------------------------------------------------------------------
# 정기 컨테이너선의 실효 평균 속력(노트). 중간 기항까지 포함한 값이라
# 본선 항해속력(16~18노트)보다 낮습니다.
SEA_SPEED_KN = 15.0
# 아시아~북미 서안은 급행 서비스가 주력이라 실효 속력이 높습니다.
TRANSPACIFIC_SPEED_KN = 19.0
# 출항 전 반입·적재와 도착 후 양하에 걸리는 시간.
SEA_TERMINAL_DAYS = 1.2
# 운하 통항 대기(선단 편성·도선). 그 밖의 길목은 대기가 없어 더하지 않습니다.
CANAL_WAIT_DAYS = {"suez": 1.0, "panama": 1.5}
# 한국에서 직기항 선박이 없는 항구는 환적항에서 피더선을 갈아탑니다.
TRANSSHIPMENT_DAYS = 4.0
# LCL은 출발지 CFS에서 혼재하고 도착지에서 적출·분류한 뒤 인도합니다.
LCL_ORIGIN_CFS_DAYS = 3.0
LCL_DESTINATION_CFS_DAYS = 4.0

# --- 항공 -------------------------------------------------------------------
# 화물기·여객기 하부화물칸의 순항 속도(km/h)와 이착륙·활주 시간.
AIR_CRUISE_KMH = 850.0
AIR_TAKEOFF_LANDING_HOURS = 0.5
# 수출 터미널 반입·보세 반출입과 탑재 대기.
AIR_ORIGIN_DAYS = 1.0
# 도착 후 하기·통관·인도.
AIR_DESTINATION_DAYS = 0.7
# 환승 1회마다 연결편 대기와 재적재가 필요합니다.
AIR_TRANSFER_DAYS = 1.0
# 장거리 노선은 당일 연결 적재가 어려워 다음 편을 기다리는 경우가 많습니다.
AIR_LONGHAUL_HOURS = 6.0
AIR_LONGHAUL_WAIT_DAYS = 0.5

# 스케줄은 선사·항공사마다 달라 폭을 두고 안내합니다.
SPREAD_RATIO = 0.12
SEA_MIN_SPREAD_DAYS = 1.0
AIR_MIN_SPREAD_DAYS = 0.5


def great_circle_km(origin: tuple[float, float], destination: tuple[float, float]) -> float:
    """두 좌표(위도, 경도) 사이의 대권거리(km)."""

    lat1, lon1 = radians(origin[0]), radians(origin[1])
    lat2, lon2 = radians(destination[0]), radians(destination[1])
    h = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0088 * asin(sqrt(h))


def to_range(days: float, min_spread: float = SEA_MIN_SPREAD_DAYS) -> dict:
    """하루 단위로 올림·내림해 최소~최대 범위를 만듭니다."""

    spread = max(days * SPREAD_RATIO, min_spread)
    return {"min": max(1, round(days - spread)), "max": max(2, round(days + spread))}


def sea_transit(distance_km: float, passages: list[str], sea_mode: str = "FCL",
                *, direct: bool | None = True, region: str = "asia") -> dict:
    """실제 항로 거리로 해상 소요일을 계산합니다.

    `passages`는 항로가 지나는 길목(suez, panama 등)이고, `direct`는 한국에서
    직기항 선박이 관측되는 항구인지입니다. 직기항이 없으면 환적 일수를 더합니다.
    """

    miles = distance_km / KM_PER_NAUTICAL_MILE
    # 운하를 지나지 않는 북미 항로는 태평양 횡단 급행 서비스입니다.
    canal = [p for p in passages if p in CANAL_WAIT_DAYS]
    speed = TRANSPACIFIC_SPEED_KN if region == "americas" and not canal else SEA_SPEED_KN

    breakdown = {"항해": miles / (speed * 24), "터미널 작업": SEA_TERMINAL_DAYS}
    for passage in canal:
        breakdown[f"{'수에즈' if passage == 'suez' else '파나마'} 운하 통항"] = CANAL_WAIT_DAYS[passage]
    if direct is False:
        breakdown["환적"] = TRANSSHIPMENT_DAYS
    if sea_mode == "LCL":
        breakdown["출발지 CFS 혼재"] = LCL_ORIGIN_CFS_DAYS
        breakdown["도착지 CFS 적출"] = LCL_DESTINATION_CFS_DAYS

    total = sum(breakdown.values())
    return {**to_range(total), "distance_km": round(distance_km),
            "breakdown": {k: round(v, 1) for k, v in breakdown.items()}}


def air_transit(distance_km: float, *, transfers: int = 0, minutes: int | None = None) -> dict:
    """항공 화물 소요일을 계산합니다.

    `minutes`는 공표 시간표의 실제 운항 시간입니다. 직항이 있으면 그 값을 쓰고,
    없으면 공항 사이 대권거리로 비행 시간을 추정합니다.
    """

    flight_hours = (minutes / 60 if minutes
                    else distance_km / AIR_CRUISE_KMH + AIR_TAKEOFF_LANDING_HOURS)
    breakdown = {"비행": flight_hours / 24,
                 "수출 터미널": AIR_ORIGIN_DAYS,
                 "도착지 인도": AIR_DESTINATION_DAYS}
    if flight_hours > AIR_LONGHAUL_HOURS:
        breakdown["연결편 대기"] = AIR_LONGHAUL_WAIT_DAYS
    if transfers:
        breakdown["환승"] = AIR_TRANSFER_DAYS * transfers

    total = sum(breakdown.values())
    return {**to_range(total, AIR_MIN_SPREAD_DAYS), "distance_km": round(distance_km),
            "flight_hours": round(flight_hours, 1),
            "scheduled": minutes is not None,
            "breakdown": {k: round(v, 1) for k, v in breakdown.items()}}
