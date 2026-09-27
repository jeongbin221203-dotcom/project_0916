"""Port and airport master data for autocomplete.

Codes come from the official UN/LOCODE list (see data/build_locations.py).
"""

from __future__ import annotations

from copy import deepcopy
from functools import lru_cache

from app.collectors.base_client import fail, load_mock, ok
from app.processors.transit_calculator import great_circle_km

# 목록에는 주요 항구·공항만 노출합니다. 그 밖의 항구는 화면의 "직접 입력"에서
# UN/LOCODE 전체 색인(search_unlocode)으로 찾습니다.
MAX_MAIN_RESULTS = 50
# World Port Index harbour size, biggest first.
HARBOR_SIZE_RANK = {"L": 0, "M": 1, "S": 2, "V": 3}
# 국내 무역항은 국가관리 -> 지방관리 순으로 보여줍니다.
PORT_CLASS_RANK = {"national": 0, "local": 1}
CODE_MIN_LENGTH = 3
CODE_MAX_LENGTH = 10


def _all_locations() -> list[dict]:
    return load_mock("locations")


def _data_version() -> int:
    """Identifies the loaded data set so derived tables rebuild with it."""

    return len(_all_locations())


def _by_code() -> dict[str, dict]:
    return _build_code_index(_data_version())


@lru_cache(maxsize=2)
def _build_code_index(_version: int) -> dict[str, dict]:
    return {item["code"]: item for item in _all_locations()}


def _countries() -> dict[str, dict]:
    return _build_countries(_data_version())


@lru_cache(maxsize=2)
def _build_countries(_version: int) -> dict[str, dict]:
    """Country code → name, region, and location counts."""

    countries: dict[str, dict] = {}
    for item in _all_locations():
        entry = countries.setdefault(item["country_code"], {
            "code": item["country_code"],
            "name": item["country"],
            "name_en": item["country_en"],
            "region": item["region"],
            "port_count": 0,
            "airport_count": 0,
        })
        entry["port_count" if item["kind"] == "port" else "airport_count"] += 1
    return countries


def _unlocode_index() -> dict[str, list]:
    """UN/LOCODE 전체 항구 색인 (code → [영문명, 국가코드])."""

    return load_mock("unlocode_ports")


def lookup_unlocode(code: str) -> dict | None:
    """코드가 실제 UN/LOCODE인지 확인하고 이름·국가를 돌려줍니다."""

    code = (code or "").strip().upper()
    entry = _unlocode_index().get(code)
    if not entry:
        return None
    return {
        "code": code,
        "name_en": entry[0],
        "country_code": entry[1],
        "name_ko": entry[2] if len(entry) > 2 else "",
    }


def _normalize(name: str) -> str:
    return "".join(ch for ch in (name or "").lower() if ch.isalnum())


def find_country_by_name(name: str) -> str | None:
    """'베트남', 'Vietnam'처럼 나라 이름을 코드로 바꿉니다."""

    needle = _normalize(name)
    if not needle:
        return None
    for country in _countries().values():
        if needle in (_normalize(country["name"]), _normalize(country["name_en"])):
            return country["code"]
    return None


def search_unlocode(country_code: str, query: str, limit: int = 50) -> dict:
    """직접 입력 칸에서 쓰는 검색.

    코드와 이름(영문·한글)을 대조하고, 나라 이름을 입력하면 그 나라 항구를
    모두 보여줍니다. 목록에 없는 소규모 항구도 여기에서 찾을 수 있습니다.
    """

    country_code = (country_code or "").strip().upper()
    needle = (query or "").strip().lower()
    country_match = find_country_by_name(query)
    if country_match and (not country_code or country_code == country_match):
        country_code, needle = country_match, ""
    if not needle and not country_code:
        return ok([], "mock")

    compact = _normalize(needle)
    listed = _by_code()
    results = []
    for code, entry in _unlocode_index().items():
        if country_code and entry[1] != country_code:
            continue
        korean = entry[2] if len(entry) > 2 else ""
        haystack = f"{code} {entry[0]} {korean}".lower()
        if needle and not (needle in haystack or (compact and compact in _normalize(f"{entry[0]}{korean}"))):
            continue
        known = listed.get(code)
        results.append({
            "code": code,
            "name": (known or {}).get("name") or korean or entry[0],
            "name_en": entry[0],
            "country_code": entry[1],
            # 목록(주요 항구)에 있는 곳인지 표시합니다.
            "major": bool(known and known.get("major")),
        })
    # 코드가 정확히 일치하는 곳, 주요 항구, 이름이 짧은 곳 순으로 보여줍니다.
    results.sort(key=lambda item: (
        item["code"].lower() != needle,
        not item["major"],
        not item["name"].lower().startswith(needle) if needle else False,
        len(item["name"]),
        item["code"],
    ))
    return ok(results[:limit], "mock")


