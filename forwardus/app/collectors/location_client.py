"""Port and airport master data for autocomplete.

Codes come from the official UN/LOCODE list (see data/build_locations.py).
"""

from __future__ import annotations

from copy import deepcopy
from functools import lru_cache

from app.collectors.base_client import fail, load_mock, ok

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
    return deepcopy(_by_code().get((code or "").strip().upper()))


def get_country(country_code: str) -> dict | None:
    return deepcopy(_countries().get((country_code or "").strip().upper()))


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


def search_locations(query: str, kind: str | None = None, country: str | None = None) -> dict:
    """Match on code, Korean/English name, city, or country."""

    try:
        items = _all_locations()
    except (OSError, ValueError):
        return fail("MOCK_DATA_ERROR", "mock")

    keyword = (query or "").strip().lower()
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

    # Exact code, then names starting with the keyword, then harbour size.
    # Shorter names win so that "부산" lists 부산항 before 부산신항.
    def rank(item: dict) -> tuple:
        return (
            item["code"].lower() != keyword,
            not (item["name"].lower().startswith(keyword) or item["name_en"].lower().startswith(keyword)),
            # 공항은 국내 직항편이 있는 곳을 먼저 보여줍니다.
            item.get("direct_from_korea") is False,
            PORT_CLASS_RANK.get(item.get("port_class"), 0),
            # 공항은 국가 안에서 규모가 큰 곳부터.
            item.get("size_rank") or 99,
            # 물동량이 많은 항만부터, 같은 항만의 부두는 모항 다음에 표시합니다.
            -(item.get("cargo_volume_mt") or 0),
            item.get("port_group") or "",
            bool(item.get("is_terminal")),
            HARBOR_SIZE_RANK.get(item.get("harbor_size"), 9),
            len(item["name"]),
            item["name"],
        )

    return ok(deepcopy(sorted(results, key=rank)[:MAX_MAIN_RESULTS]), "mock")
