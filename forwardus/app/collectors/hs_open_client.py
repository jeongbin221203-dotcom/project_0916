"""관세청 말고 HS부호를 받아오는 곳. 모두 무료이고 키가 필요 없습니다.

관세청이 멈추거나 호출 한도에 걸리면 HS부호를 전혀 찾을 수 없게 됩니다.
그럴 때 쓸 자리입니다.

    1. UN Comtrade 품목분류   HS 6자리 · 영문 · 6,940개 (전 세계 공통)
    2. 미국 USITC HTS         미국 10자리 · 영문 (앞 6자리는 세계 공통)
    3. 영국 Trade Tariff      영국 10자리 · 영문

반드시 알아야 할 한계가 하나 있습니다.
**HS는 앞 6자리까지만 세계 공통입니다.** 뒤 4자리는 나라마다 다릅니다.
우리 수출신고서에는 한국 세번 10자리(HSK)가 들어가야 하므로, 여기서 찾은
6자리는 "어느 호에 속하는지"를 알려 줄 뿐 신고에 그대로 쓸 수 없습니다.
마지막 4자리는 관세청에서 확인해야 합니다.
"""

from __future__ import annotations

import json
from threading import Lock

from app.collectors import file_cache
from app.collectors.base_client import fail, ok, request_text

# UN 무역통계국이 공개하는 품목분류. 키가 필요 없습니다.
UN_URL = "https://comtradeapi.un.org/files/v1/app/reference/{edition}.json"
UN_EDITIONS = {"HS2022": "H6", "HS2017": "H5", "HS2012": "H4"}

USITC_URL = "https://hts.usitc.gov/reststop/search"
UK_URL = "https://www.trade-tariff.service.gov.uk/api/v2/search_references"

SOURCES = {
    "un": {"label": "UN Comtrade 품목분류", "digits": 6,
           "note": "전 세계가 함께 쓰는 6자리입니다.",
           "url": "https://comtradeapi.un.org"},
    "usitc": {"label": "미국 USITC 관세율표", "digits": 10,
              "note": "미국 10자리입니다. 앞 6자리만 우리와 같습니다.",
              "url": "https://hts.usitc.gov"},
    "uk": {"label": "영국 Trade Tariff", "digits": 10,
           "note": "영국 10자리입니다. 앞 6자리만 우리와 같습니다.",
           "url": "https://www.trade-tariff.service.gov.uk"},
}

LIMIT_NOTE = ("HS는 앞 6자리까지만 세계 공통입니다. 수출신고서에는 한국 세번 "
              "10자리가 들어가므로, 마지막 4자리는 관세청에서 확인해야 합니다.")


def _digits(value: str) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


# --- 1. UN Comtrade (HS 6자리, 전 세계 공통) ------------------------------------

# 품목분류표는 HS 개정(5년마다) 때만 바뀝니다. 파일은 개정판별로 따로 두고,
# 정정분을 반영하도록 이 기간이 지나면 새로 받아 봅니다. 못 받으면 예전 것을 씁니다.
UN_REFRESH_DAYS = 180

_un_tables: dict[str, tuple[tuple[str, str], ...]] = {}
_un_name_maps: dict[str, dict[str, str]] = {}
_un_lock = Lock()


def clear_cache() -> None:
    """메모리에 올려 둔 품목분류표를 비웁니다. (파일은 그대로 둡니다)"""

    _un_tables.clear()
    _un_name_maps.clear()


def _download_un_table(edition: str) -> tuple[tuple[str, str], ...]:
    code = UN_EDITIONS.get(edition, "H6")
    result = request_text("GET", UN_URL.format(edition=code), timeout=40)
    if not result["success"]:
        return ()
    try:
        rows = json.loads(result["data"])["results"]
    except (ValueError, KeyError, TypeError):
        return ()
    table = []
    for row in rows:
        number, text = str(row.get("id", "")), str(row.get("text", ""))
        if not number.isdigit():
            continue
        # "330510 - Hair preparations; shampoos" 에서 설명만 남깁니다.
        name = text.split(" - ", 1)[1] if " - " in text else text
        table.append((number, name.strip()))
    return tuple(table)


def _un_table(edition: str) -> tuple[tuple[str, str], ...]:
    """품목분류 전체(약 1.7MB). 메모리 → 파일 → UN 순서로 찾습니다.

    받기에 실패하면 빈 표를 기억하지 않습니다. 다음 호출에서 다시 시도합니다.
    """

    if edition in _un_tables:
        return _un_tables[edition]
    with _un_lock:                      # 여러 요청이 동시에 1.7MB를 받지 않게 합니다.
        if edition in _un_tables:
            return _un_tables[edition]
        name = f"un_hs/{edition}"
        cached = file_cache.read(name)
        stored = ()
        if cached and isinstance(cached[0], dict):
            stored = tuple((str(code), str(text)) for code, text in cached[0].get("rows") or ()
                           if str(code).isdigit())
        table = stored
        if not stored or cached[1] > UN_REFRESH_DAYS:
            fresh = _download_un_table(edition)
            if fresh:
                file_cache.write(name, {"edition": edition, "source": UN_URL.format(
                    edition=UN_EDITIONS.get(edition, "H6")), "rows": fresh})
                table = fresh
        if table:
            _un_tables[edition] = table
        return table


def _un_names(edition: str) -> dict[str, str]:
    if edition not in _un_name_maps:
        table = _un_table(edition)
        if not table:
            return {}
        _un_name_maps[edition] = dict(table)
    return _un_name_maps[edition]