def find_unlocode_by_name(country_code: str, name: str, limit: int = 5) -> list[dict]:
    """국가 안에서 이름으로 실제 UN/LOCODE를 찾습니다.

    완전히 같은 이름을 먼저 찾고, 없으면 이름이 포함된 항구를 돌려줍니다.
    """

    country_code = (country_code or "").strip().upper()
    needle = _normalize(name)
    if not needle:
        return []

    exact, partial = [], []
    for code, entry in _unlocode_index().items():
        port_name, code_country = entry[0], entry[1]
        korean_name = entry[2] if len(entry) > 2 else ""
        if code_country != country_code:
            continue
        item = {"code": code, "name_en": port_name, "country_code": code_country, "name_ko": korean_name}
        # 영문명과 한글명(있는 경우) 모두 대조합니다.
        for candidate in (port_name, korean_name):
            normalized = _normalize(candidate)
            if not normalized:
                continue
            if normalized == needle:
                exact.append(item)
                break
            if needle in normalized or normalized in needle:
                partial.append(item)
                break
    matches = exact or partial
    matches.sort(key=lambda item: (len(item["name_en"]), item["code"]))
    return matches[:limit]


def find_location(code: str) -> dict | None:
    return deepcopy(_by_code().get(str(code or "").strip().upper()))


def get_country(country_code: str) -> dict | None:
    return deepcopy(_countries().get(str(country_code or "").strip().upper()))


def list_countries(kind: str, exclude: list[str] | None = None) -> dict:
    """Countries that have at least one location of the requested kind."""

    field = "port_count" if kind == "port" else "airport_count"
    excluded = {code.upper() for code in (exclude or [])}
    items = [
        {**country, "count": country[field]}
        for country in _countries().values()
        if country[field] and country["code"] not in excluded
    ]
    items.sort(key=lambda item: item["name"])
    return ok(items, "mock")


def apply_origin(items: list[dict], origin_code: str | None) -> list[dict]:
    """출발 공항을 알면 그 공항 기준으로 직항 여부를 다시 계산합니다."""

    origin_code = (origin_code or "").strip().upper()
    if not origin_code:
        return items
    for item in items:
        if item["kind"] != "airport" or item.get("direct_from_korea") is None:
            continue
        item["direct_from_korea"] = origin_code in (item.get("direct_from") or [])
    return items


# 사람이 흔히 쓰는 표기 → 우리 자료에 적힌 이름.
#
# 자료는 "호찌민항"·"안트베르펜항"으로 적혀 있는데, 실무에서는 "호치민"·"앤트워프"라고
# 씁니다. 그대로 치면 **한 건도 안 나와 도착지를 고를 수가 없습니다.**
# 흔한 지명 61개로 재어 보니 다섯 곳이 그랬습니다. (2026-09-26)
PLACE_ALIASES = {
    "호치민": "호찌민", "호치민시": "호찌민", "사이공": "호찌민",
    "앤트워프": "안트베르펜", "안트워프": "안트베르펜", "앤트워프항": "안트베르펜",
    "하노이": "노이바이",
    "델리": "인디라", "뉴델리": "인디라",
    "뭄바이": "mumbai", "봄베이": "mumbai",
    "제다": "jeddah", "젯다": "jeddah",
    "쿠알라룸푸르": "kuala",
    "베이징": "beijing", "북경": "beijing",
    "상해": "상하이", "심천": "선전", "청도": "칭다오", "대련": "다롄", "천진": "톈진",
    "광주(중국)": "광저우",
}


