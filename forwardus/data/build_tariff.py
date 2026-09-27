"""관세청 품목번호별 관세율표(공공데이터포털)를 내부 세율표로 굳혀 둡니다.

왜 굳히나
  관세율은 **돈이 걸린 값**입니다. 그런데 관세청 UNI-PASS 관세율 조회는
  키가 있어야 하고, 기관이 멈추면 견적에서 관세를 못 냅니다. 게다가 조회로는
  기관에 없는 부호가 있습니다 — 2026-09-27 확인에서 3304.99(화장품)·
  8507.60(리튬이온)·8708.29(자동차부품)가 "조회된 관세율 정보가 없습니다"
  였습니다. 우리나라 수출 상위 품목인데 말입니다.

  포털 파일에는 전 품목이 들어 있습니다. 받아서 굳혀 두면 **키 없이도, 기관이
  멈춰도** 답합니다.

받는 곳 — API 키가 필요 없습니다 (파일을 내려받습니다)
    https://www.data.go.kr/data/15051179/fileData.do
    관세청_품목번호별 관세율표 · 공공누리 제1유형(출처표시) · 연 1회 갱신

    python data/build_tariff.py                 # 포털에서 받아 변환
    python data/build_tariff.py --file 파일.xlsx  # 직접 받은 파일로 변환

결과: data/mock/tariff_rates.json
관세율은 매년 1월 1일 개정되고 조정·할당관세는 수시로 바뀝니다. 포털이 새
기준일 자료를 올리면 다시 돌리세요.

엑셀은 xlsx(압축된 XML)라 표준 라이브러리로만 읽습니다. 줄이 너무 적거나
형식이 다르면 **기존 파일을 건드리지 않고 그대로 멈춥니다.** 조용히 빈 표가
들어가는 것이 가장 위험합니다. (build_hsk.py 와 같은 원칙입니다)
"""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import httpx

DATA_DIR = Path(__file__).resolve().parent
RAW_DIR = DATA_DIR / "raw"
OUT_PATH = DATA_DIR / "mock" / "tariff_rates.json"

PAGE_URL = "https://www.data.go.kr/data/15051179/fileData.do"
META_URL = "https://www.data.go.kr/tcs/dss/selectFileDataDownload.do"
DOWNLOAD_URL = "https://www.data.go.kr/cmm/cmm/fileDownload.do"
PUBLIC_DATA_PK = "15051179"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; FORWARDUS/1.0)"}

# 2026-02-11 자료는 10자리 부호 12,000여 개에 세율 줄이 수십만입니다.
# 이보다 훨씬 적으면 받은 파일이 잘린 것입니다.
MIN_CODES = 10_000
MIN_ROWS = 50_000
HS_LENGTH = 10
# 표의 머리글. 순서가 바뀌어도 이름으로 찾습니다.
NEEDED = ("품목번호", "관세율구분", "관세율", "적용개시일", "적용만료일")
OPTIONAL = ("단위당세액", "기준가격", "적용국가구분", "용도세율구분")
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

