"""오퍼시트에서 읽은 항구 이름 — **엉뚱한 곳을 채우지 않는가.**

왜 이 파일이 있나
  오퍼시트는 회사마다 칸 이름이 다릅니다. 그래서 바이어 주소가 항구 칸으로
  들어오는 일이 생깁니다. 그때 항구를 못 찾으면 빈 칸으로 두어야 하는데,
  예전에는 **낱말을 하나 떼고 다시 찾아** 아무 데나 들어맞았습니다.

    "Phong Nha, Vietnam"        -> 'Nha'  -> 나바셰바항(INNSA, 인도)
    "Hai Duong, Vietnam"        -> 'Hai'  -> 하이퐁항(VNHPH)
    "Angeles City, Philippines" -> 'City' -> 호찌민항(VNSGN)

  자동입력은 틀리면 안 되는 자리입니다. 빈 칸이 틀린 칸보다 낫습니다.
  그래서 **안 잡혀야 하는 글을 먼저** 둡니다. (2026-09-27)
"""

from __future__ import annotations

import pytest

from app.services import document_extract_service as extract

# 우리 항구가 아닌 글. 하나라도 잡히면 실패입니다.
NOT_A_PORT = [
    ("Phong Nha, Vietnam", "destination"),            # 'Phong'·'Nha'만 겹칩니다
    ("Hai Duong, Vietnam", "destination"),            # 'Hai'만 겹칩니다
    ("Angeles City, Philippines", "destination"),     # 'Angeles'·'City'만 겹칩니다
    ("Hanoi, Vietnam", "destination"),                # 바이어 도시. 항구는 하이퐁입니다
    ("Shanghai Linen Demo Trading Co., Ltd.", "destination"),   # 회사 이름입니다
    ("New Busan Logistics Center", "origin"),         # 항구가 아니라 물류창고입니다
    ("Daegu, Republic of Korea", "origin"),           # 회사 소재지일 뿐입니다
]

# 같은 항구를 서류마다 다르게 적습니다. 전부 같은 코드로 가야 합니다.
SAME_PORT = [
    # 하이퐁 — 항구표에는 'Haiphong' 한 낱말로 들어 있습니다.
    ("Hai Phong, Vietnam", "VNHPH", "destination"),
    ("Hai Phong", "VNHPH", "destination"),
    ("HAIPHONG", "VNHPH", "destination"),
    ("Port of Hai Phong", "VNHPH", "destination"),
    ("HAI PHONG PORT", "VNHPH", "destination"),
    # 부산 · 인천 — 옛 로마자 표기(Pusan · Inchon)도 받습니다.
    ("Busan, Republic of Korea", "KRPUS", "origin"),
    ("BUSAN, KOREA", "KRPUS", "origin"),
    ("Port of Busan", "KRPUS", "origin"),
    ("Pusan", "KRPUS", "origin"),
    ("Incheon, Republic of Korea", "KRINC", "origin"),
    ("INCHON", "KRINC", "origin"),
    # 나라가 붙어 오는 것
    ("Los Angeles, United States", "USLAX", "destination"),
    ("LOS ANGELES, CA, USA", "USLAX", "destination"),
    ("Shanghai, China", "CNSGH", "destination"),
    ("Yokohama, Japan", "JPYOK", "destination"),
    ("Singapore", "SGSIN", "destination"),
]


@pytest.mark.parametrize("text,role", NOT_A_PORT)
def test_항구가_아니면_비워_둔다(app, text, role):
    found = extract._port(text, "SEA", role, [])
    assert found is None, f"'{text}' 에 {found and found.get('name')}({found and found.get('code')})를 넣었습니다"


@pytest.mark.parametrize("text,code,role", SAME_PORT)
def test_같은_항구는_같은_코드로_간다(app, text, code, role):
    found = extract._port(text, "SEA", role, [])
    assert found is not None, f"'{text}' 을(를) 못 찾았습니다"
    assert found["code"] == code, f"'{text}' -> {found['name']}({found['code']}) · 기대 {code}"


def test_표본_오퍼시트_다섯_거래가_그대로_들어간다(app):
    """사용자가 준 표본(2027년 거래 5건)의 인코텀즈·항구·선적일.

    001·003 은 같은 거래를 다른 양식으로 적은 것이고, 002 는 원산지증명서라
    인코텀즈가 없습니다. 어느 양식이든 같은 값이 나와야 합니다.
    """

    deals = [
        ("FOB", "Busan, Republic of Korea", "Los Angeles, United States",
         "2027-03-24", "KRPUS", "USLAX"),
        ("CIF", "Busan, Republic of Korea", "Shanghai, China",
         "2027-04-28", "KRPUS", "CNSGH"),
        ("CFR", "Incheon, Republic of Korea", "Yokohama, Japan",
         "2027-06-02", "KRINC", "JPYOK"),
        ("FOB", "Busan, Republic of Korea", "Singapore",
         "2027-07-23", "KRPUS", "SGSIN"),
        # 바이어는 하노이인데 도착항은 하이퐁입니다. 도시와 항구가 다릅니다.
        ("CIF", "Incheon, Republic of Korea", "Hai Phong, Vietnam",
         "2027-09-29", "KRINC", "VNHPH"),
    ]
    for incoterms, pol, pod, when, want_origin, want_dest in deals:
        for terms in (incoterms, ""):        # 오퍼시트 / 원산지증명서
            form = extract.to_form({
                "incoterms": terms, "port_of_loading": pol,
                "port_of_discharge": pod, "shipment_date": when,
            })["fields"]
            assert form.get("origin_code") == want_origin, (pol, form.get("origin_code"))
            assert form.get("destination_code") == want_dest, (pod, form.get("destination_code"))
            assert form.get("requested_departure_date") == when, (when, form)
            assert form.get("incoterms", "") == terms
