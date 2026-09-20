"""HS CODE 조회와 도착국 규제 정보.

HS CODE는 관세청 UNI-PASS "HS부호검색" API에서 찾고, 키가 없거나 호출이
실패하면 data/mock/hs_codes.json의 예시 목록을 씁니다.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from copy import deepcopy

from app.collectors.base_client import fail, get_config, load_mock, ok, request_text

REQUIREMENT_STATUSES = ["confirmed", "check_required", "not_applicable", "unknown"]


# 관세청 UNI-PASS "HS부호검색". 품명(한/영)이나 HSK 10자리로 찾습니다.
UNIPASS_HS_URL = "https://unipass.customs.go.kr:38010/ext/rest/hsSgnQry/searchHsSgn"
HS_CODE_LENGTH = 10
MAX_HS_RESULTS = 12
# 너무 짧은 말로 찾으면 응답이 수 MB가 되고 쓸모도 없습니다.
MIN_KOREAN_LENGTH = 2
MIN_ENGLISH_LENGTH = 3


def _has_hangul(text: str) -> bool:
    return any("가" <= ch <= "힣" for ch in text)


def _hs_key() -> str:
    return (get_config("UNIPASS_API_KEYS", {}) or {}).get("HS_CODE_SEARCH", "")


def search_hs_codes_mock(query: str) -> dict:
    """API를 쓸 수 없을 때 쓰는 예시 목록."""

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
    return ok(results[:MAX_HS_RESULTS], "mock")


def search_hs_codes(query: str) -> dict:
    """관세청 HS부호검색으로 품목을 찾습니다. 실패하면 예시 목록을 씁니다."""

    keyword = (query or "").strip()
    key = _hs_key()
    if not keyword or not key:
        return search_hs_codes_mock(keyword)

    digits = keyword.replace(".", "").replace("-", "")
    korean = _has_hangul(keyword)
    if digits.isdigit():
        # HS부호로는 10자리 완전일치만 조회됩니다. 그보다 짧으면 예시 목록에서 찾습니다.
        if len(digits) != HS_CODE_LENGTH:
            return search_hs_codes_mock(keyword)
        params = {"hsSgn": digits, "koenTp": "1"}
    else:
        if len(keyword) < (MIN_KOREAN_LENGTH if korean else MIN_ENGLISH_LENGTH):
            return ok([], "api")
        params = {"prnm": keyword, "koenTp": "1" if korean else "2"}

    result = request_text("GET", UNIPASS_HS_URL, params={"crkyCn": key, **params})
    if not result["success"]:
        return search_hs_codes_mock(keyword)
    try:
        root = ET.fromstring(result["data"])
    except ET.ParseError:
        return search_hs_codes_mock(keyword)

    notice = (root.findtext("ntceInfo") or "").strip()
    if notice:
        return fail("API_INVALID_REQUEST", "api", notice)

    # 같은 HS부호가 세율 종류만큼 반복돼 오므로 부호 기준으로 한 번만 담습니다.
    items: dict[str, dict] = {}
    for row in root.findall("hsSgnSrchRsltVo"):
        code = (row.findtext("hsSgn") or "").strip()
        if not code or code in items:
            continue
        items[code] = {
            "code": format_hs_code(code),
            "name": (row.findtext("korePrnm") or "").strip(),
            "name_en": (row.findtext("englPrnm") or "").strip(),
            "weight_unit": (row.findtext("wghtUt") or "").strip(),
            "quantity_unit": (row.findtext("qtyUt") or "").strip(),
        }
        if len(items) >= MAX_HS_RESULTS:
            break
    return ok(list(items.values()), "api")


def format_hs_code(code: str) -> str:
    """HSK 10자리를 읽기 쉽게 끊어 보여줍니다. (3304991000 -> 3304.99-1000)"""

    digits = (code or "").strip()
    if len(digits) != HS_CODE_LENGTH or not digits.isdigit():
        return digits
    return f"{digits[:4]}.{digits[4:6]}-{digits[6:]}"


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
