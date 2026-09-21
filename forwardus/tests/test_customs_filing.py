"""관세사 전달용 수출신고 자료."""

from __future__ import annotations

import pytest

from app.services import customs_filing_service
from app.validators import ValidationError


def test_sheet_collects_everything_a_customs_broker_asks_for(app, create_shipment):
    """관세사가 묻는 항목이 한 장에 모여 있어야 합니다."""

    with app.app_context():
        shipment = create_shipment()
        sheet = customs_filing_service.filing_sheet(shipment)

    labels = [row["label"] for section in sheet["sections"] for row in section["rows"]]
    for needed in ["수출자 상호", "수출자 사업자등록번호", "구매자 상호", "거래구분", "결제방법",
                   "인도조건 (Incoterms)", "결제통화", "신고가격", "운송수단", "적재항 (POL)",
                   "목적국", "원산지", "총 포장 수량", "총중량 (Gross)", "순중량 (Net)"]:
        assert needed in labels, needed

    item = sheet["lines"][0]
    assert {"hs_code", "product_description", "quantity", "gross_weight_kg"} <= set(item)


def test_missing_fields_are_named_not_invented(app, create_shipment):
    """비어 있는 칸은 지어내지 않고 비어 있다고 알려 줍니다."""

    with app.app_context():
        shipment = create_shipment()
        sheet = customs_filing_service.filing_sheet(shipment)

    # 사업자등록번호는 운송 입력에 없으므로 처음에는 비어 있습니다.
    assert "수출자 사업자등록번호" in sheet["missing"]
    assert "사업자등록번호" in customs_filing_service.describe_missing(sheet)


def test_business_number_is_stored_in_the_standard_shape(app, create_shipment):
    with app.app_context():
        shipment = create_shipment()
        customs_filing_service.update_filing_fields(shipment, {
            "exporter_business_no": "1234567890",
            "customs_trade_kind": "11",
            "customs_payment_method": "LS",
        })
        assert shipment.exporter_business_no == "123-45-67890"
        assert shipment.customs_payment_method == "LS"

        with pytest.raises(ValidationError):
            customs_filing_service.update_filing_fields(shipment, {"exporter_business_no": "123"})
        with pytest.raises(ValidationError):
            customs_filing_service.update_filing_fields(shipment, {"customs_trade_kind": "99"})


def test_copyable_text_lists_every_item(app, create_shipment):
    """메일에 붙여 넣을 글에 품목이 모두 들어갑니다."""

    with app.app_context():
        shipment = create_shipment(cargo=[
            {"product_description": "샴푸", "hs_code": "3305100000", "package_type": "carton",
             "quantity": 100, "length_cm": 40, "width_cm": 30, "height_cm": 25,
             "weight_per_package_kg": 12},
            {"product_description": "린스", "hs_code": "3305900000", "package_type": "carton",
             "quantity": 50, "length_cm": 40, "width_cm": 30, "height_cm": 25,
             "weight_per_package_kg": 12},
        ])
        text = customs_filing_service.as_text(customs_filing_service.filing_sheet(shipment))

    assert "[수출신고 자료]" in text
    assert "샴푸" in text and "린스" in text
    assert "HS 3305100000" in text
    assert "아직 비어 있는 칸" in text