# 관세율구분 부호가 무슨 세율인지.
#
# **이름을 우리가 짓지 않습니다.** 아래 목록은 관세청 UNI-PASS 관세율 조회가
# 실제로 돌려준 trrtTpNm 값을 그대로 옮긴 것입니다. (2026-09-27 에 3306100000·
# 1902301010 두 부호로 받아 둔 응답에서 뽑았습니다 — data/cache/snap_tariff_*)
#
# 왜 이름이 있어야 하나
#   fta_guide.countries_for() 가 **이름에서** 나라를 읽어냅니다.
#   ("한ㆍ터키 FTA협정세율(선택1)" → "터키") 이름이 없으면 협정을 못 찾아,
#   원산지증명서 안내가 목록에서 사라집니다. 실제로 그렇게 됐습니다.
RATE_KINDS = {
    "A": "기본세율",
    "C": "WTO협정세율",
    "E1": "아시아ㆍ태평양 협정세율(일반)",
    "FAE1": "한ㆍUAE CEPA(선택1)",
    "FAS1": "한ㆍ아세안 FTA협정세율(선택1)",
    "FAU1": "한ㆍ호주 FTA협정세율(선택1)",
    "FCA1": "한ㆍ캐나다 FTA협정세율(선택1)",
    "FCECR1": "한ㆍ중미 FTA협정세율_코스타리카(선택1)",
    "FCEHN1": "한ㆍ중미 FTA협정세율_온두라스(선택1)",
    "FCENI1": "한ㆍ중미 FTA협정세율_니카라과(선택1)",
    "FCEPA1": "한ㆍ중미 FTA협정세율_파나마(선택1)",
    "FCESV1": "한ㆍ중미 FTA협정세율_엘살바도르(선택1)",
    "FCL1": "한ㆍ칠레FTA협정세율(선택1)",
    "FCN1": "한ㆍ중국 FTA협정세율(선택1)",
    "FCO1": "한ㆍ콜롬비아FTA협정세율(선택1)",
    "FEF1": "한ㆍEFTA FTA협정세율(선택1)",
    "FEU1": "한ㆍEU FTA협정세율(선택1)",
    "FGB1": "한ㆍ영국 FTA협정세율(선택1)",
    "FID1": "한ㆍ인도네시아 CEPA(선택1)",
    "FIL1": "한ㆍ이스라엘 FTA(선택1)",
    "FIN1": "한ㆍ인도 FTA협정세율(선택1)",
    "FKH1": "한ㆍ캄보디아 FTA(선택1)",
    "FNZ1": "한ㆍ뉴질랜드 FTA협정세율(선택1)",
    "FPE1": "한ㆍ페루 FTA협정세율(선택1)",
    "FPH1": "한ㆍ필리핀 FTA(선택1)",
    "FRCAS1": "RCEP협정세율_아세안(선택1)",
    "FRCAU1": "RCEP협정세율_호주(선택1)",
    "FRCCN1": "RCEP협정세율_중국(선택1)",
    "FRCJP1": "RCEP협정세율_일본(선택1)",
    "FRCNZ1": "RCEP협정세율_뉴질랜드(선택1)",
    "FSG1": "한ㆍ싱가포르FTA협정세율(선택1)",
    "FTR1": "한ㆍ터키 FTA협정세율(선택1)",
    "FUS1": "한ㆍ미 FTA 협정세율(선택1)",
    "FVN1": "한ㆍ베트남 FTA협정세율(선택1)",
    "R": "최빈국특혜관세",
    "U": "북한산",
}

# 뒤 숫자만 다른 것은 **같은 협정의 다른 선택**입니다. (FTR1 · FTR2 · FTR3 …)
# 관세청 이름도 "(선택1)" 자리만 바뀌므로, 줄기가 같은 이름을 찾아 번호만
# 갈아 끼웁니다. 줄기를 모르는 부호는 부호 그대로 보여 줍니다.
_CHOICE = re.compile(r"\(선택\d+\)\s*$")


def rate_kind_name(kind: str) -> str:
    """세율구분 부호의 이름. 모르면 부호 그대로 돌려줍니다."""

    if kind in RATE_KINDS:
        return RATE_KINDS[kind]
    stem = re.sub(r"\d+$", "", kind)
    tail = kind[len(stem):]
    if not stem or not tail:
        return kind
    for number in ("1", "2", "3", ""):
        base = RATE_KINDS.get(stem + number)
        if base:
            return _CHOICE.sub(f"(선택{tail})", base) if _CHOICE.search(base)                 else f"{base}(선택{tail})"
    return kind


def download() -> tuple[Path, str]:
    """포털에서 받습니다. (저장한 파일, 자료 이름) — API 키를 쓰지 않습니다."""

    meta = httpx.get(META_URL, params={"publicDataPk": PUBLIC_DATA_PK, "fileDetailSn": "1",
                                       "dataNm": ""}, headers=HEADERS, timeout=60).json()
    atch = meta.get("atchFileId")
    name = (meta.get("dataSetFileDetailInfo") or {}).get("dataNm", "")
    if not atch:
        raise SystemExit("포털에서 파일 번호를 받지 못했습니다. 페이지에서 직접 받아 --file 로 넘겨주세요.\n"
                         f"  {PAGE_URL}")
    response = httpx.get(DOWNLOAD_URL,
                         params={"atchFileId": atch, "fileDetailSn": meta.get("fileDetailSn", 1)},
                         headers=HEADERS, timeout=300, follow_redirects=True)
    response.raise_for_status()
    if not response.content.startswith(b"PK"):
        raise SystemExit("받은 파일이 xlsx가 아닙니다. (보안문자 확인이 걸렸을 수 있습니다) "
                         f"페이지에서 직접 받아 --file 로 넘겨주세요.\n  {PAGE_URL}")
    stamp = base_date(name) or "unknown"
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    path = RAW_DIR / f"tariff_rates_{stamp.replace('-', '')}.xlsx"
    path.write_bytes(response.content)
    return path, name


