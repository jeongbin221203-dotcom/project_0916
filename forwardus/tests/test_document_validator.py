"""Document generation and cross-document validation tests."""

from __future__ import annotations

import pytest

from app.processors.document_validator import validate_documents
from app.services import ServiceError, document_service
from app.validators import ValidationError


def test_quantity_mismatch_matches_spec_example():
    reference = {"quantity": 500}
    documents = {
        "commercial_invoice": {"quantity": 500},
        "packing_list": {"quantity": 500},
        "bl_draft": {"quantity": 480},
    }
    result = validate_documents(documents, reference)
    assert result["status"] == "warning"
    assert len(result["findings"]) == 1
    finding = result["findings"][0]
    assert finding["status"] == "warning"
    assert finding["field"] == "quantity"
    assert finding["expected"] == 500
    assert finding["actual"] == 480
    assert finding["document"] == "bl_draft"


def test_text_comparison_ignores_case_and_spacing():
    result = validate_documents({"ci": {"consignee": "abc  beauty inc."}}, {"consignee": "ABC Beauty Inc."})
    assert result["status"] == "passed"


def test_empty_field_flagged():
    result = validate_documents({"ci": {"hs_code": ""}}, {"hs_code": "3304.99"})
    assert result["findings"][0]["actual"] is None


def test_generated_documents_reuse_shipment_data(create_shipment):
    shipment = create_shipment()
    document_service.generate_documents(shipment)
    ci = document_service.get_document(shipment, "commercial_invoice")
    assert ci.status == "generated"
    assert ci.data["exporter"] == shipment.exporter_name
    assert ci.data["consignee"] == shipment.buyer.name
    assert ci.data["quantity"] == shipment.cargo.quantity
    assert ci.data["invoice_value"] == shipment.invoice_value
    assert ci.data["pol"].endswith("(KRPUS)")
    assert document_service.validate_shipment_documents(shipment)["status"] == "passed"
    assert ci.status == "validated"


def test_documents_follow_standard_form_fields(create_shipment):
    """표준 서식(상업송장·P/I·Booking Request·S/R)의 칸이 서류마다 들어 있고, 채울 수 있는 값은 채웁니다."""

    shipment = create_shipment()
    document_service.generate_documents(shipment)

    ci = document_service.get_document(shipment, "commercial_invoice").data
    assert {"lc_no", "buyer", "shipping_marks", "payment_terms", "signed_by"} <= set(ci)
    assert ci["signed_by"] == shipment.exporter_name and ci["lc_no"] == ""

    pi = document_service.get_document(shipment, "proforma_invoice").data
    assert pi["country_of_origin"] == "THE REPUBLIC OF KOREA"
    assert pi["carriage_by"] == ("AIR" if shipment.transport_mode == "AIR" else "SEA")
    assert pi["final_destination"].endswith(f"({shipment.destination_code})")
    assert {"validity_date", "po_no", "bank_info", "shipment_time"} <= set(pi)

    br = document_service.get_document(shipment, "booking_request").data
    digits = "".join(ch for ch in shipment.cargo.hs_code if ch.isdigit())
    assert br["hs6"] == f"{digits[:4]}.{digits[4:6]}"
    # 운임 조건에 따라 선불지·후불지 중 하나만 채웁니다.
    assert (br["prepaid_at"] == "") != (br["collect_at"] == "")
    assert {"notify_party_2", "service_contract_no", "reefer", "confirmation_to"} <= set(br)

    sr = document_service.get_document(shipment, "shipping_instruction").data
    assert {"booking_no", "container_seal_no", "shipping_marks"} <= set(sr)

    # 새 칸도 서류에서 직접 고칠 수 있습니다.
    document_service.update_document(shipment, "commercial_invoice", {"lc_no": "LC-2026-001 / 2026-09-01"})
    assert document_service.get_document(shipment, "commercial_invoice").data["lc_no"] == "LC-2026-001 / 2026-09-01"

    view = document_service.document_view(document_service.get_document(shipment, "proforma_invoice"))
    assert next(f for f in view if f["key"] == "bank_info")["wide"] is True
    assert next(f for f in view if f["key"] == "po_no")["wide"] is False


def test_edit_creates_warning_and_blocks_finalize(create_shipment):
    shipment = create_shipment()
    document_service.generate_documents(shipment)
    document_service.update_document(shipment, "bl_draft", {"quantity": "480"})
    result = document_service.validate_shipment_documents(shipment)
    assert result["status"] == "warning"
    assert [(f["document"], f["field"]) for f in result["findings"]] == [("bl_draft", "quantity")]
    with pytest.raises(ValidationError):
        document_service.finalize_document(shipment, "bl_draft")
    # Unaffected documents can still be finalized.
    assert document_service.finalize_document(shipment, "commercial_invoice").status == "final"
    with pytest.raises(ServiceError):
        document_service.update_document(shipment, "commercial_invoice", {"remarks": "x"})


@pytest.mark.parametrize("bad", ["abc", "-5", "nan", "1.5"])
def test_document_numeric_edit_validated(create_shipment, bad):
    shipment = create_shipment()
    document_service.generate_documents(shipment)
    with pytest.raises(ValidationError):
        document_service.update_document(shipment, "packing_list", {"quantity": bad})


def test_net_weight_not_invented_when_missing(create_shipment, cargo_input):
    shipment = create_shipment(cargo={**cargo_input, "net_weight_kg": ""})
    document_service.generate_documents(shipment)
    assert document_service.get_document(shipment, "packing_list").data["net_weight_kg"] == ""
