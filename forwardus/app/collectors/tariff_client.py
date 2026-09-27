"""도착국 기준 관세율 조회.

한국 관세청 세율은 "한국으로 수입할 때" 기준이라, 수출 상대국이 실제로 매기는
관세는 그 나라 자료에서 봐야 합니다. 키 없이 동작이 확인된 세 곳을 씁니다.

- 세계은행 WITS(UNCTAD TRAINS): 거의 모든 나라의 HS 6단위 적용세율.
  MFN(최혜국)과 한국산 특혜세율을 따로 줍니다. 값은 6단위 안 세부 라인의
  단순평균이라 최소·최대를 함께 보여줍니다. SDMX-REST XML 경로만 빠릅니다
  (URL형·JSON은 25초 넘게 걸립니다).
- 미국 USITC HTS: 미국 세분 부호(8~10자리)와 일반·특별(FTA)세율.
- 영국 Trade Tariff: 영국 10자리 부호와 제3국·한국 특혜세율.
- 일본 세관 실행관세율표: JSON API는 없지만 류(chapter)별 HTML 표가 규칙적이라
  9자리 통계부호·기본세율·WTO세율·한국(RCEP)세율을 읽어 옵니다.

EU TARIC은 HTML 조회 화면뿐이라 부호를 넣은 링크로 안내합니다.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from app.collectors import file_cache
from app.collectors.base_client import fail, ok, request_text

# WITS(UNCTAD TRAINS) 세율은 1년 단위 자료입니다.
WITS_REFRESH_DAYS = 90

WITS_URL = ("https://wits.worldbank.org/API/V1/SDMX/V21/rest/data/DF_WITS_Tariff_TRAINS/"
            "A.{reporter}.{partner}.{hs6}.reported/")
USITC_URL = "https://hts.usitc.gov/reststop/exportList"
UK_URL = "https://www.trade-tariff.service.gov.uk/api/v2/commodities/{code}"
UK_HEADING_URL = "https://www.trade-tariff.service.gov.uk/api/v2/headings/{heading}"
JAPAN_INDEX_URL = "https://www.customs.go.jp/english/tariff/index.htm"
JAPAN_CHAPTER_URL = "https://www.customs.go.jp/english/tariff/{edition}/data/e_{chapter}.htm"
# 일본 세관은 User-Agent가 없으면 거부합니다.
BROWSER_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; FORWARDUS/1.0)"}

WORLD = "000"       # WITS에서 "모든 나라" (MFN)
KOREA = "410"       # 한국의 UN 숫자코드 (특혜세율 조회용)
EU_REPORTER = "918"  # EU는 공동관세라 회원국이 아니라 EU 하나로 보고합니다

_ISO_PATH = Path(__file__).resolve().parents[2] / "data" / "raw" / "iso_3166_regions.json"

# 나라별 공식 관세율표 조회 페이지. 부호를 넣어 바로 열 수 있게 합니다.
LOOKUP_PAGES = {
    "EU": ("EU TARIC", "https://ec.europa.eu/taxation_customs/dds2/taric/measures.jsp"
                       "?Lang=en&Taric={hs6}&Area=KR"),
    "US": ("미국 USITC HTS", "https://hts.usitc.gov/search?query={hs6}"),
    "GB": ("영국 Trade Tariff", "https://www.trade-tariff.service.gov.uk/search?q={hs6}"),
    "JP": ("일본 세관 실행관세율표", JAPAN_INDEX_URL),
    "AU": ("호주 국경청 Working Tariff",
           "https://www.abf.gov.au/importing-exporting-and-manufacturing/tariff-classification/current-tariff/schedule-3"),
    "CN": ("중국 해관 세율 조회", "http://www.customs.gov.cn/"),
    "*": ("세계은행 WITS", "https://wits.worldbank.org/tariff/trains/en/country/{iso3}/product/{hs6}"),
}


@lru_cache(maxsize=1)
def _m49() -> dict[str, str]:
    """ISO 2자리 국가코드 → UN 숫자코드(M49). WITS는 숫자코드만 받습니다."""

    try:
        rows = json.loads(_ISO_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {row["alpha-2"]: str(int(row["country-code"])) for row in rows if row.get("country-code")}


@lru_cache(maxsize=1)
def _iso3() -> dict[str, str]:
    """ISO 2자리 → 3자리. WITS 웹 조회 페이지 링크에 씁니다."""

    try:
        rows = json.loads(_ISO_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {row["alpha-2"]: row["alpha-3"] for row in rows if row.get("alpha-3")}


def lookup_page(country_code: str, hs6: str, eu_members: tuple[str, ...] = ()) -> dict:
    """도착국 공식 관세율표를 바로 열 수 있는 링크."""

    code = (country_code or "").strip().upper()
    key = "EU" if code in eu_members else code
    label, url = LOOKUP_PAGES.get(key) or LOOKUP_PAGES["*"]
    return {"label": label, "url": url.format(hs6=hs6, iso3=_iso3().get(code, code))}


def reporter_for(country_code: str, eu_members: tuple[str, ...] = ()) -> str:
    """도착국의 WITS 보고자 코드. EU 회원국은 EU(918)로 묶입니다."""

    code = (country_code or "").strip().upper()
    if code in eu_members:
        return EU_REPORTER
    return _m49().get(code, "")


def _parse_wits(xml: str) -> dict | None:
    """SDMX generic XML에서 가장 최근 연도의 관측값 하나를 꺼냅니다."""

    def rate_of(text: str | None) -> float | None:
        # WITS는 세율을 32비트 실수로 줍니다. (1.7 → "1.70000004768372")
        # 그대로 보여주면 잘못된 정밀도로 읽히므로 소수 둘째 자리에서 끊습니다.
        try:
            return round(float(text), 2)
        except (TypeError, ValueError):
            return None

    latest = None
    for obs in re.findall(r"<generic:Obs>.*?</generic:Obs>", xml, re.S):
        year = re.search(r'ObsDimension[^>]*value="(\d{4})"', obs)
        value = re.search(r'ObsValue[^>]*value="([^"]+)"', obs)
        if not year or value is None or rate_of(value.group(1)) is None:
            continue
        attrs = dict(re.findall(r'<generic:Value id="(\w+)" value="([^"]*)"', obs))
        try:
            lines = int(attrs.get("TOTALNOOFLINES") or 0)
        except ValueError:
            lines = 0
        row = {
            "year": int(year.group(1)),
            "rate": rate_of(value.group(1)),
            "min": rate_of(attrs.get("MIN_RATE")),
            "max": rate_of(attrs.get("MAX_RATE")),
            "lines": lines,
            "type": attrs.get("TARIFFTYPE", ""),
        }
        if latest is None or row["year"] > latest["year"]:
            latest = row
    return latest


def fetch_wits(reporter: str, partner: str, hs6: str, *, timeout: float = 30) -> dict:
    """도착국(reporter)이 partner산 물품에 매기는 HS6 세율. 최근 연도 값.

    WITS 세율은 1년에 한 번 갱신되므로 받은 값을 파일에 두고 WITS_REFRESH_DAYS 동안
    다시 씁니다. 기한이 지나 새로 받지 못하면 예전 값을 씁니다(source="cache").
    실패(시간 초과 등)는 저장하지 않아 다음 호출에서 다시 시도합니다.
    """

    if not reporter or len(hs6) != 6 or not hs6.isdigit():
        return fail("VALIDATION_ERROR", "api", "국가코드와 HS 6자리가 필요합니다.")
    name = f"wits/{reporter}_{partner}_{hs6}"
    cached = file_cache.read(name)
    if cached and cached[1] <= WITS_REFRESH_DAYS:
        return ok(cached[0], "api")
    result = request_text("GET", WITS_URL.format(reporter=reporter, partner=partner, hs6=hs6),
                          timeout=timeout)
    if result["success"]:
        row = _parse_wits(result["data"])
    elif result.get("error_code") == "API_NOT_FOUND":
        # 자료가 없으면 404가 옵니다. 오류가 아니라 "없음"으로 돌려줍니다.
        row = None
    elif cached:
        return ok(cached[0], "cache")
    else:
        return result
    file_cache.write(name, row)
    return ok(row, "api")


def fetch_us_hts(hs_prefix: str) -> dict:
    """미국 HTS 세분 부호. 4자리 헤딩(예: 3304)의 모든 라인을 받습니다.

    `to`는 그 헤딩의 하위를 포함하지 않아 다음 헤딩까지 범위를 넓혀 받고,
    `styles` 파라미터가 없으면 400이 옵니다.
    """

    heading = (hs_prefix or "")[:4]
    if len(heading) != 4 or not heading.isdigit():
        return fail("VALIDATION_ERROR", "api", "HS 4자리 이상이 필요합니다.")
    next_heading = f"{int(heading) + 1:04d}"
    result = request_text("GET", USITC_URL, params={
        "from": heading, "to": next_heading, "format": "JSON", "styles": "false"}, timeout=30)
    if not result["success"]:
        return result
    try:
        rows = json.loads(result["data"])
    except ValueError:
        return fail("API_INVALID_RESPONSE", "api")
    lines = [{
        "code": row.get("htsno", ""),
        "indent": int(row.get("indent") or 0),
        "description": (row.get("description") or "").strip(),
        "general": (row.get("general") or "").strip(),
        "special": (row.get("special") or "").strip(),
        "other": (row.get("other") or "").strip(),
        "units": row.get("units") or [],
    } for row in rows if isinstance(row, dict)]
    return ok(lines, "api")


def fetch_uk_heading(hs4: str) -> dict:
    """영국 4자리 헤딩 아래의 10자리 부호 목록과 제3국 세율."""

    heading = re.sub(r"\D", "", hs4 or "")[:4]
    if len(heading) != 4:
        return fail("VALIDATION_ERROR", "api", "HS 4자리 이상이 필요합니다.")
    result = request_text("GET", UK_HEADING_URL.format(heading=heading), timeout=30)
    if not result["success"]:
        return result
    try:
        payload = json.loads(result["data"])
    except ValueError:
        return fail("API_INVALID_RESPONSE", "api")

    included = {(item["type"], item["id"]): item for item in payload.get("included", [])}

    def duty(measure_id: str) -> str:
        measure = included.get(("measure", measure_id), {})
        if (measure.get("relationships", {}).get("measure_type", {}).get("data") or {}).get("id") != "103":
            return ""
        duty_id = (measure["relationships"].get("duty_expression", {}).get("data") or {}).get("id")
        base = included.get(("duty_expression", duty_id), {}).get("attributes", {}).get("base", "")
        return re.sub(r"<[^>]+>", "", base).strip()

    lines = []
    for item in payload.get("included", []):
        if item.get("type") != "commodity":
            continue
        attrs = item["attributes"]
        measures = (item.get("relationships", {}).get("overview_measures", {}).get("data") or [])
        third_country = next((text for text in (duty(m["id"]) for m in measures) if text), "")
        lines.append({
            "code": attrs.get("goods_nomenclature_item_id", ""),
            "indent": int(attrs.get("number_indents") or 0),
            "leaf": bool(attrs.get("leaf")),
            "description": re.sub(r"<[^>]+>", "", attrs.get("formatted_description", "")).strip(),
            "general": third_country,
        })
    return ok(lines, "api")


def fetch_uk_tariff(code10: str) -> dict:
    """영국 10자리 부호의 세율. 한국산에 적용되는 특혜세율을 함께 줍니다."""

    digits = re.sub(r"\D", "", code10 or "")
    if len(digits) != 10:
        return fail("VALIDATION_ERROR", "api", "영국 부호는 10자리입니다.")
    result = request_text("GET", UK_URL.format(code=digits),
                          params={"filter[geographical_area_id]": "KR"}, timeout=30)
    if not result["success"]:
        return result
    try:
        payload = json.loads(result["data"])
    except ValueError:
        return fail("API_INVALID_RESPONSE", "api")

    included = {(item["type"], item["id"]): item for item in payload.get("included", [])}
    measures = []
    for item in payload.get("included", []):
        if item.get("type") != "measure":
            continue
        rel = item.get("relationships", {})
        kind = (rel.get("measure_type", {}).get("data") or {}).get("id")
        duty = (rel.get("duty_expression", {}).get("data") or {}).get("id")
        area = (rel.get("geographical_area", {}).get("data") or {}).get("id", "")
        kind_name = included.get(("measure_type", kind), {}).get("attributes", {}).get("description", "")
        rate = included.get(("duty_expression", duty), {}).get("attributes", {}).get("base", "")
        if kind_name and rate:
            measures.append({"type": kind_name, "rate": re.sub(r"<[^>]+>", "", rate).strip(),
                             "area": area})
    attributes = payload.get("data", {}).get("attributes", {})
    return ok({
        "code": attributes.get("goods_nomenclature_item_id", digits),
        "description": re.sub(r"<[^>]+>", "", attributes.get("formatted_description", "")).strip(),
        "measures": measures,
    }, "api")


# --- 일본 --------------------------------------------------------------------

def _clean(text: str) -> str:
    text = re.sub(r"<br\s*/?>", " ", text)
    text = re.sub(r"<[^>]+>", "", text).replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", text).strip()


@lru_cache(maxsize=1)
def japan_edition() -> str:
    """가장 최근 실행관세율표 판(예: "2026_08_08"). 목차 페이지의 링크에서 고릅니다."""

    result = request_text("GET", JAPAN_INDEX_URL, headers=BROWSER_HEADERS, timeout=30)
    if not result["success"]:
        return ""
    editions = re.findall(r"/english/tariff/(\d{4}_\d{2}_\d{2})/index\.htm", result["data"])
    return max(editions) if editions else ""


@lru_cache(maxsize=32)
def _japan_chapter(edition: str, chapter: str) -> dict:
    """류 하나의 표 전체를 받아 행 목록으로 바꿉니다. 같은 류는 다시 받지 않습니다."""

    result = request_text("GET", JAPAN_CHAPTER_URL.format(edition=edition, chapter=chapter),
                          headers=BROWSER_HEADERS, timeout=30)
    if not result["success"]:
        return result
    html = result["data"]
    table = re.search(r'<table id="datatable">(.*?)</table>', html, re.S)
    if not table:
        return fail("API_INVALID_RESPONSE", "api")
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table.group(1), re.S)
    if len(rows) < 3:
        return fail("API_INVALID_RESPONSE", "api")

    # 둘째 머리글 행: H.S.code · (통계) · General · Temporary · WTO · GSP · LDC · EPA들 · 단위 I·II
    # 자료 행은 여기에 Description(3번째)과 Law(마지막)가 끼어 있어 한 칸씩 밀립니다.
    header = [_clean(cell) for cell in re.findall(r"<th[^>]*>(.*?)</th>", rows[1], re.S)]
    columns = {name: index + 1 for index, name in enumerate(header)}

    def column(*names: str) -> int | None:
        return next((columns[name] for name in names if name in columns), None)

    wanted = {
        "general": column("General"),
        "temporary": column("Temporary"),
        "wto": column("WTO"),
        "korea": column("Korea (RCEP)", "Korea(RCEP)"),
        "unit": column("I"),
    }
    lines, current = [], ""
    for row in rows[2:]:
        cells = [_clean(cell) for cell in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if len(cells) < 4:
            continue
        current = cells[0] or current            # 부호는 첫 행에만 적히고 아래로 이어집니다.
        lines.append({
            "hs": current, "stat": cells[1], "description": cells[2],
            **{key: (cells[index] if index is not None and index < len(cells) else "")
               for key, index in wanted.items()},
        })
    return ok(lines, "api")


def fetch_japan_tariff(hs_prefix: str) -> dict:
    """일본 실행관세율표에서 HS 4자리(또는 6자리) 아래의 9자리 통계부호와 세율."""

    digits = re.sub(r"\D", "", hs_prefix or "")
    if len(digits) < 4:
        return fail("VALIDATION_ERROR", "api", "HS 4자리 이상이 필요합니다.")
    edition = japan_edition()
    if not edition:
        return fail("API_CONNECTION_ERROR", "api", "일본 세관 관세율표 목차를 받지 못했습니다.")
    result = _japan_chapter(edition, digits[:2])
    if not result["success"]:
        return result

    prefix = digits[:6]
    lines = []
    for row in result["data"]:
        hs = row["hs"].replace(".", "")
        # 헤딩 행(33.04)은 물품이 그 아래일 때, 소호 행(3304.99)은 앞자리가 같을 때 남깁니다.
        if not (hs.startswith(prefix) or (hs and prefix.startswith(hs))):
            continue
        code = f"{hs[:4]}.{hs[4:6]}" + (f"-{row['stat']}" if row["stat"] else "")
        lines.append({**row, "code": code if len(hs) >= 6 else row["hs"]})
    return ok({"edition": edition.replace("_", "-"), "lines": lines}, "api")
