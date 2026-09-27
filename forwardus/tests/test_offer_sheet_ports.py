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


# --- 짐작이 섞였으면 그렇다고 말하는가 ------------------------------------------------

def test_줄여서_찾았으면_그렇다고_적는다(app):
    """이름을 줄여서 찾았으면 **줄였다고 알려야** 합니다.

    값만 맞으면 된 것이 아닙니다. 'Los Angeles USA' 를 'Los Angeles' 로 줄여
    찾은 것은 짐작이 섞인 것이고, 사람이 한 번 봐야 합니다. 알림이 없으면
    그냥 서류에 그렇게 적혀 있던 것처럼 보입니다.

    (이 테스트가 없으면 줄이는 길을 통째로 지워도 아무도 울지 않습니다 —
     띄어쓰기를 지워 찾는 다른 길이 같은 답을 내기 때문입니다. 2026-09-27)
    """

    notes: list[str] = []
    found = extract._port("Los Angeles USA", "SEA", "destination", notes)
    assert found and found["code"] == "USLAX"
    assert any("Los Angeles" in note and "찾았습니다" in note for note in notes), notes


def test_일월_차례를_모르는_날짜는_까닭을_적는다(app):
    """02/06/2027 은 2월 6일인지 6월 2일인지 알 수 없습니다.

    비워 두는 것만으로는 부족합니다. **왜** 비웠는지 적어야 사람이 달력에서
    고릅니다. 그냥 "읽지 못했다"고만 하면 서류가 잘못된 줄 압니다.
    """

    notes: list[str] = []
    from app.services.intake_service import _date

    assert _date("02/06/2027", notes, "선적일") == ""
    assert any("일/월" in note for note in notes), notes


def test_뜻이_하나인_날짜는_읽는다(app):
    """연도가 앞에 오거나 달이 글자면 뜻이 하나로 정해집니다."""

    from app.services.intake_service import _date

    for written, want in (("2027-03-24", "2027-03-24"), ("2027.04.28", "2027-04-28"),
                          ("29-SEP-2027", "2027-09-29"), ("July 23, 2027", "2027-07-23"),
                          ("20270428", "2027-04-28")):
        notes: list[str] = []
        assert _date(written, notes, "선적일") == want, (written, notes)


def test_가격조건에_붙은_군더더기를_뗀다(app):
    """C.I.F. · "FOB Incoterms 2020" · "FOB Busan" 전부 오퍼시트에 나오는 모양입니다."""

    from app.services.intake_service import _incoterms_word

    for written, want in (("CIF", "CIF"), ("cif", "CIF"), ("C.I.F.", "CIF"),
                          ("C.F.R.", "CFR"), ("FOB Incoterms 2020", "FOB"),
                          ("FOB Busan", "FOB"), (" CIF ", "CIF")):
        assert _incoterms_word(written) == want, written
    # 모르는 말은 비워 둡니다. 지어내면 안 됩니다.
    for written in ("XYZ", "FOBB", "", "Incoterms 2020"):
        assert _incoterms_word(written) == "", written
