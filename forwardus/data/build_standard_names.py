"""관세청 표준품명(공공데이터포털)을 내부 표로 굳혀 둡니다.

표준품명이 무엇인가
  신고서에 적는 **정식 품명**입니다. 관세청이 신고 정확도를 높이려고 HS부호마다
  정해 둔 이름이고, 품목표의 계층형 이름과 달리 구체적입니다.
    품목표     "그 밖의 식용 어류 설육(건조한 것, 염장이나 염수장한 것, …)"
    표준품명   "북어(통북어)" · "건대구(두절대구)" · "건대구(통대구)"
  사람이 실제로 적는 말에 훨씬 가깝습니다.

무엇에 쓰나 — 찾기 결과의 순위
  일상어를 넣었을 때 **정식 품명을 1순위**로 올리고, 같은 부호에 묶인 형제
  표준품명을 그다음에, 다른 부호의 표준품명을 뒤에 붙입니다. 형제 이름이
  보이면 "내 물건이 정말 이 부호인가"를 스스로 확인할 수 있습니다.
  ("신선마늘(육쪽)" 옆에 "신선마늘(다쪽)"이 보이는 식입니다)
  (2026-09-27 사용자 결정: 형제 먼저, 다른 호를 뒤에)

받는 곳 — API 키가 필요 없습니다 (파일을 내려받습니다)
    https://www.data.go.kr/data/15049721/fileData.do
    관세청_표준품명 · 공공누리 제1유형(출처표시) · 연 1회 갱신

    python data/build_standard_names.py                 # 포털에서 받아 변환
    python data/build_standard_names.py --file 파일.xlsx  # 직접 받은 파일로

결과: data/mock/standard_names.json

엑셀 줄 수(26,873)와 품명 수는 다릅니다. 한 품명에 규격이 여러 줄 붙어 있어
줄 수가 부풀려져 있습니다. 실제 품명은 2,600여 개, 부호는 1,100여 개입니다.

줄이 너무 적거나 머리글이 다르면 **기존 파일을 건드리지 않고 멈춥니다.**
조용히 빈 표가 들어가는 것이 가장 위험합니다. (build_hsk.py 와 같은 원칙)
"""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from datetime import date
from pathlib import Path

import httpx

DATA_DIR = Path(__file__).resolve().parent
RAW_DIR = DATA_DIR / "raw"
OUT_PATH = DATA_DIR / "mock" / "standard_names.json"

PAGE_URL = "https://www.data.go.kr/data/15049721/fileData.do"
META_URL = "https://www.data.go.kr/tcs/dss/selectFileDataDownload.do"
DOWNLOAD_URL = "https://www.data.go.kr/cmm/cmm/fileDownload.do"
PUBLIC_DATA_PK = "15049721"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; FORWARDUS/1.0)"}

# 2026-01-01 자료는 품명 2,647개 · 부호 1,139개입니다. 크게 적으면 잘린 것입니다.
MIN_NAMES = 2_000
MIN_CODES = 900
HS_LENGTH = 10
NEEDED = ("HS부호", "표준품명_한글", "품명")
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

# 이름값을 못 하는 품명. 이것만 있는 부호는 "기타"라 찾기에 도움이 안 됩니다.
GENERIC = {"기타", "그 밖의 것", "기타의 것", "Other"}


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
    path = RAW_DIR / f"std_names_{stamp.replace('-', '')}.xlsx"
    path.write_bytes(response.content)
    return path, name


def base_date(name: str) -> str:
    found = re.search(r"(\d{4})(\d{2})(\d{2})\s*$", (name or "").strip())
    return "-".join(found.groups()) if found else ""


def read_rows(path: Path) -> list[list[str]]:
    """xlsx 첫 시트를 읽습니다. 표준 라이브러리만 씁니다."""

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
                    text = "".join(p.text or "" for p in node.iter(f"{NS}t")) if node else ""
                cells.append((text or "").strip())
            rows.append(cells)
    return rows