def search_locations(query: str, kind: str | None = None, country: str | None = None,
                     origin_code: str | None = None) -> dict:
    """Match on code, Korean/English name, city, or country."""

    try:
        items = _all_locations()
    except (OSError, ValueError):
        return fail("MOCK_DATA_ERROR", "mock")

    keyword = (query or "").strip().lower()
    keyword = PLACE_ALIASES.get(keyword, keyword)
    country = (country or "").strip().upper()
    # With no keyword and no country there is nothing to rank by, so only the
    # well-known locations are suggested. Typing searches the full list.
    majors_only = True
    results = []
    for item in items:
        if kind and item["kind"] != kind:
            continue
        if country and item["country_code"] != country:
            continue
        if majors_only and not item["major"]:
            continue
        if keyword:
            haystack = " ".join((
                item["code"], item["name"], item["name_en"], item["country"], item["country_en"]
            )).lower()
            if keyword not in haystack:
                continue
        results.append(item)

    # 정렬 순서
    #   1) 코드가 정확히 일치 / 이름이 검색어로 시작
    #   2) 국내 무역항 구분, 항공화물 거점·직항 구분
    #   3) 대표 항만·공항(지정 순위 10위 이내)
    #   4) 한글 이름(가나다순) -> 영문 이름(알파벳순)
    CURATED_LIMIT = 10

    def rank(item: dict) -> tuple:
        has_korean = item["name"] != item["name_en"]
        curated = item.get("size_rank") or 99
        return (
            item["code"].lower() != keyword,
            not (item["name"].lower().startswith(keyword) or item["name_en"].lower().startswith(keyword)),
            # 항공화물 거점 -> 직항 -> 나머지
            not (item.get("cargo_hub") and item.get("direct_from_korea")),
            item.get("direct_from_korea") is False,
            # 도착 항구도 같은 순서로: 한국 직기항 -> 항로 기록 없음 -> 환적 필요.
            # 출발지인 국내 무역항은 아래의 관리주체·물동량 순서를 씁니다.
            0 if item["country_code"] == "KR" else {True: 0, None: 1, False: 2}[item.get("sea_direct")],
            PORT_CLASS_RANK.get(item.get("port_class"), 0),
            # 국내 무역항은 물동량 순서를 유지합니다.
            -(item.get("cargo_volume_mt") or 0),
            # 부두를 모항 옆에 붙이는 용도로만 씁니다. (국내 무역항)
            item.get("port_group") if item.get("cargo_volume_mt") else "",
            bool(item.get("is_terminal")),
            # 지정 순위가 있는 대표 공항까지만 순서를 고정합니다.
            curated if curated <= CURATED_LIMIT else CURATED_LIMIT + 1,
            # 한글 이름을 먼저(가나다순), 영문 이름은 그 뒤(알파벳순)
            not has_korean,
            item["name"] if has_korean else item["name_en"].lower(),
        )

    items = apply_origin(deepcopy(sorted(results, key=rank)), origin_code)
    if origin_code:
        # 직항 여부가 바뀌었으므로 다시 정렬합니다.
        items.sort(key=rank)
    return ok(items, "mock")


# 지금 정기편이 뜨지 않는 국내 공항. 여기서 출발한다고 소요일을 내면
# 예약할 수 없는 일정을 알려 주는 셈이 됩니다.
# 확인: 한국공항공사 운항스케줄 페이지 (출발·도착 표가 모두 비어 있음)
SUSPENDED_AIRPORTS = {
    "MWX": {
        "reason": "무안국제공항은 정기편 운항이 멈춰 있습니다.",
        "detail": "한국공항공사 운항스케줄에 등록된 정기편이 없습니다. "
                  "재개 시점이 정해지지 않아 인천·김해에서 보내야 합니다.",
        "checked_on": "2026-09-20",
        "source": "한국공항공사 무안국제공항 운항스케줄",
    },
}


@lru_cache(maxsize=1)
def korean_air_gateways() -> tuple[str, ...]:
    """국제선이 실제로 뜨는 국내 공항. 직항 목적지가 많은 곳을 먼저 둡니다.

    수출 화물을 보낼 공항을 고를 때 씁니다. 거리만 보면 무안·제주처럼
    국제 화물을 보낼 수 없는 공항이 뽑힙니다.
    """

    counts: dict[str, int] = {}
    for item in _all_locations():
        if item["kind"] != "airport":
            continue
        for code in item.get("direct_from") or []:
            counts[code] = counts.get(code, 0) + 1
    ordered = sorted((code for code in counts if code not in SUSPENDED_AIRPORTS),
                     key=lambda code: -counts[code])
    return tuple(ordered)