def base_date(name: str) -> str:
    """자료 이름 끝의 8자리를 기준일로 읽습니다. ("..._20260211" → 2026-02-11)"""

    found = re.search(r"(\d{4})(\d{2})(\d{2})\s*$", name.strip())
    return "-".join(found.groups()) if found else ""


def read_rows(path: Path) -> list[list[str]]:
    """xlsx 첫 시트를 [[칸, 칸, ...], ...] 로 읽습니다. 표준 라이브러리만 씁니다."""

    import xml.etree.ElementTree as ET

    with zipfile.ZipFile(path) as book:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in book.namelist():
            root = ET.fromstring(book.read("xl/sharedStrings.xml"))
            for item in root.findall(f"{NS}si"):
                shared.append("".join(node.text or "" for node in item.iter(f"{NS}t")))

        sheets = sorted(n for n in book.namelist()
                        if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n))
        if not sheets:
            raise SystemExit("엑셀 안에 시트가 없습니다.")
        rows: list[list[str]] = []
        root = ET.fromstring(book.read(sheets[0]))
        for line in root.iter(f"{NS}row"):
            cells: list[str] = []
            for cell in line.findall(f"{NS}c"):
                value = cell.find(f"{NS}v")
                text = value.text if value is not None else None
                if cell.get("t") == "s" and text is not None:
                    index = int(text)
                    text = shared[index] if 0 <= index < len(shared) else ""
                elif cell.get("t") == "inlineStr":
                    node = cell.find(f"{NS}is")
                    text = "".join(part.text or "" for part in node.iter(f"{NS}t")) if node else ""
                cells.append((text or "").strip())
            rows.append(cells)
    return rows


def convert(rows: list[list[str]]) -> dict:
    """머리글로 칸 자리를 찾아 품목번호별 세율 목록으로 바꿉니다."""

    header = next((line for line in rows if "품목번호" in line), None)
    if header is None:
        raise SystemExit("표에서 '품목번호' 머리글을 찾지 못했습니다. 서식이 바뀐 것 같습니다.")
    where = {name: index for index, name in enumerate(header) if name}
    missing = [name for name in NEEDED if name not in where]
    if missing:
        raise SystemExit(f"표에 없는 칸이 있습니다: {missing}. 서식이 바뀐 것 같습니다.")

    def cell(line: list[str], name: str) -> str:
        index = where.get(name)
        return line[index].strip() if index is not None and index < len(line) else ""

    # 압축해서 담습니다.
    #
    # 줄마다 dict 를 두면 55MB 가 됩니다. 11,326 부호 × 세율 33종이고, 그 가운데
    # 대부분이 FTA 협정세율(FUS1 한-미 · FEU1 한-EU · FCN1 한-중 …)입니다.
    # 값은 거의 다 세율 하나뿐이고 적용기간도 20260101~20261231 로 같습니다.
    # 그래서 **부호마다 {세율구분: 세율}** 로만 담고, 기간이나 단위당세액이
    # 기본과 다른 것만 따로 적습니다. (1/10 이하로 줄어듭니다)
    by_code: dict[str, dict[str, str]] = defaultdict(dict)
    odd: dict[str, dict[str, dict]] = defaultdict(dict)
    period = Counter()
    counted = 0
    lines = rows[rows.index(header) + 1:]

    for line in lines:
        start, end = cell(line, "적용개시일"), cell(line, "적용만료일")
        if start and end:
            period[(start, end)] += 1
    common = period.most_common(1)[0][0] if period else ("", "")

    for line in lines:
        code = re.sub(r"\D", "", cell(line, "품목번호"))
        if len(code) != HS_LENGTH:
            continue
        kind = cell(line, "관세율구분")
        rate, unit = cell(line, "관세율"), cell(line, "단위당세액")
        if not kind or not (rate or unit):
            continue          # 값이 아무것도 없는 줄은 버립니다.
        by_code[code][kind] = rate
        extra = {}
        start, end = cell(line, "적용개시일"), cell(line, "적용만료일")
        if (start, end) != common:
            extra["start_date"], extra["end_date"] = start, end
        if unit:
            extra["unit_amount"] = unit
        if cell(line, "용도세율구분"):
            extra["use"] = cell(line, "용도세율구분")
        if extra:
            odd[code][kind] = extra
        counted += 1
    return {"codes": {code: kinds for code, kinds in sorted(by_code.items())},
            "extra": {code: kinds for code, kinds in sorted(odd.items())},
            "period": list(common), "rows": counted}


