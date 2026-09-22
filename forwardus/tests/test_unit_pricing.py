"""단가의 기준 — 낱개로 값을 매긴 품목.

오퍼시트와 L/C는 대개 "2,000 PCS × USD 3.20"처럼 낱개로 값을 매깁니다.
우리 품목 줄의 quantity는 포장 개수라, 예전에는 송장에 "100 CTN × 64.00"이
찍혔습니다. 합계는 같아도 단가가 L/C와 다르면 은행에서 서류 불일치로
돌아옵니다.

여기서 지키는 것
  1. 낱개로 매긴 품목은 송장에 낱개 수량과 그 단가가 **그대로** 찍힌다
  2. 수량 × 단가 = 금액이 맞지 않으면 받지 않는다
  3. 포장 개수는 정확히 나누어떨어질 때만 계산한다
  4. 낱개 칸을 안 쓰면 예전과 똑같이 동작한다
"""

from __future__ import annotations

import pytest

from app.processors.cargo_calculator import calculate_cargo_lines
from app.validators import ValidationError
from app.validators.cargo_validator import price_unit_of, validate_cargo_input

BOX = {"length_cm": 40, "width_cm": 30, "height_cm": 25, "weight_per_package_kg": 12,
       "package_type": "carton", "product_description": "Hair Shampoo 500ml"}

# 오퍼시트에 적힌 그대로: 2,000 PCS × 3.20 = 6,400.00, 20 PCS/CTN
SHAMPOO = {**BOX, "unit_quantity": "2,000", "price_unit": "PCS", "unit_price": "3.20",
           "amount": "6,400.00", "units_per_package": "20"}


# --- 검증기 ------------------------------------------------------------------------

def test_낱개_기준_품목을_받는다():
    cargo = validate_cargo_input(SHAMPOO)

    assert cargo["unit_quantity"] == 2000
    assert cargo["price_unit"] == "PCS"
    assert cargo["unit_price"] == 3.2
    assert cargo["amount"] == 6400.0
    # 포장 개수는 2,000 ÷ 20 으로 구했습니다.
    assert cargo["quantity"] == 100


def test_수량_곱하기_단가가_금액과_다르면_받지_않는다():
    """오퍼시트를 잘못 읽었거나 오타가 난 경우입니다. 조용히 넘기면 송장이 틀립니다."""

    with pytest.raises(ValidationError) as caught:
        validate_cargo_input({**SHAMPOO, "amount": "6,500.00"})

    assert caught.value.field == "amount"
    assert "6,400.00" in str(caught.value) and "6,500.00" in str(caught.value)


def test_소수_단가도_정확히_맞으면_받는다():
    """0.85 × 5,000은 부동소수로 4250.000000000001입니다. 그걸 틀렸다고 하면 안 됩니다."""

    cargo = validate_cargo_input({**BOX, "unit_quantity": 5000, "price_unit": "PCS",
                                  "unit_price": 0.85, "amount": 4250, "units_per_package": 100})

    assert cargo["amount"] == 4250.0 and cargo["quantity"] == 50


def test_나누어떨어지지_않는_포장은_멈추고_묻는다():
    """2,010 ÷ 20 = 100.5상자. 반올림해 101로 적으면 서류가 거짓말을 합니다."""

    with pytest.raises(ValidationError) as caught:
        validate_cargo_input({**SHAMPOO, "unit_quantity": 2010, "amount": 6432})

    assert caught.value.field == "units_per_package"
    assert "100.50" in str(caught.value)


def test_입력_중에는_경고만_남기고_계산은_계속한다():
    """운송 계획 화면은 입력하는 도중에 계속 계산합니다. 그때 막으면 안 됩니다."""

    result = calculate_cargo_lines(
        [{**SHAMPOO, "unit_quantity": 2010, "amount": 6432, "quantity": 101}], strict=False)

    assert result["lines"][0]["quantity"] == 101
    assert any("나누어떨어지지" in row["message"] for row in result["warnings"])


def test_적은_포장_개수가_계산과_다르면_받지_않는다():
    with pytest.raises(ValidationError) as caught:
        validate_cargo_input({**SHAMPOO, "quantity": 90})

    assert caught.value.field == "quantity"
    assert "100" in str(caught.value) and "90" in str(caught.value)


def test_마지막_상자가_덜_찼으면_포장_개수를_직접_적는다():
    """포장당 낱개 수를 비우면 포장 개수는 사람이 적은 그대로 씁니다."""

    cargo = validate_cargo_input({**SHAMPOO, "unit_quantity": 2010, "amount": 6432,
                                  "units_per_package": "", "quantity": 101})

    assert cargo["quantity"] == 101 and cargo["unit_quantity"] == 2010


def test_단위가_없으면_받지_않는다():
    with pytest.raises(ValidationError) as caught:
        validate_cargo_input({**SHAMPOO, "price_unit": ""})

    assert caught.value.field == "price_unit"


def test_모르는_단위는_받지_않는다():
    """AI나 사람이 적은 낯선 단위를 그대로 서류에 찍지 않습니다."""

    with pytest.raises(ValidationError) as caught:
        validate_cargo_input({**SHAMPOO, "price_unit": "BAGGIES"})

    assert caught.value.field == "price_unit"