def airport_service_status(code: str) -> dict:
    """그 공항이 지금 정기편을 띄우는지. 모르면 운항 중으로 봅니다."""

    stopped = SUSPENDED_AIRPORTS.get((code or "").strip().upper())
    return {"operating": False, **stopped} if stopped else {"operating": True}


def sea_links() -> dict:
    """국내 항구별로 실제 항로가 이어진 나라 목록.

    data/build_sea_links.py가 searoute 항만 네트워크에서 뽑은 값입니다.
    """

    try:
        return load_mock("sea_links")
    except (OSError, ValueError):
        return {"origins": {}, "by_country": {}}


def sea_lane_direct(origin_code: str, destination_country: str) -> dict:
    """이 출발항에서 그 나라로 가는 배가 실제로 있는지 봅니다.

    예전에는 도착항만 보고 "한국에서 직기항이 있는 항구"인지 판정했습니다.
    그러면 광양항처럼 멕시코 항로가 없는 항구에서도 직기항이라고 나왔습니다.
    출발항이 그 나라와 이어져 있는지를 함께 봐야 맞습니다.

    `known`이 False면 자료가 없다는 뜻이고, 없다고 단정하지 않습니다.
    """

    links = sea_links()
    origin = (origin_code or "").strip().upper()
    country = (destination_country or "").strip().upper()
    countries = links.get("origins", {}).get(origin)
    if countries is None or not country:
        return {"known": False}
    if country in countries:
        return {"known": True, "direct": True, "origin": origin, "alternatives": []}
    # 같은 나라로 가는 배가 있는 다른 국내 항구를 알려 줍니다.
    others = [code for code in links.get("by_country", {}).get(country, []) if code != origin]
    return {"known": True, "direct": False, "origin": origin, "alternatives": others}


def sea_route(origin_code: str, destination_code: str) -> dict | None:
    """미리 계산해 둔 실제 해상 항로 거리와 지나는 길목을 돌려줍니다.

    data/build_sea_routes.py가 searoute 해상 항로망에서 구한 값입니다.
    """

    try:
        routes = load_mock("sea_routes")["routes"]
    except (OSError, ValueError, KeyError):
        return None
    leg = routes.get(origin_code, {}).get(destination_code)
    if not leg:
        return None
    return {"distance_km": leg[0], "passages": leg[1] if len(leg) > 1 else []}


def nearest(location: dict, kind: str, country_code: str | None = None) -> dict | None:
    """같은 나라에서 좌표가 가장 가까운 항구(또는 공항)를 찾습니다.

    해상 모드에서 항공 소요시간을, 항공 모드에서 해상 소요시간을 함께 보여줄 때
    짝이 되는 지점을 고르는 데 씁니다.
    """

    if not location or location.get("lat") is None:
        return None
    country_code = country_code or location["country_code"]
    here = (location["lat"], location["lon"])
    candidates = [item for item in _all_locations()
                  if item["kind"] == kind and item["country_code"] == country_code
                  and item["lat"] is not None and item.get("major")
                  and (kind != "airport" or item["code"] not in SUSPENDED_AIRPORTS)]
    if kind == "airport" and country_code == "KR":
        # 국제선이 뜨는 공항만 고릅니다. 무안·제주처럼 화물을 보낼 수 없는
        # 공항이 거리만으로 뽑히면 예약할 수 없는 일정을 알려 주게 됩니다.
        gateways = set(korean_air_gateways())
        candidates = [item for item in candidates if item["code"] in gateways] or candidates
    # 한국에서 실제로 직기항·직항이 있는 곳을 먼저 고릅니다.
    key = "sea_direct" if kind == "port" else "direct_from_korea"
    candidates = [item for item in candidates if item.get(key)] or candidates
    if not candidates:
        return None
    return deepcopy(min(candidates, key=lambda item: great_circle_km(here, (item["lat"], item["lon"]))))


def country_name(country_code: str) -> str:
    """국가코드의 한글 이름. 목록에 없으면 코드를 그대로 돌려줍니다."""

    code = (country_code or "").strip().upper()
    for item in _all_locations():
        if item["country_code"] == code:
            return item["country"]
    return code
