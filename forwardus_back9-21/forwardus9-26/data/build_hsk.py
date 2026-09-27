"""관세청 HS부호 단위별 품목명(공공데이터포털)을 내부 품목표로 굳혀 둡니다.

관세청 HS부호검색 API가 멈춰도 HSK 10자리를 찾고, AI가 낸 부호가 실제로
있는지 확인하는 데 씁니다. 받는 곳:

    https://www.data.go.kr/data/15130660/fileData.do
    공공누리 제1유형(출처표시) · 관세청

    python data/build_hsk.py                 # 포털에서 받아 변환
    python data/build_hsk.py --file 파일.xlsx  # 직접 받은 파일로 변환

결과: data/mock/hsk_codes.json
HSK는 매년 1월 1일 개정됩니다. 관세청이 새 기준일 자료를 올리면 다시 돌리세요.
(HS2027은 2027-01-01 시행이라 그때는 반드시 다시 받아야 합니다.)

엑셀은 xlsx(압축된 XML)라 표준 라이브러리로만 읽습니다. 10자리가 너무 적거나
형식이 다르면 기존 파일을 건드리지 않고 그대로 멈춥니다. 조용히 빈 목록이
들어가는 것이 가장 위험합니다.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx

DATA_DIR = Path(__file__).resolve().parent
RAW_DIR = DATA_DIR / "raw"
OUT_PATH = DATA_DIR / "mock" / "hsk_codes.json"

PAGE_URL = "https://www.data.go.kr/data/15130660/fileData.do"
META_URL = "https://www.data.go.kr/tcs/dss/selectFileDataDownload.do"
DOWNLOAD_URL = "https://www.data.go.kr/cmm/cmm/fileDownload.do"
PUBLIC_DATA_PK = "15130660"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; FORWARDUS/1.0)"}

MIN_CODES = 10_000          # 2026-01-01 자료는 11,327개입니다.
SHEET_HEADER = "HS10단위"
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def download() -> tuple[Path, str]:
    """포털에서 받습니다. (저장한 파일, 자료 이름)"""

    meta = httpx.get(META_URL, params={"publicDataPk": PUBLIC_DATA_PK, "fileDetailSn": "1",
                                       "dataNm": ""}, headers=HEADERS, timeout=60).json()
    atch, name = meta.get("atchFileId"), (meta.get("dataSetFileDetailInfo") or {}).get("dataNm", "")
    if not atch:
        raise SystemExit("포털에서 파일 번호를 받지 못했습니다. 페이지에서 직접 받아 --file 로 넘겨주세요.\n"
                         f"  {PAGE_URL}")
    response = httpx.get(DOWNLOAD_URL, params={"atchFileId": atch, "fileDetailSn": meta.get("fileDetailSn", 1)},
                         headers=HEADERS, timeout=120, follow_redirects=True)
    response.raise_for_status()
    if not response.content.startswith(b"PK"):
        raise SystemExit("받은 파일이 xlsx가 아닙니다. (보안문자 확인이 걸렸을 수 있습니다) "
                         f"페이지에서 직접 받아 --file 로 넘겨주세요.\n  {PAGE_URL}")
    date = base_date(name) or "unknown"
    path = RAW_DIR / f"hsk_names_{date.replace('-', '')}.xlsx"
    path.write_bytes(response.content)
    return path, name


def base_date(name: str) -> str:
    """"관세청_HS부호 단위별 품목명_20260101" → "2026-01-01"."""

    match = re.search(r"(20\d{2})(\d{2})(\d{2})", name or "")
    return f"{match[1]}-{match[2]}-{match[3]}" if match else ""


def read_sheets(path: Path) -> list[list[list[str]]]:
    """시트마다 [행[칸]]. 칸은 A·B·C 세 개(부호·한글품목명·영문품목명)입니다."""

    with zipfile.ZipFile(path) as book:
        shared = ["".join(t.text or "" for t in item.iter(NS + "t"))
                  for item in ET.fromstring(book.read("xl/sharedStrings.xml")).findall(NS + "si")]
        names = sorted((n for n in book.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)),
                       key=lambda n: int(re.search(r"\d+", n.rsplit("/", 1)[1])[0]))
        sheets = []
        for name in names:
            rows = []
            for row in ET.fromstring(book.read(name)).iter(NS + "row"):
                cells = {}
                for cell in row.findall(NS + "c"):
                    value = cell.find(NS + "v")
                    if value is None:
                        text = "".join(t.text or "" for t in cell.iter(NS + "t"))
                    elif cell.get("t") == "s":
                        text = shared[int(value.text)]
                    else:
                        text = value.text or ""
                    cells[re.sub(r"\d", "", cell.get("r", ""))] = text.replace("\xa0", " ").strip()
                rows.append([cells.get(col, "") for col in "ABC"])
            sheets.append(rows)
    return sheets


def convert(sheets: list[list[list[str]]]) -> tuple[dict, dict]:
    """(상위 단위 {부호: [한글, 영문]}, 10자리 {부호: [한글, 영문]})"""

    levels, codes = {}, {}
    for rows in sheets:
        if not rows or not rows[0][0].startswith("HS"):
            raise SystemExit(f"시트 머리글이 예상과 다릅니다: {rows[0] if rows else '빈 시트'}")
        target = codes if rows[0][0] == SHEET_HEADER else levels
        for code, korean, english in rows[1:]:
            if not code:
                continue
            if not code.isdigit():
                raise SystemExit(f"숫자가 아닌 부호가 있습니다: {code!r}")
            if target is codes and len(code) != 10:
                raise SystemExit(f"10단위 시트에 {len(code)}자리 부호가 있습니다: {code}")
            target[code] = [korean, english]
    return levels, codes


def check(levels: dict, codes: dict) -> None:
    """형식이 바뀌어 반쯤 빈 자료가 들어가는 것을 막습니다."""

    if len(codes) < MIN_CODES:
        raise SystemExit(f"10자리 부호가 {len(codes)}개뿐입니다. (최소 {MIN_CODES}개) 자료를 확인해주세요.")
    unnamed = [code for code, (korean, _) in codes.items() if not korean]
    if len(unnamed) > len(codes) * 0.01:
        raise SystemExit(f"한글품목명이 빈 부호가 {len(unnamed)}개입니다. 자료를 확인해주세요.")
    # 6단위 시트에는 아래로 더 나뉘는 소호만 있습니다. (0101.30 당나귀는 10단위 한 줄뿐)
    # 그래서 4단위 호만 반드시 있어야 합니다.
    orphans = [code for code in codes if code[:4] not in levels]
    if len(orphans) > len(codes) * 0.01:
        raise SystemExit(f"호(4단위) 이름이 없는 부호가 {len(orphans)}개입니다. 예: {orphans[:5]}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--file", type=Path, help="포털에서 직접 받은 xlsx 파일")
    parser.add_argument("--date", help="자료 기준일 (예: 2026-01-01). 파일 이름에 있으면 생략")
    args = parser.parse_args()

    if args.file:
        path, name = args.file, args.file.name
    else:
        path, name = download()
    date = args.date or base_date(name)
    if not date:
        raise SystemExit("자료 기준일을 알 수 없습니다. --date 2026-01-01 처럼 넘겨주세요.")

    levels, codes = convert(read_sheets(path))
    check(levels, codes)

    payload = {
        "source": "관세청_HS부호 단위별 품목명",
        "provider": "관세청",
        "license": "공공누리 제1유형(출처표시)",
        "url": PAGE_URL,
        "base_date": date,
        "note": "HSK 10자리 한글·영문 품목명. 신고 전 관세청 최신 품목분류를 확인하세요.",
        "levels": levels,
        "codes": codes,
    }
    temp = OUT_PATH.with_suffix(".json.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(temp, OUT_PATH)

    print(OUT_PATH)
    print(f"  기준일 {date} · 10자리 {len(codes):,}개 · 상위 단위 {len(levels):,}개")


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUTF8", "1")
    sys.stdout.reconfigure(encoding="utf-8")
    main()