def convert(rows: list[list[str]]) -> dict:
    """{부호: [표준품명...]} 과 {표준품명: [부호...]} 를 만듭니다.

    엑셀 줄은 규격까지 갈라져 있어 같은 품명이 여러 번 나옵니다. 품명 단위로
    묶으면서 **처음 나온 순서를 지킵니다** (관세청이 적어 둔 품명번호 순서입니다).
    """

    header = next((line for line in rows if "HS부호" in line), None)
    if header is None:
        raise SystemExit("표에서 'HS부호' 머리글을 찾지 못했습니다. 서식이 바뀐 것 같습니다.")
    where = {name: index for index, name in enumerate(header) if name}
    missing = [name for name in NEEDED if name not in where]
    if missing:
        raise SystemExit(f"표에 없는 칸이 있습니다: {missing}. 서식이 바뀐 것 같습니다.")

    def cell(line: list[str], name: str) -> str:
        index = where.get(name)
        return line[index].strip() if index is not None and index < len(line) else ""

    by_code: dict[str, list[str]] = {}
    by_name: dict[str, list[str]] = {}
    official: dict[str, str] = {}
    english: dict[str, str] = {}

    for line in rows[rows.index(header) + 1:]:
        code = re.sub(r"\D", "", cell(line, "HS부호"))
        name = cell(line, "표준품명_한글")
        if len(code) != HS_LENGTH or not name:
            continue
        names = by_code.setdefault(code, [])
        if name not in names:
            names.append(name)
        codes = by_name.setdefault(name, [])
        if code not in codes:
            codes.append(code)
        official.setdefault(code, cell(line, "품명"))
        if "표준품명_영문" in where and cell(line, "표준품명_영문"):
            english.setdefault(name, cell(line, "표준품명_영문"))

    # "기타" 하나만 있는 부호는 찾기에 도움이 안 됩니다. 이름 표에서만 빼고
    # 부호별 목록에는 남겨 둡니다 (형제 목록에 "기타"도 보여야 합니다).
    lookup = {name: codes for name, codes in by_name.items() if name not in GENERIC}
    return {"by_code": by_code, "by_name": lookup,
            "official": official, "english": english}


def check(table: dict) -> None:
    names, codes = table["by_name"], table["by_code"]
    if len(names) < MIN_NAMES:
        raise SystemExit(f"표준품명이 {len(names):,}개뿐입니다. {MIN_NAMES:,}개 이상이어야 합니다. "
                         "받은 파일이 잘렸거나 서식이 바뀐 것 같습니다. 기존 파일은 그대로 둡니다.")
    if len(codes) < MIN_CODES:
        raise SystemExit(f"부호가 {len(codes):,}개뿐입니다. {MIN_CODES:,}개 이상이어야 합니다. "
                         "기존 파일은 그대로 둡니다.")
    # 형제가 둘 이상인 부호가 꽤 있어야 합니다. 없으면 품명 단위로 못 묶은 것입니다.
    with_siblings = sum(1 for v in codes.values() if len(v) > 1)
    if with_siblings < len(codes) * 0.4:
        raise SystemExit(f"형제 품명이 있는 부호가 {with_siblings:,}/{len(codes):,} 뿐입니다. "
                         "'표준품명_한글' 칸을 잘못 읽은 것 같습니다. 기존 파일은 그대로 둡니다.")


def main() -> None:
    parser = argparse.ArgumentParser(description="관세청 표준품명을 내부 표로 굳힙니다.")
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
        "source": "관세청 표준품명 (공공데이터포털)",
        "url": PAGE_URL,
        "license": "공공누리 제1유형(출처표시)",
        "base_date": stamp,
        "built_on": date.today().isoformat(),
        "count": len(table["by_name"]),
        "codes": len(table["by_code"]),
        **table,
    }, ensure_ascii=False), encoding="utf-8")

    siblings = sum(1 for v in table["by_code"].values() if len(v) > 1)
    print(f"■ 굳혔습니다 · 표준품명 {len(table['by_name']):,}개 · 부호 {len(table['by_code']):,}개")
    print(f"   형제 품명이 있는 부호 {siblings:,}개")
    print(f"   기준일 {stamp or '알 수 없음'} → {OUT_PATH} ({OUT_PATH.stat().st_size:,}바이트)")


if __name__ == "__main__":
    main()
