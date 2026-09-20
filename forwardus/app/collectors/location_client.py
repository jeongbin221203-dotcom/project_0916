"""Port and airport master data for autocomplete.

Codes come from the official UN/LOCODE list (see data/build_locations.py).
"""

from __future__ import annotations

from copy import deepcopy
from functools import lru_cache

from app.collectors.base_client import fail, load_mock, ok

# Main trade ports are listed first; the rest follow under "기타 항구".
MAX_MAIN_RESULTS = 40
MAX_OTHER_RESULTS = 12
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
    majors_only = not keyword and not country
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
            PORT_CLASS_RANK.get(item.get("port_class"), 0),
            HARBOR_SIZE_RANK.get(item.get("harbor_size"), 9),
            len(item["name"]),
            item["name"],
        )

    main_ports = sorted((item for item in results if item["major"]), key=rank)[:MAX_MAIN_RESULTS]
    other_ports = sorted((item for item in results if not item["major"]), key=rank)[:MAX_OTHER_RESULTS]
    return ok(deepcopy(main_ports + other_ports), "mock")
