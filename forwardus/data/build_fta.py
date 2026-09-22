"""관세청 FTA 포털에서 협정 회원국과 원산지증명 발급방식을 받아옵니다.

협정별 회원국과 원산지증명 발급방식을 주는 API는 없습니다. (UNI-PASS 통계부호
A12는 서버 오류 상태입니다.) 대신 관세청 FTA 포털의 공개 페이지 세 곳에 우리가
필요한 내용이 관세청 표기 그대로 있어, 여기서 받아 파일로 굳혀 둡니다.

    python data/build_fta.py

결과: data/mock/fta_agreements.json
협정이 새로 발효되거나 회원국이 바뀔 때만 다시 돌리면 됩니다.

받아온 한글 국가명은 관세청 국가코드(통계부호 A06)와 대조해 2자리 코드로
바꿉니다. 하나라도 못 맞추면 기존 파일을 건드리지 않고 그대로 멈춥니다.
페이지 구조가 바뀌었는데 조용히 빈 목록이 들어가는 것이 가장 위험합니다.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

OUT_PATH = Path(__file__).resolve().parent / "mock" / "fta_agreements.json"
PORTAL = "https://www.customs.go.kr/ftaportalkor/cm/cntnts/cntntsView.do"
# User-Agent가 없으면 400을 돌려줍니다.
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; FORWARDUS/1.0)"}
PAGES = {
    "members": {"mi": "3310", "cntntsId": "986"},      # FTA 발효현황 (각주에 회원국)
    "apta": {"mi": "3343", "cntntsId": "1022"},        # 아시아·태평양 무역협정
    "certificate": {"mi": "3401", "cntntsId": "1061"},  # 원산지증명서 발급
}

# 관세청 국가코드(A06)와 표기가 다른 이름
NAME_ALIASES = {
    "체코": "체코공화국",
    "룩셈부르크": "룩셈부르그",
    "포르투갈": "포루투갈",
    "아랍에미리트연합국(UAE)": "아랍에미리트 연합",
    "미국": "미국",
}


def fetch(page: str) -> str:
    response = httpx.get(PORTAL, params=PAGES[page], headers=HEADERS, timeout=60)
    response.raise_for_status()
    return response.text


def clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = (text.replace("&nbsp;", " ").replace("&middot;", "·")
            .replace("&rsquo;", "'").replace("&lsquo;", "'").replace("&amp;", "&"))
    return re.sub(r"\s+", " ", text).strip()


def table_rows(html: str) -> list[list[list[str]]]:
    """표를 [행[칸]] 형태로 바꿉니다."""

    out = []
    for table in re.findall(r"<table.*?</table>", html, re.S):
        rows = [[clean(cell) for cell in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)]
                for row in re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.S)]
        out.append([row for row in rows if row])
    return out


def parse_members(html: str) -> dict[str, list[str]]:
    """발효현황 각주에서 협정체별 회원국을 읽습니다."""

    text = clean(html)
    members = {}
    for key, pattern in (
        ("EFTA", r"EFTA\(유럽자유무역연합\)\(\d+개국\)\s*:\s*([^0-9)]+?)\s*\d\)"),
        ("아세안", r"ASEAN\(\d+개국\)\s*:\s*([^0-9)]+?)\s*\d\)"),
        ("EU", r"EU\(\d+개국\)\s*:\s*(.+?)\s*\d\)\s*중미"),
        ("중미", r"중미\(\d+개국\)\s*:\s*([^0-9)]+?)\s*\d\)"),
    ):
        match = re.search(pattern, text)
        if not match:
            raise SystemExit(f"발효현황 페이지에서 {key} 회원국을 찾지 못했습니다. 페이지 구조를 확인해주세요.")
        members[key] = [name.strip() for name in match.group(1).split(",") if name.strip()]
    return members


def parse_apta(html: str) -> list[str]:
    """아시아·태평양 무역협정 회원국 (한국 제외)."""

    for table in table_rows(html):
        for row in table:
            if row and row[0] == "회원국" and len(row) > 1:
                names = [name.strip() for name in row[1].split(",") if name.strip()]
                return [name for name in names if name != "한국"]
    raise SystemExit("아시아·태평양 무역협정 회원국을 찾지 못했습니다.")


def parse_certificates(html: str) -> dict[str, dict]:
    """협정별 원산지증명 발급방식·발급자·서식·유효기간을 읽습니다."""

    wanted = {"발급방식": "method", "발급자": "issuer", "증명서식": "form", "유효기간": "valid_for"}
    certificates: dict[str, dict] = {}
    for table in table_rows(html):
        header = table[0] if table else []
        if not header or header[0] != "구분" or len(header) < 3:
            continue
        partners = header[1:]
        if any(word in partners[0] for word in ("기관발급", "자율발급")):
            continue                                   # 제도 설명 표는 건너뜁니다.
        for row in table[1:]:
            field = wanted.get(row[0])
            if not field:
                continue
            for partner, value in zip(partners, row[1:]):
                certificates.setdefault(partner, {})[field] = value
    if not certificates:
        raise SystemExit("원산지증명 발급 표를 찾지 못했습니다.")
    return certificates


def to_codes(names: list[str], country_codes: dict[str, str], label: str) -> list[str]:
    """한글 국가명을 2자리 코드로 바꿉니다. 하나라도 못 맞추면 멈춥니다."""

    codes, missing = [], []
    for name in names:
        key = NAME_ALIASES.get(name, name)
        code = country_codes.get(key) or next(
            (iso for full, iso in country_codes.items() if full.startswith(key)), None)
        if code:
            codes.append(code)
        else:
            missing.append(name)
    if missing:
        raise SystemExit(f"{label}: 관세청 국가코드에서 못 찾은 이름 {missing}")
    return codes


def main() -> None:
    from app import create_app
    from app.collectors import customs_client

    app = create_app()
    with app.app_context():
        result = customs_client.fetch_country_codes()
    if not result["success"]:
        raise SystemExit(f"관세청 국가코드를 받지 못했습니다: {result['message']}")
    country_codes = result["data"]

    members = parse_members(fetch("members"))
    members["일반"] = parse_apta(fetch("apta"))      # 관세율구분명이 "(일반)"으로 옵니다.
    blocs = {key: to_codes(names, country_codes, key) for key, names in members.items()}
    certificates = parse_certificates(fetch("certificate"))

    OUT_PATH.write_text(json.dumps({
        "source": "관세청 FTA 포털",
        "pages": {key: f"{PORTAL}?mi={value['mi']}&cntntsId={value['cntntsId']}"
                  for key, value in PAGES.items()},
        "blocs": blocs,
        "certificates": certificates,
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"{OUT_PATH}")
    for key, codes in blocs.items():
        print(f"  {key}: {len(codes)}개국 · {' '.join(codes)}")
    print(f"  원산지증명 발급방식: {len(certificates)}개 협정")


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUTF8", "1")
    main()
