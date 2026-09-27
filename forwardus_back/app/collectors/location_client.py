"""Port and airport master data for autocomplete."""

from __future__ import annotations

from copy import deepcopy

from app.collectors.base_client import fail, load_mock, ok

MAX_RESULTS = 10


def _all_locations() -> list[dict]:
    return load_mock("locations")


def find_location(code: str) -> dict | None:
    code = (code or "").strip().upper()
    for item in _all_locations():
        if item["code"] == code:
            return deepcopy(item)
    return None


def search_locations(query: str, kind: str | None = None) -> dict:
    """Match on code, Korean/English name, city, or country."""

    try:
        items = _all_locations()
    except (OSError, ValueError):
        return fail("MOCK_DATA_ERROR", "mock")

    keyword = (query or "").strip().lower()
    results = []
    for item in items:
        if kind and item["kind"] != kind:
            continue
        haystack = " ".join(
            [item["code"], item["name"], item["name_en"], item["city"], item["city_en"], item["country"]]
        ).lower()
        if not keyword or keyword in haystack:
            results.append(deepcopy(item))
    # Exact code matches first, then alphabetical by code.
    results.sort(key=lambda item: (item["code"].lower() != keyword, item["code"]))
    return ok(results[:MAX_RESULTS], "mock")
