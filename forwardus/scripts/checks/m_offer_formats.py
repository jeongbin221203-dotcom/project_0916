# -*- coding: utf-8 -*-
"""오퍼시트 양식 50가지로 자동입력을 잽니다.

왜 50가지인가
  오퍼시트는 표준 서식이 없습니다. 회사마다 같은 값을 다르게 적습니다.
  표본 3종이 맞았다고 다 맞는 것이 아닙니다.

무엇을 흔드나 (실제 무역서류에서 쓰이는 표기만 씁니다)
  항구      Busan / BUSAN, KOREA / Port of Busan / Pusan / 부산
  인코텀즈   FOB / F.O.B. / fob / FOB Busan / Ex Works / EXW
  날짜      2027-03-24 / 24/03/2027 / March 24, 2027 / 24-MAR-2027 / 2027.03.24
  통화      USD / US$ / $ / usd
  도착항 없음  가격조건 줄에만 지명이 있는 경우 (오퍼시트에 흔합니다)

  50가지는 이 자리들을 섞어 만듭니다. 정답은 거래 5건의 값 그대로입니다.

AI 는 부르지 않습니다. AI 가 글자를 제대로 읽어 준다고 치고, 그 값이 칸으로
옮겨지는 길만 봅니다. 여기서 틀리면 AI 가 아무리 잘 읽어도 틀립니다.
"""
import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app import create_app
from config import TestConfig
from app.services import document_extract_service as X

# 거래 5건 — 표본 PDF 그대로. (인코텀즈, 출발지, 도착지, 선적일)
DEALS = [
    ("FOB", "KRPUS", "USLAX", "2027-03-24", "Busan", "Los Angeles"),
    ("CIF", "KRPUS", "CNSGH", "2027-04-28", "Busan", "Shanghai"),
    ("CFR", "KRINC", "JPYOK", "2027-06-02", "Incheon", "Yokohama"),
    ("FOB", "KRPUS", "SGSIN", "2027-07-23", "Busan", "Singapore"),
    ("CIF", "KRINC", "VNHPH", "2027-09-29", "Incheon", "Hai Phong"),
]

# 항구를 적는 열 가지 버릇. (원문, 꾸미는 함수)
PORT_STYLES = [
    ("그대로", lambda p, c: p),
    ("나라 붙임", lambda p, c: f"{p}, {c}"),
    ("대문자", lambda p, c: p.upper()),
    ("대문자+나라", lambda p, c: f"{p.upper()}, {c.upper()}"),
    ("Port of", lambda p, c: f"Port of {p}"),
    ("뒤에 PORT", lambda p, c: f"{p.upper()} PORT"),
    ("괄호 나라", lambda p, c: f"{p} ({c})"),
    # 쉼표 없이 나라를 붙이는 버릇. 쉼표로 자를 수 없어 나라 이름을 알아보고
    # 떼어야 합니다. ("Los Angeles USA")
    ("쉼표 없이 나라", lambda p, c: f"{p} {c}"),
    ("띄어쓰기 없앰", lambda p, c: p.replace(" ", "")),
    ("앞뒤 공백", lambda p, c: f"  {p}  "),
    ("Seaport", lambda p, c: f"{p} Seaport"),
]

COUNTRY = {"Busan": "Republic of Korea", "Incheon": "Republic of Korea",
           "Los Angeles": "United States", "Shanghai": "China",
           "Yokohama": "Japan", "Singapore": "Singapore", "Hai Phong": "Vietnam"}

# 인코텀즈를 적는 버릇
TERM_STYLES = [
    ("그대로", lambda t: t),
    ("소문자", lambda t: t.lower()),
    ("점 찍기", lambda t: ".".join(t) + "."),
    ("뒤에 2020", lambda t: f"{t} Incoterms 2020"),
    ("앞뒤 공백", lambda t: f" {t} "),
]

# 날짜를 적는 버릇 (ISO 로 돌아와야 맞습니다)
DATE_STYLES = [
    ("ISO", lambda d: d),
    ("점", lambda d: d.replace("-", ".")),
    # 숫자만 있는 날짜는 일부러 못 읽습니다. 2월 6일인지 6월 2일인지
    # 서류만으로는 가릴 수 없습니다. 빈 칸이 맞는 답입니다.
    ("슬래시 일/월/년(애매)", lambda d: f"{d[8:10]}/{d[5:7]}/{d[:4]}"),
    ("영문 달", lambda d: _long_date(d)),
    ("dd-MMM-yyyy", lambda d: _short_date(d)),
]

MONTHS = ["January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]


def _long_date(iso: str) -> str:
    return f"{MONTHS[int(iso[5:7]) - 1]} {int(iso[8:10])}, {iso[:4]}"


def _short_date(iso: str) -> str:
    return f"{iso[8:10]}-{MONTHS[int(iso[5:7]) - 1][:3].upper()}-{iso[:4]}"


def build() -> list[dict]:
    """양식 50가지를 만듭니다. 자리마다 버릇을 돌려 가며 씁니다."""

    cases = []
    no = 0
    for port_style, port_fn in PORT_STYLES:
        for term_style, term_fn in TERM_STYLES:
            deal = DEALS[no % len(DEALS)]
            date_style, date_fn = DATE_STYLES[no % len(DATE_STYLES)]
            terms, want_o, want_d, when, pol, pod = deal
            no += 1
            cases.append({
                "no": no,
                "이름": f"{port_style} · {term_style} · {date_style}",
                "raw": {
                    "incoterms": term_fn(terms),
                    "port_of_loading": port_fn(pol, COUNTRY[pol]),
                    "port_of_discharge": port_fn(pod, COUNTRY[pod]),
                    "shipment_date": date_fn(when),
                },
                "want": (terms, want_o, want_d, when),
            })
    return cases


def main() -> int:
    app = create_app(TestConfig)
    cases = build()
    bad = []
    with app.app_context():
        for case in cases:
            form = X.to_form(case["raw"])["fields"]
            terms, want_o, want_d, when = case["want"]
            got = (form.get("incoterms", ""), form.get("origin_code", ""),
                   form.get("destination_code", ""),
                   form.get("requested_departure_date", ""))
            # 애매한 숫자 날짜는 빈 칸이 맞는 답입니다.
            if "애매" in case["이름"]:
                when = ""
            if got != (terms, want_o, want_d, when):
                bad.append((case, got))

        print(f"■ 오퍼시트 양식 {len(cases)}가지 · 칸 4개씩 = {len(cases) * 4}가지 확인")
        print(f"   문제 {len(bad)}건\n")
        for case, got in bad:
            terms, want_o, want_d, when = case["want"]
            print(f"  ★ {case['no']:>2}. {case['이름']}")
            print(f"     넣은 값 {case['raw']}")
            print(f"     기대 인코텀즈 {terms} 출발 {want_o} 도착 {want_d} 선적일 {when}")
            print(f"     받음 인코텀즈 {got[0]!r} 출발 {got[1]!r} 도착 {got[2]!r} 선적일 {got[3]!r}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
