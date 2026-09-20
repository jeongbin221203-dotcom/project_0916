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
        "shipping_instruction": {"quantity": 480},
    }
    result = validate_documents(documents, reference)
    assert result["status"] == "warning"
    assert len(result["findings"]) == 1
    finding = result["findings"][0]
    assert finding["status"] == "warning"
    assert finding["field"] == "quantity"
    assert finding["expected"] == 500
    assert finding["actual"] == 480
    assert finding["document"] == "shipping_instruction"


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


def test_packing_list_follows_the_korean_standard_form(create_shipment):
    """포장명세서는 표준 서식(①Seller ~ ⑩Signed by)을 그대로 따릅니다."""

    shipment = create_shipment()
    document_service.generate_documents(shipment)
    doc = document_service.get_document(shipment, "packing_list")

    # ①~⑥ 왼쪽 칸, ⑦~⑨ 오른쪽 칸
    assert {"exporter", "consignee", "etd", "vessel_or_flight", "pol", "pod",
            "doc_no", "doc_date", "buyer", "other_references"} <= set(doc.data)
    # 예전 주문 서식의 칸은 남아 있지 않습니다.
    assert not {"order_no", "packed_by", "shipped_via", "attention"} & set(doc.data)
    assert doc.data["exporter"] == shipment.exporter_name
    assert doc.data["signed_by"] == shipment.exporter_name

    labels = {f["key"]: f["label"] for f in document_service.document_view(doc)}
    assert labels["exporter"].endswith("Seller")
    assert labels["pol"].endswith("From") and labels["pod"].endswith("To")

    items = document_service.document_items(doc)
    assert [c["label"] for c in items["columns"]] == [
        "Shipping Marks", "No. & kind of packages", "Goods description",
        "Quantity or net weight", "Gross Weight", "Measurement"]
    assert len(items["rows"]) == len(shipment.cargos)
    first = items["rows"][0]
    assert first["total_weight"] == shipment.cargos[0].total_weight_kg
    assert first["measurement"] == shipment.cargos[0].total_cbm
    # ⑧칸은 "수량 또는 순중량"입니다.
    cargo = shipment.cargos[0]
    assert first["net_quantity"] == (f"{cargo.net_weight_kg} kg" if cargo.net_weight_kg is not None
                                     else f"{cargo.quantity} CARTON")


def test_item_tables_cover_every_document_that_lists_goods(create_shipment):
    """품목을 줄로 적는 서식은 모두 표를 갖습니다. 나머지는 표가 없습니다."""

    shipment = create_shipment()
    document_service.generate_documents(shipment)
    with_items = {"commercial_invoice", "packing_list", "proforma_invoice",
                  "shipping_instruction", "booking_request"}
    for doc_type in with_items:
        items = document_service.document_items(document_service.get_document(shipment, doc_type))
        assert items and items["rows"], doc_type


def test_item_cells_can_be_edited(create_shipment):
    """표의 칸도 서류 화면에서 고칠 수 있어야 합니다."""

    shipment = create_shipment()
    document_service.generate_documents(shipment)
    document_service.update_document(shipment, "packing_list", {"item-0-shipping_marks": "N/M"})
    rows = document_service.get_document(shipment, "packing_list").data["items"]
    assert rows[0]["shipping_marks"] == "N/M"
    # 표에 없는 칸 이름은 무시합니다.
    document_service.update_document(shipment, "packing_list", {"item-9-quantity": "1"})
    assert len(document_service.get_document(shipment, "packing_list").data["items"]) == len(rows)


def test_dangerous_goods_are_declared_on_shipping_documents(create_shipment):
    """위험물은 선사에 신고해야 하므로 선적 서류에 UN번호·급·포장등급이 들어갑니다."""

    shipment = create_shipment(cargo={
        "product_description": "페인트", "hs_code": "3208100000", "package_type": "drum",
        "quantity": 20, "length_cm": 50, "width_cm": 50, "height_cm": 60,
        "weight_per_package_kg": 40, "is_dangerous": True, "un_number": "UN1263",
        "dg_class": "3", "proper_shipping_name": "PAINT", "packing_group": "II"})
    document_service.generate_documents(shipment)

    for doc_type in ("booking_request", "shipping_instruction"):
        declared = document_service.get_document(shipment, doc_type).data["dangerous_goods"]
        assert declared == "UN1263 CLASS 3 PG II PAINT", doc_type

    # 위험물이 아니면 빈칸입니다.
    plain = create_shipment()
    document_service.generate_documents(plain)
    assert document_service.get_document(plain, "booking_request").data["dangerous_goods"] == ""


