"""오퍼시트의 수량이 **낱개인가 상자 수인가**. (2026-09-28)

왜 있나
  우산 오퍼시트를 넣어 보니 낱개가 포장 개수 칸으로 들어갔습니다.

      서류: UMB-01  1,200 PCS · 50 PCS per export carton · Total 40 cartons
      우리: quantity = 1200      <- 맞는 값은 24상자

  quantity 칸은 **상자 수**이고 CBM 과 한 포장 무게를 여기서 냅니다.
  낱개를 넣으면 화물이 **50배**로 부풀어 운임·스케줄이 통째로 틀립니다.
  그런데 화면 어디에도 경고가 안 뜹니다.

  앞서 넣어 본 표본 15장은 품목마다 포장이 적혀 있어 이 문제가 안 보였습니다.
  오퍼시트의 Quantity 열은 대개 낱개라, 오히려 이쪽이 흔합니다.
"""

from __future__ import annotations

import pytest

from app.services import document_extract_service as extract


def _one(raw: dict) -> tuple[str, list[str]]:
    notes: list[str] = []
    line = extract._item({"product_description": "시험", **raw}, notes, 1)
    return line.get("quantity", ""), notes


def test_낱개를_한_상자_개수로_나눈다():
    """서류에 둘 다 적혀 있으면 계산합니다. 짐작이 아닙니다."""

    got, notes = _one({"pieces": 1200, "units_per_package": 50, "package_unit": "PCS"})
    assert got == "24"
    assert any("낱개" in note and "24상자" in note for note in notes), notes


def test_딱_안_떨어지면_올리고_그렇다고_적는다():
    """1,210개를 50개들이 상자에 담으면 25상자입니다(마지막은 덜 참)."""

    got, notes = _one({"pieces": 1210, "units_per_package": 50, "package_unit": "PCS"})
    assert got == "25"
    assert any("올렸습니다" in note for note in notes), notes


def test_낱개인데_한_상자_개수를_모르면_비운다():
    """**짐작하지 않습니다.**

    빈 칸은 사람이 채우지만, 50배 부푼 화물은 아무도 못 알아챕니다.
    """

    got, notes = _one({"package_count": 1200, "package_unit": "PCS"})
    assert got == ""
    assert any("낱개" in note and "직접 적어" in note for note in notes), notes


@pytest.mark.parametrize("unit", ["CTNS", "CTN", "PLTS", "CARTONS", ""])
def test_상자_수가_제대로_적혔으면_그대로_쓴다(unit):
    """고치다가 멀쩡한 서류를 건드리면 안 됩니다."""

    got, _ = _one({"package_count": 40, "package_unit": unit})
    assert got == "40"


def test_서류의_총_상자_수로_검산한다(app):
    """24 + 16 = 40 — 서류가 스스로 확인해 줍니다.

    합이 맞으면 우리가 나눈 것이 옳았다는 뜻입니다.
    """

    out = extract.to_form({
        "total_packages": 40,
        "items": [
            {"product_description": "3단 우산", "pieces": 1200,
             "units_per_package": 50, "package_unit": "PCS", "unit_price": 4.50, "amount": 5400},
            {"product_description": "장우산", "pieces": 800,
             "units_per_package": 50, "package_unit": "PCS", "unit_price": 6.50, "amount": 5200},
        ],
    })
    assert [line["quantity"] for line in out["items"]] == ["24", "16"]
    assert any("맞습니다" in note and "40상자" in note for note in out["notes"]), out["notes"]


def test_합이_안_맞으면_그렇다고_적는다(app):
    """우리가 잘못 나눴을 수 있습니다. 조용히 넘어가면 안 됩니다."""

    out = extract.to_form({
        "total_packages": 99,
        "items": [
            {"product_description": "가", "pieces": 1200, "units_per_package": 50,
             "package_unit": "PCS", "unit_price": 1, "amount": 1200},
        ],
    })
    assert any("다릅니다" in note for note in out["notes"]), out["notes"]


# --- 서류에 또렷이 적힌 발송일·도착 희망일 ------------------------------------------

def test_Seller_dispatch_를_선적일로_읽는다(app):
    """"선적(예정)일"이라고만 적어 두었더니 AI 가 이 줄을 못 알아봤습니다.

    2쪽짜리 Firm Offer 는 이렇게 적습니다.
        Shipment        Within 60 calendar days after receipt of full T/T payment
        Seller dispatch February 26, 2027 (2027-02-26): cargo ready date
    윗줄은 기준일이 없어 비우는 것이 맞지만, 아랫줄에는 진짜 날짜가 있습니다.
    29칸이 차고 선적일만 비어 있었습니다. (2026-09-28)
    """

    form = extract.to_form({"shipment_date": "2027-02-26",
                            "buyer_required_date": "2027-04-15"})["fields"]
    assert form["requested_departure_date"] == "2027-02-26"
    assert form["buyer_required_date"] == "2027-04-15"


def test_Buyer_요청_도착일_칸을_채운다(app):
    """화면에 칸이 있는데 서류 읽기에서 아예 안 받고 있었습니다.

    운송 계획이 스케줄을 고를 때 쓰는 값입니다.
    """

    form = extract.to_form({"buyer_required_date": "April 15, 2027"})["fields"]
    assert form["buyer_required_date"] == "2027-04-15"


def test_기준일_없는_상대_날짜는_비운다(app):
    """"입금 후 60일 이내"는 언제부터인지 모릅니다. 짐작하지 않습니다."""

    form = extract.to_form({"shipment_date": "Within 60 calendar days after payment"})["fields"]
    assert not form.get("requested_departure_date")