def heading_names(code: str) -> dict:
    """HSK 끝단 품명("기타", "승용자동차용")만으로는 무슨 물건인지 모릅니다.
    그 세번이 속한 호(4자리)·소호(6자리)의 영문 이름을 돌려줍니다. 못 받으면 빈 값입니다."""

    digits = _digits(code)
    names = _un_names("HS2022")
    return {"heading": names.get(digits[:4], ""), "subheading": names.get(digits[:6], "")}


def search_un(query: str, limit: int = 20, edition: str = "HS2022") -> dict:
    """영문 품명이나 숫자로 HS 6자리를 찾습니다."""

    text = (query or "").strip()
    if len(text) < 2:
        return fail("VALIDATION_ERROR", "api", "두 글자 이상 입력해주세요.")

    table = _un_table(edition)
    if not table:
        return fail("API_CONNECTION_ERROR", "api", "UN 품목분류를 받지 못했습니다.")

    digits = _digits(text)
    lowered = text.lower()
    if digits:
        rows = [(code, name) for code, name in table if code.startswith(digits)]
    else:
        rows = [(code, name) for code, name in table if lowered in name.lower()]

    # 짧은 부호(류·호)를 먼저 보여 줍니다. 큰 갈래부터 좁혀 가는 순서입니다.
    rows.sort(key=lambda row: (len(row[0]), row[0]))
    return ok([{
        "code": code,
        "name_en": name,
        "digits": len(code),
        "level": {2: "류(Chapter)", 4: "호(Heading)", 6: "소호(Subheading)"}.get(
            len(code), f"{len(code)}자리"),
        "source": "un",
    } for code, name in rows[:max(1, limit)]], "api")


# --- 2. 미국 USITC ---------------------------------------------------------------

def search_usitc(query: str, limit: int = 20) -> dict:
    """미국 관세율표에서 찾습니다. 영문 품명으로 잘 찾힙니다."""

    text = (query or "").strip()
    if len(text) < 2:
        return fail("VALIDATION_ERROR", "api", "두 글자 이상 입력해주세요.")

    result = request_text("GET", USITC_URL, params={"keyword": text}, timeout=25)
    if not result["success"]:
        return result
    try:
        rows = json.loads(result["data"])
    except ValueError:
        return fail("API_INVALID_RESPONSE", "api")
    if not isinstance(rows, list):
        rows = rows.get("results", []) if isinstance(rows, dict) else []

    found = []
    for row in rows[:max(1, limit)]:
        number = str(row.get("htsno") or "").strip()
        if not _digits(number):
            continue
        found.append({
            "code": number,
            "hs6": _digits(number)[:6],
            "name_en": str(row.get("description") or "").strip(),
            "source": "usitc",
        })
    return ok(found, "api")


# --- 3. 영국 Trade Tariff --------------------------------------------------------

def search_uk(query: str, limit: int = 20) -> dict:
    """영국 관세율표의 검색 색인에서 찾습니다."""

    text = (query or "").strip().lower()
    if len(text) < 2:
        return fail("VALIDATION_ERROR", "api", "두 글자 이상 입력해주세요.")

    result = request_text("GET", UK_URL, timeout=40,
                          headers={"Accept": "application/json"})
    if not result["success"]:
        return result
    try:
        rows = json.loads(result["data"]).get("data", [])
    except (ValueError, AttributeError):
        return fail("API_INVALID_RESPONSE", "api")

    found = []
    for row in rows:
        attributes = row.get("attributes", {}) if isinstance(row, dict) else {}
        title = str(attributes.get("title") or "")
        if text not in title.lower():
            continue
        code = str(attributes.get("referenced_id") or "")
        found.append({"code": code, "hs6": _digits(code)[:6],
                      "name_en": title, "source": "uk"})
        if len(found) >= max(1, limit):
            break
    return ok(found, "api")


# --- 모아서 쓰기 -----------------------------------------------------------------

def search(query: str, limit: int = 20) -> dict:
    """세 곳을 함께 보고 HS 6자리로 묶어 돌려줍니다.

    관세청이 안 될 때 쓰는 자리라, 한 곳이 실패해도 나머지로 답합니다.
    """

    text = (query or "").strip()
    if len(text) < 2:
        return fail("VALIDATION_ERROR", "api", "두 글자 이상 입력해주세요.")

    merged: dict[str, dict] = {}
    tried, failed = [], []
    for name, call in (("un", search_un), ("usitc", search_usitc), ("uk", search_uk)):
        result = call(text, limit=limit)
        tried.append(name)
        if not result["success"]:
            failed.append({"source": name, "message": result["message"]})
            continue
        for row in result["data"]:
            code = row.get("hs6") or _digits(row["code"])[:6]
            if len(code) < 4:
                continue
            found = merged.setdefault(code, {
                "hs6": code, "names": [], "sources": [], "codes": []})
            if row["name_en"] and row["name_en"] not in found["names"]:
                found["names"].append(row["name_en"])
            if name not in found["sources"]:
                found["sources"].append(name)
            if row["code"] not in found["codes"]:
                found["codes"].append(row["code"])

    # 여러 곳에서 같이 나온 부호를 먼저 보여 줍니다. 더 믿을 만합니다.
    rows = sorted(merged.values(), key=lambda row: (-len(row["sources"]), row["hs6"]))
    return ok({
        "query": text,
        "rows": rows[:max(1, limit)],
        "tried": tried,
        "failed": failed,
        "limit_note": LIMIT_NOTE,
        "sources": SOURCES,
    }, "api")
