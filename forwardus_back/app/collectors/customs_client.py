"""HS CODE lookup and destination regulation data (mock provider)."""

from __future__ import annotations

from copy import deepcopy

from app.collectors.base_client import fail, load_mock, ok

REQUIREMENT_STATUSES = ["confirmed", "check_required", "not_applicable", "unknown"]


def search_hs_codes(query: str) -> dict:
    try:
        items = load_mock("hs_codes")
    except (OSError, ValueError):
        return fail("MOCK_DATA_ERROR", "mock")
    keyword = (query or "").strip().lower().replace(".", "")
    results = [
        deepcopy(item)
        for item in items
        if not keyword
        or keyword in item["code"].replace(".", "")
        or keyword in item["name"].lower()
        or keyword in item["name_en"].lower()
    ]
    return ok(results[:10], "mock")


def fetch_regulations(hs_code: str, country_code: str) -> dict:
    """Return regulation check items for an HS code and destination country.

    Items state what must be checked; they never declare that export is permitted.
    """

    # TODO: call the live provider via base_client.request_json when CUSTOMS_API_KEY is configured.

    try:
        data = load_mock("regulations")
    except (OSError, ValueError):
        return fail("MOCK_DATA_ERROR", "mock")

    chapter = (hs_code or "").replace(".", "")[:2]
    items = [deepcopy(item) for item in data["common"]]
    chapter_rules = data["by_chapter"].get(chapter, {})
    country_items = chapter_rules.get(country_code)
    if country_items:
        items.extend(deepcopy(country_items))
    elif chapter_rules:
        items.append({
            "title": "목적지 국가 규제 데이터 없음",
            "status": "unknown",
            "detail": "해당 품목의 목적지 국가 규제 데이터가 등록되어 있지 않습니다. 관세사 또는 바이어를 통해 확인하세요.",
        })
    else:
        items.append({
            "title": "품목별 규제 데이터 없음",
            "status": "unknown",
            "detail": "이 HS CODE 류(Chapter)에 대한 규제 데이터가 아직 없습니다.",
        })
    for item in items:
        item["source"] = "mock"
    return ok({"hs_code": hs_code, "country_code": country_code, "items": items}, "mock")
