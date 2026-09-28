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


# --- 단가의 기준은 낱개, CBM 의 기준은 상자 -------------------------------------------

def test_낱개_수량과_단위를_함께_넣는다(app):
    """**제가 만든 문제입니다.**

    "낱개가 포장 개수 칸에 들어간다"를 고치며 수량을 1,200 -> 24상자로
    바꿨습니다. CBM·중량은 맞아졌는데 **단가의 기준이 무너졌습니다.**

        서류:  1,200 PCS × 4.50 = 5,400.00
        우리:  quantity 24(상자) · unit_price 4.50

    이 프로그램은 둘을 갈라 둡니다.
        quantity       포장 개수    CBM·중량의 기준
        unit_quantity  낱개 수량    단가의 기준
        price_unit     낱개의 단위
    priced_by_units() 는 **뒤의 둘이 다 있을 때만** 참입니다. 하나라도 비면
    단가 칸이 금액÷상자수로 채워져, 오퍼시트·L/C 와 다른 단가가 송장에 나갑니다.

    고치기 전에는 quantity 에 1,200 이 들어가 단가가 **우연히** 맞았습니다.
    CBM 이 50배 틀린 대가로요. 둘 다 맞아야 합니다.
    """

    from app.validators.cargo_validator import priced_by_units

    line = extract._item({"product_description": "3단 우산", "pieces": 1200,
                          "units_per_package": 50, "piece_unit": "PCS",
                          "package_unit": "CTN", "unit_price": 4.50,
                          "amount": 5400}, [], 1)
    assert line["quantity"] == "24"                      # CBM·중량의 기준
    assert line["unit_quantity"] == "1200"               # 단가의 기준
    assert line["price_unit"] == "PCS"
    assert float(line["unit_quantity"]) * float(line["unit_price"]) == pytest.approx(5400)

    holder = type("Cargo", (), dict(unit_quantity=1200, price_unit="PCS"))()
    assert priced_by_units(holder) is True


def test_상자_단위를_낱개_단위로_쓰지_않는다(app):
    """package_unit 은 상자를 세는 말입니다.

    그것을 단가의 단위로 쓰면 송장에 "1,200 **CTN** × 4.50" 으로 찍힙니다.
    서류에는 "1,200 PCS" 라고 적혀 있는데요.
    """

    line = extract._item({"product_description": "우산", "pieces": 1200,
                          "units_per_package": 50, "package_unit": "CTN",
                          "unit_price": 4.50}, [], 1)
    assert line["price_unit"] == "PCS", line.get("price_unit")


@pytest.mark.parametrize("piece_unit,want", [("PCS", "PCS"), ("KG", "KG"), ("", "PCS")])
def test_서류에_적힌_낱개_단위를_따른다(app, piece_unit, want):
    raw = {"product_description": "시험", "pieces": 500, "units_per_package": 25,
           "package_unit": "BAG"}
    if piece_unit:
        raw["piece_unit"] = piece_unit
    assert extract._item(raw, [], 1)["price_unit"] == want


def test_낱개를_모르면_단가_기준을_안_만든다(app):
    """반쪽만 넣으면 priced_by_units 가 거짓이라 넣으나 마나입니다."""

    line = extract._item({"product_description": "상자로만", "package_count": 40,
                          "package_unit": "CTNS", "unit_price": 265}, [], 1)
    assert line["quantity"] == "40"
    assert "unit_quantity" not in line
    assert "price_unit" not in line
