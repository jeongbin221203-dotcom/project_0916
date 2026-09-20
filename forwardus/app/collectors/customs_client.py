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
    """관세청 HS부호검색(API018)으로 품목을 찾습니다.

    품명은 한글·영문 모두 부분일치로 찾고, HS부호는 10자리 완전일치만 됩니다.
    API 키가 없거나 호출이 실패할 때만 예시 목록으로 되돌아갑니다.
    """

    keyword = (query or "").strip()
    key = _hs_key()
    if not key:
        return search_hs_codes_mock(keyword)
    if not keyword:
        return ok([], "api")

    digits = keyword.replace(".", "").replace("-", "").replace(" ", "")
    korean = _has_hangul(keyword)
    if digits.isdigit():
        # HS부호는 10자리 완전일치만 조회됩니다. (연계 가이드 3.2.18)
        if len(digits) != HS_CODE_LENGTH:
            return ok([], "api")
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

    # 영문으로 찾으면 한글품명이 비어 옵니다. 부호로 다시 물어 한글 이름을 채웁니다.
    if params.get("koenTp") == "2":
        _fill_korean_names(key, items)
    return ok(list(items.values()), "api")


def _fill_korean_names(key: str, items: dict[str, dict]) -> None:
    """영문 검색 결과에 한글품명을 채워 넣습니다. (부호별 재조회)"""

    for code, item in items.items():
        if item["name"]:
            continue
        result = request_text("GET", UNIPASS_HS_URL,
                              params={"crkyCn": key, "hsSgn": code, "koenTp": "1"})
        if not result["success"]:
            return
        try:
            root = ET.fromstring(result["data"])
        except ET.ParseError:
            return
        row = root.find("hsSgnSrchRsltVo")
        if row is not None:
            item["name"] = (row.findtext("korePrnm") or "").strip()


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


# 관세청 UNI-PASS "관세율 기본 조회"(API030). HS부호 10자리로 세율을 가져옵니다.
UNIPASS_TARIFF_URL = "https://unipass.customs.go.kr:38010/ext/rest/trrtQry/retrieveTrrt"


def fetch_tariff_rates(hs_code: str) -> dict:
    """HS부호의 세율 목록을 조회합니다. (기본세율·WTO·FTA 협정세율)

    응답의 루트 태그는 가이드 문서와 달리 소문자로 옵니다(trrtQryRtnVo).
    """

    digits = (hs_code or "").replace(".", "").replace("-", "").replace(" ", "")
    if len(digits) != HS_CODE_LENGTH or not digits.isdigit():
        return fail("VALIDATION_ERROR", "api", "HS부호 10자리를 입력해주세요.")

    key = (get_config("UNIPASS_API_KEYS", {}) or {}).get("TARIFF_RATE", "")
    if not key:
        return fail("API_AUTH_FAILED", "api", "관세율 조회 API 키가 없습니다.")

    result = request_text("GET", UNIPASS_TARIFF_URL, params={"crkyCn": key, "hsSgn": digits})
    if not result["success"]:
        return result
    try:
        root = ET.fromstring(result["data"])
    except ET.ParseError:
        return fail("API_INVALID_RESPONSE", "api")

    notice = (root.findtext("ntceInfo") or "").strip()
    rows = [{
        "code": (row.findtext("trrtTpcd") or "").strip(),
        "name": (row.findtext("trrtTpNm") or "").strip(),
        "rate": (row.findtext("trrt") or "").strip(),
        "unit_amount": (row.findtext("prutXamt") or "").strip(),
        "start_date": (row.findtext("aplyStrtDt") or "").strip(),
        "end_date": (row.findtext("aplyEndDt") or "").strip(),
    } for row in root.findall("trrtQryRsltVo")]
    if not rows and notice:
        return fail("API_NO_DATA", "api", notice)
    return ok(rows, "api")


# 관세청 "통계부호"(API019). 국가코드 부호는 statsSgnTp=A06 입니다.
UNIPASS_STATS_URL = "https://unipass.customs.go.kr:38010/ext/rest/statsSgnQry/retrieveStatsSgnBrkd"
COUNTRY_CODE_GROUP = "A06"


def fetch_country_codes() -> dict:
    """관세청이 쓰는 국가코드 목록. {한글 국가명: 2자리 코드}

    협정세율 구분명("한ㆍ칠레FTA협정세율")에서 나라를 찾아내는 데 씁니다.
    """

    key = (get_config("UNIPASS_API_KEYS", {}) or {}).get("STATISTICS_CODE", "")
    if not key:
        return fail("API_AUTH_FAILED", "api", "통계부호 조회 API 키가 없습니다.")

    result = request_text("GET", UNIPASS_STATS_URL,
                          params={"crkyCn": key, "statsSgnTp": COUNTRY_CODE_GROUP})
    if not result["success"]:
        return result
    try:
        root = ET.fromstring(result["data"])
    except ET.ParseError:
        return fail("API_INVALID_RESPONSE", "api")

    names = {}
    for row in root.findall("statsSgnQryVo2"):
        code = (row.findtext("cdValtVal") or "").strip().upper()
        name = (row.findtext("cdValtValNm") or "").strip()
        if len(code) == 2 and name:
            names[name] = code
    if not names:
        return fail("API_NO_DATA", "api", (root.findtext("ntceInfo") or "").strip() or "국가코드를 받지 못했습니다.")
    return ok(names, "api")
