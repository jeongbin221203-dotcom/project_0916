"""오퍼시트를 AI에 실제로 넣어 보고 찾은 잘못 셋. (2026-09-27)

표본 PDF 15장을 AI에 넣었더니 001·002 양식 10장은 다 맞고 003 양식에서만
어긋났습니다. 손으로 값을 넣어 보던 때는 안 보이던 것들입니다 — AI가 어느
글자를 어느 칸으로 보내는지는 실제로 불러 봐야 알 수 있었습니다.
"""

from __future__ import annotations

import pytest

from app.services import document_extract_service as extract

BUSAN = "Busan, Republic of Korea"


def _plan(raw: dict) -> tuple[dict, list[str], object]:
    """to_form 과 lc_plan 을 extract() 와 같은 차례로 돌립니다."""

    form = extract.to_form(raw)
    fields, notes = form["fields"], form["notes"]
    schedule = extract.lc_plan(raw, fields, fields.get("transport_mode") or "SEA", notes)
    if schedule:
        fields["requested_departure_date"] = schedule["recommended_etd"].isoformat()
    return fields, notes, schedule


# --- ① 오퍼시트의 유효기일은 L/C 유효기일이 아닙니다 ---------------------------------

def test_오퍼시트_유효기일로_선적일을_덮어쓰지_않는다(app):
    """003 양식은 조건을 번호 매긴 목록으로 적습니다.

        3) Payment   T/T: 100% in advance, before shipment.
        6) Validity  Valid through 2027-03-16

    Validity 는 **이 가격이 언제까지 유효한가**입니다. L/C와 상관없습니다.
    그런데 이것을 L/C 유효기일로 보고, 서류에 적힌 선적일 2027-03-24 를
    2027-02-20 으로 덮어썼습니다. 한 달 넘게 앞당겨진 날로 스케줄을 잡으면
    배를 놓칩니다.
    """

    fields, _, schedule = _plan({
        "document_type": "offer_sheet",
        "payment_terms": "T/T: 100% in advance, before shipment.",
        "lc_expiry_date": "2027-03-16", "shipment_date": "2027-03-24",
        "incoterms": "FOB", "transport_mode": "SEA",
        "port_of_loading": BUSAN, "port_of_discharge": "Los Angeles, United States",
    })
    assert schedule is None, "L/C가 없는 서류인데 L/C 일정이 돌았습니다"
    assert fields["requested_departure_date"] == "2027-03-24"


def test_오퍼시트에_L_C라고_적혀_있어도_유효기일은_안_쓴다(app):
    """L/C로 결제한다고 적혀 있어도, L/C 유효기일은 **은행이 내는 L/C에만** 있습니다.

    오퍼시트의 Validity 를 그것으로 보면 안 됩니다. 대신 L/C 원본을 올려
    달라고 말합니다.
    """

    fields, notes, schedule = _plan({
        "document_type": "offer_sheet",
        "payment_terms": "Irrevocable L/C at sight in favor of the seller.",
        "lc_expiry_date": "2027-04-19", "shipment_date": "2027-04-28",
        "incoterms": "CIF", "transport_mode": "SEA",
        "port_of_loading": BUSAN, "port_of_discharge": "Shanghai, China",
    })
    assert schedule is None
    assert fields["requested_departure_date"] == "2027-04-28"
    assert any("L/C" in note and "원본" in note for note in notes), notes


def test_진짜_L_C_원본은_그대로_계산한다(app):
    """고치다가 쓸모를 없애면 안 됩니다. L/C 원본은 여전히 선적 마감을 냅니다."""

    fields, notes, schedule = _plan({
        "document_type": "letter_of_credit", "lc_no": "LC-2027-77",
        "payment_terms": "Irrevocable L/C", "lc_expiry_date": "2027-05-30",
        "lc_latest_shipment_date": "2027-05-10",
        "incoterms": "CIF", "transport_mode": "SEA",
        "port_of_loading": BUSAN, "port_of_discharge": "Shanghai, China",
    })
    assert schedule is not None, "L/C 원본인데 선적 마감을 안 냈습니다"
    assert any("선적 마감" in note for note in notes), notes


@pytest.mark.parametrize("payment,has_lc", [
    ("T/T: 100% in advance, before shipment.", False),
    ("T/T: 30% deposit on order; 70% before shipment.", False),
    ("Irrevocable L/C at sight in favor of the seller.", True),
    ("취소불능 신용장 일람불", True),
    ("Documentary Credit", True),
    ("", False),
])
def test_결제조건으로_L_C_거래인지_가린다(app, payment, has_lc):
    assert extract.has_letter_of_credit({"payment_terms": payment}) is has_lc


# --- ② 해상 전용 조건인데 항공으로 보던 것 -------------------------------------------

@pytest.mark.parametrize("terms", ["FOB", "CFR", "CIF", "FAS"])
def test_배로만_쓰는_조건이면_항공으로_보지_않는다(app, terms):
    """FOB·CFR·CIF·FAS 는 Incoterms 2020 에서 배로만 쓰는 조건입니다.

    (ICC 가 "Rules for Sea and Inland Waterway Transport" 로 묶어 둔 넷)
    그런데 AI가 운송수단을 AIR로 읽으면 부산항 대신 **김해공항**이,
    상하이항 대신 **푸둥공항**이 들어갔습니다. 표본 003-02 에서 실제로
    그랬습니다. 조건이 더 믿을 만하니 조건을 따릅니다.
    """

    form = extract.to_form({"transport_mode": "AIR", "incoterms": terms,
                            "port_of_loading": BUSAN,
                            "port_of_discharge": "Shanghai, China"})
    fields = form["fields"]
    assert fields["transport_mode"] == "SEA"
    assert fields.get("origin_code") == "KRPUS", fields.get("origin_code")
    assert fields.get("destination_code") == "CNSGH", fields.get("destination_code")
    assert any("배로만" in note for note in form["notes"]), form["notes"]


@pytest.mark.parametrize("terms", ["CPT", "CIP", "DAP", "DDP", "EXW", "FCA"])
def test_항공에도_쓰는_조건은_건드리지_않는다(app, terms):
    """모든 운송수단에 쓰는 조건까지 배로 바꾸면 진짜 항공 건이 망가집니다."""

    form = extract.to_form({"transport_mode": "AIR", "incoterms": terms})
    assert form["fields"]["transport_mode"] == "AIR"
    assert not any("배로만" in note for note in form["notes"])


def test_L_C가_아닌_결제면_상업송장이라도_L_C_일정을_안_돌린다(app):
    """오퍼시트가 아닌 서류에서도 같은 규칙입니다.

    상업송장은 L/C 날짜를 **적을 수 있는** 서류라 NO_LC_DATES 에 없습니다.
    그래도 결제가 T/T 면 L/C 거래가 아니므로 선적 마감을 계산하면 안 됩니다.
    (이 테스트가 없으면 has_letter_of_credit 를 통째로 지워도 아무도 울지
     않습니다 — 오퍼시트는 NO_LC_DATES 가 따로 막아 주기 때문입니다. 2026-09-27)
    """

    fields, _, schedule = _plan({
        "document_type": "commercial_invoice",
        "payment_terms": "T/T 30 days after B/L date",
        "lc_expiry_date": "2027-05-30", "shipment_date": "2027-06-10",
        "incoterms": "CIF", "transport_mode": "SEA",
        "port_of_loading": BUSAN, "port_of_discharge": "Shanghai, China",
    })
    assert schedule is None, "T/T 결제인데 L/C 일정이 돌았습니다"
    assert fields["requested_departure_date"] == "2027-06-10"