@pytest.mark.parametrize("written, expected", [
    ("pcs", "PCS"), ("Pieces", "PCS"), ("PC", "PCS"), ("kgs", "KG"),
    ("Dozen", "DZ"), ("pairs", "PR"), ("SET", "SET"), ("M/T", ""), ("", ""),
])
def test_서류마다_다른_단위_표기를_하나로_맞춘다(written, expected):
    assert price_unit_of(written) == expected


def test_금액만_있고_나누어떨어지지_않으면_단가를_지어내지_않는다():
    """100 ÷ 3 = 33.3333… 이 값을 송장에 찍으면 되곱해도 100이 안 나옵니다."""

    cargo = validate_cargo_input({**BOX, "unit_quantity": 3, "price_unit": "SET",
                                  "amount": 100, "quantity": 1})

    assert cargo["unit_price"] is None
    assert cargo["amount"] == 100.0


def test_금액만_있고_나누어떨어지면_단가를_채운다():
    cargo = validate_cargo_input({**BOX, "unit_quantity": 2000, "price_unit": "PCS",
                                  "amount": 6400, "quantity": 100})

    assert cargo["unit_price"] == 3.2


def test_낱개_칸을_안_쓰면_예전과_같다():
    """포장 개수가 단가의 기준입니다. 이미 만든 서류가 바뀌면 안 됩니다."""

    cargo = validate_cargo_input({**BOX, "quantity": 100, "amount": 6400})

    assert cargo["unit_price"] == 64.0
    assert cargo["unit_quantity"] is None and cargo["price_unit"] == ""


# --- 초안 서류 --------------------------------------------------------------------

DRAFT = {
    "exporter_name": "Forward Cosmetics Co., Ltd.", "buyer_name": "ABC Beauty Inc.",
    "origin_code": "KRPUS", "destination_code": "USLAX", "incoterms": "FOB",
    "currency": "USD", "items": [SHAMPOO],
}


def test_견적송장에_오퍼시트_단가가_그대로_찍힌다(app):
    from app.services import draft_document_service as drafts

    with app.app_context():
        rendered = drafts.render("proforma_invoice", DRAFT)

    row = rendered["data"]["items"][0]
    assert row["quantity"] == "2,000"
    assert row["unit"] == "PCS"
    assert row["unit_price"] == 3.2
    assert row["amount"] == 6400.0
    # 합계 칸의 단가도 포장 기준(64)이 아니라 낱개 기준입니다.
    assert rendered["data"]["unit_price"] == "3.2 / PCS"


def test_상업송장은_수량_칸에_단위까지_적고_포장은_따로_적는다(app):
    from app.services import draft_document_service as drafts

    with app.app_context():
        row = drafts.render("commercial_invoice", DRAFT)["data"]["items"][0]

    assert row["quantity"] == "2,000 PCS"
    assert row["unit_price"] == 3.2
    assert row["packages"] == "100 CTN"


def test_포장명세서는_포장_개수와_낱개_수량을_같이_적는다(app):
    """송장의 2,000 PCS와 포장명세서의 숫자가 같아야 합니다."""

    from app.services import draft_document_service as drafts

    with app.app_context():
        row = drafts.render("packing_list_std", DRAFT)["data"]["items"][0]

    assert row["packages"] == "100 CTN"
    assert row["net_weight"].startswith("2,000 PCS")


def test_어디에도_포장_기준_단가가_나오지_않는다(app):
    """64.0은 오퍼시트에 없는 단가입니다. 어느 서류에도 찍히면 안 됩니다."""

    from app.services import draft_document_service as drafts

    with app.app_context():
        for kind in ("proforma_invoice", "commercial_invoice", "packing_list_std"):
            data = drafts.render(kind, DRAFT)["data"]
            text = repr(data)
            assert "64.0" not in text, kind


# --- 저장된 Shipment -------------------------------------------------------------

def test_운송_계획으로_저장해도_기준이_남는다(app, create_shipment):
    """오퍼시트 → 운송 계획 → 최종 서류로 가는 길에서 단가가 바뀌면 안 됩니다."""

    from app.services import customs_filing_service, document_service

    shipment = create_shipment(cargo={**SHAMPOO, "quantity": ""}, invoice_value=6400)
    cargo = shipment.cargos[0]

    assert (cargo.unit_quantity, cargo.price_unit, cargo.units_per_package) == (2000, "PCS", 20)
    assert cargo.quantity == 100

    invoice = document_service.build_items(shipment, "commercial_invoice")[0]
    assert invoice["quantity"] == "2,000 PCS" and invoice["unit_price"] == 3.2

    # 수출신고 자료도 송장과 같은 기준입니다.
    line = customs_filing_service.filing_sheet(shipment)["lines"][0]
    assert (line["quantity"], line["unit"], line["unit_price"]) == (2000, "PCS", 3.2)


def test_낱개_칸이_없는_Shipment는_예전_서류_그대로다(app, create_shipment):
    from app.services import document_service

    shipment = create_shipment()
    row = document_service.build_items(shipment, "proforma_invoice")[0]

    assert row["quantity"] == 500
    assert row["unit"] == "CTN"