def test_bill_of_lading_is_not_a_document_the_exporter_writes():
    """B/L은 선사가 발행합니다. 수출자가 작성하는 서류 목록에 있으면 안 됩니다."""

    from app.models.document import DOCUMENT_TYPES

    assert "bl_draft" not in DOCUMENT_TYPES
    assert list(DOCUMENT_TYPES) == ["commercial_invoice", "packing_list", "proforma_invoice",
                                    "shipping_instruction", "booking_request"]


def test_stale_documents_are_rebuilt_with_the_current_form(create_shipment):
    """서식을 바꾸면 이미 만든 문서도 새 서식으로 다시 만들어야 합니다.

    예전에는 "이미 있음"으로 건너뛰어 화면에서 양식이 그대로인 것처럼 보였습니다.
    """

    shipment = create_shipment()
    document_service.generate_documents(shipment)
    doc = document_service.get_document(shipment, "packing_list")

    # 예전 서식으로 만들어진 문서를 흉내 냅니다. (칸 구성이 지금과 다름)
    doc.data = {"order_no": "PL-OLD", "consignee": "ABC", "remarks_old": "사람이 적은 메모",
                "shipping_marks": "사람이 적은 화인"}
    document_service.shipment_repository.commit()
    assert document_service.is_outdated(doc) is True

    document_service.generate_documents(shipment)          # 덮어쓰기 없이 자동 작성
    rebuilt = document_service.get_document(shipment, "packing_list")
    assert set(rebuilt.data) - {"items"} == set(document_service.DOCUMENT_FIELDS["packing_list"])
    assert rebuilt.data["items"]                           # 품목 표가 생깁니다.
    # 새 서식에도 있는 칸이면 사람이 적은 값을 살립니다.
    assert rebuilt.data["shipping_marks"] == "사람이 적은 화인"
    assert "order_no" not in rebuilt.data                  # 새 서식에 없는 칸은 버립니다.
    assert "remarks_old" not in rebuilt.data

    # 최신 서식이면 다시 만들지 않습니다.
    assert document_service.is_outdated(rebuilt) is False
    assert document_service.generate_documents(shipment) == []


def test_validation_ignores_boxes_the_current_form_does_not_show(create_shipment):
    """예전 문서에 남은 칸까지 비교하면 고칠 수 없는 불일치가 보고됩니다."""

    shipment = create_shipment()
    document_service.generate_documents(shipment)
    doc = document_service.get_document(shipment, "commercial_invoice")
    # 지금 서식의 상업송장에는 없는 칸에 틀린 값이 남아 있어도 지적하지 않습니다.
    doc.data["total_cbm"] = 999.0
    document_service.shipment_repository.commit()
    assert document_service.check_documents(shipment)["status"] == "passed"


def test_numbers_can_be_typed_with_thousands_separators(create_shipment):
    """화면이 48,000.00으로 보여주므로 그대로 옮겨 적어도 저장돼야 합니다."""

    shipment = create_shipment()
    document_service.generate_documents(shipment)
    document_service.update_document(shipment, "commercial_invoice", {"gross_weight_kg": "48,000.00"})
    assert document_service.get_document(shipment, "commercial_invoice").data["gross_weight_kg"] == 48000.0


def test_document_sections_follow_the_printed_form(create_shipment):
    """서류 화면은 칸을 서식 순서대로 묶어 보여줍니다."""

    shipment = create_shipment()
    document_service.generate_documents(shipment)
    sections = document_service.document_sections(
        document_service.get_document(shipment, "packing_list"))

    # 표준 서식은 왼쪽 ①~⑥과 오른쪽 ⑦~⑨을 나란히 인쇄합니다.
    assert [f["key"] for f in sections[0]["fields"]] == [
        "exporter", "doc_no", "exporter_address", "doc_date",
        "consignee", "buyer", "consignee_address", "other_references"]
    assert [f["key"] for f in sections[1]["fields"]] == ["etd", "vessel_or_flight", "pol", "pod"]
    # 품목 표 자리가 중간에 한 번 들어갑니다.
    assert [s["items"] for s in sections].count(True) == 1
    assert sections[-1]["fields"][-1]["key"] == "signed_by"


def test_edit_creates_warning_and_blocks_finalize(create_shipment):
    shipment = create_shipment()
    document_service.generate_documents(shipment)
    document_service.update_document(shipment, "shipping_instruction", {"quantity": "480"})
    result = document_service.validate_shipment_documents(shipment)
    assert result["status"] == "warning"
    assert [(f["document"], f["field"]) for f in result["findings"]] == [("shipping_instruction", "quantity")]
    with pytest.raises(ValidationError):
        document_service.finalize_document(shipment, "shipping_instruction")
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