def check(table: dict) -> None:
    """적으면 멈춥니다. 조용히 빈 표가 들어가는 것이 가장 위험합니다."""

    codes, rows = table["codes"], table["rows"]
    if len(codes) < MIN_CODES:
        raise SystemExit(f"품목번호가 {len(codes):,}개뿐입니다. {MIN_CODES:,}개 이상이어야 합니다. "
                         "받은 파일이 잘렸거나 서식이 바뀐 것 같습니다. 기존 파일은 그대로 둡니다.")
    if rows < MIN_ROWS:
        raise SystemExit(f"세율 줄이 {rows:,}개뿐입니다. {MIN_ROWS:,}개 이상이어야 합니다. "
                         "기존 파일은 그대로 둡니다.")
    # 기본세율(A)이 거의 모든 부호에 있어야 합니다. 없으면 엉뚱한 칸을 읽은 것입니다.
    with_basic = sum(1 for kinds in codes.values() if "A" in kinds)
    if with_basic < len(codes) * 0.9:
        raise SystemExit(f"기본세율(A)이 있는 부호가 {with_basic:,}/{len(codes):,} 뿐입니다. "
                         "'관세율구분' 칸을 잘못 읽은 것 같습니다. 기존 파일은 그대로 둡니다.")


def main() -> None:
    parser = argparse.ArgumentParser(description="관세청 품목번호별 관세율표를 내부 표로 굳힙니다.")
    parser.add_argument("--file", help="직접 받은 xlsx 파일 경로")
    args = parser.parse_args()

    if args.file:
        path, name = Path(args.file), Path(args.file).stem
    else:
        path, name = download()
    print(f"■ 읽는 파일 {path} ({path.stat().st_size:,}바이트)")

    table = convert(read_rows(path))
    check(table)

    stamp = base_date(name)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps({
        "source": "관세청 품목번호별 관세율표 (공공데이터포털)",
        "url": PAGE_URL,
        "license": "공공누리 제1유형(출처표시)",
        "base_date": stamp,
        "built_on": date.today().isoformat(),
        "count": len(table["codes"]),
        "rows": table["rows"],
        # 표에 실제로 나온 구분만 담습니다. 이름을 모르는 것은 담지 않습니다
        # (읽는 쪽이 부호 그대로 보여 줍니다).
        "rate_kinds": {kind: rate_kind_name(kind) for kind in sorted(
            {k for kinds in table["codes"].values() for k in kinds})
            if rate_kind_name(kind) != kind},
        # 거의 모든 줄이 같은 적용기간입니다. 한 번만 적고, 다른 것만 extra 에 둡니다.
        "period": table["period"],
        "codes": table["codes"],
        "extra": table["extra"],
    }, ensure_ascii=False), encoding="utf-8")

    print(f"■ 굳혔습니다 · 품목번호 {len(table['codes']):,}개 · 세율 줄 {table['rows']:,}개")
    print(f"   기준일 {stamp or '알 수 없음'} → {OUT_PATH} "
          f"({OUT_PATH.stat().st_size:,}바이트)")


if __name__ == "__main__":
    main()
