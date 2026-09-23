"""Document generation and cross-document validation tests."""

from __future__ import annotations

import pytest

from app.processors.document_validator import validate_documents
from app.services import document_service
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


LABELS = {"commercial_invoice": "상업송장", "packing_list": "패킹리스트",
          "shipping_instruction": "선적지시서"}


def _cross(documents, reference=None, fields=("quantity", "net_weight_kg")):
    """서류끼리만 맞대어 봅니다. (기준값은 일부러 비워 둡니다)"""

    shown = {doc_type: list(fields) for doc_type in documents}
    return validate_documents(documents, reference or {}, LABELS, shown)


def test_기준값이_없어도_서류끼리_다르면_잡는다():
    """Shipment에 안 적은 칸은 기준값 대조에서 통째로 빠집니다.

    그래도 상업송장과 패킹리스트의 순중량은 서로 같아야 합니다. 예전에는
    서류마다 다른 값이 적혀 있어도 전부 통과였습니다.
    """

    result = _cross({"commercial_invoice": {"net_weight_kg": 900},
                     "packing_list": {"net_weight_kg": 880}})
    assert result["status"] == "warning"
    assert len(result["findings"]) == 1
    assert result["findings"][0]["kind"] == "cross"


def test_한_서류만_다르면_나머지와_다르다고_알린다():
    result = _cross({"commercial_invoice": {"quantity": 500},
                     "packing_list": {"quantity": 500},
                     "shipping_instruction": {"quantity": 480}})
    finding = result["findings"][0]
    assert finding["document"] == "shipping_instruction"
    assert finding["message"] == "선적지시서의 Quantity가 나머지 서류와 일치하지 않습니다."
    assert finding["actual"] == 480          # 이 서류에 적힌 값
    assert finding["expected"] == 500        # 나머지 서류가 적은 값


def test_두_서류가_다르면_둘을_맞대어_알린다():
    """둘뿐이면 어느 쪽이 맞는지 알 수 없습니다. "나머지"가 없습니다."""

    result = _cross({"commercial_invoice": {"quantity": 500},
                     "packing_list": {"quantity": 480}})
    assert result["findings"][0]["message"] == (
        "상업송장과 패킹리스트의 Quantity가 일치하지 않습니다. 다시 확인해주세요.")


def test_셋이_제각각이면_저마다_맞대어_알린다():
    result = _cross({"commercial_invoice": {"net_weight_kg": 100},
                     "packing_list": {"net_weight_kg": 200},
                     "shipping_instruction": {"net_weight_kg": 300}})
    assert [f["document"] for f in result["findings"]] == ["packing_list", "shipping_instruction"]
    for finding in result["findings"]:
        assert finding["message"].startswith("상업송장과 ")
        assert finding["message"].endswith("일치하지 않습니다. 다시 확인해주세요.")


def test_모든_서류가_같으면_통과한다():
    result = _cross({"commercial_invoice": {"quantity": 500, "net_weight_kg": 900},
                     "packing_list": {"quantity": 500, "net_weight_kg": 900},
                     "shipping_instruction": {"quantity": 500, "net_weight_kg": 900}})
    assert result["status"] == "passed"
    assert result["findings"] == []


def test_기준값이_이미_잡은_자리는_두_번_알리지_않는다():
    """같은 자리를 두 줄로 알리면 고칠 곳이 둘인 줄 압니다."""

    result = validate_documents(
        {"commercial_invoice": {"quantity": 500},
         "packing_list": {"quantity": 500},
         "shipping_instruction": {"quantity": 480}},
        {"quantity": 500}, LABELS, {d: ["quantity"] for d in LABELS})
    assert len(result["findings"]) == 1
    assert result["findings"][0]["kind"] != "cross"      # 기준값 쪽이 더 쓸모 있습니다.


def test_조사를_얼버무리지_않는다():
    """"Quantity이(가)"처럼 괄호로 미루지 않습니다. (processors/korean)"""

    result = validate_documents({"commercial_invoice": {"quantity": 480}},
                                {"quantity": 500}, LABELS, {"commercial_invoice": ["quantity"]})
    message = result["findings"][0]["message"]
    assert "이(가)" not in message
    assert message == "상업송장의 Quantity가 Shipment 기준값과 다릅니다."


def test_빈_칸은_서류끼리_맞대는_대상이_아니다():
    """안 적은 것은 "다르다"가 아니라 "아직 안 적었다"입니다."""

    result = _cross({"commercial_invoice": {"quantity": 500},
                     "packing_list": {"quantity": ""}})
    assert result["status"] == "passed"      # 기준값이 없으니 빈 칸도 지적하지 않습니다.


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


def test_packing_list_uses_the_order_form_with_one_row_per_item(create_shipment):
    """포장명세서는 지정받은 주문 서식(ORDER # / SHIPPED TO / 품목표)을 씁니다."""

    shipment = create_shipment(cargo=[
        {"product_description": "샴푸", "package_type": "carton", "quantity": 100,
         "length_cm": 40, "width_cm": 30, "height_cm": 25, "weight_per_package_kg": 12},
        {"product_description": "화장품 세트", "package_type": "carton", "quantity": 30,
         "length_cm": 60, "width_cm": 40, "height_cm": 40, "weight_per_package_kg": 18},
    ])
    document_service.generate_documents(shipment)
    doc = document_service.get_document(shipment, "packing_list")

    assert {"order_no", "date_ordered", "customer_order_no", "date_shipped", "attention",
            "shipped_via", "container_no", "invoice_no", "comments", "packed_by"} <= set(doc.data)
    assert doc.data["order_no"] == shipment.shipment_id
    assert doc.data["packed_by"] == shipment.exporter_name
    assert doc.data["invoice_no"] == f"CI-{shipment.shipment_id}"

    items = document_service.document_items(doc)
    assert [c["label"] for c in items["columns"]] == [
        "ITEM NUMBER", "QUANTITY", "SHIPPED", "BACKORDERED", "DESCRIPTION",
        "UNIT WEIGHT", "TOTAL WEIGHT"]
    # 품목을 두 개 넣으면 줄도 두 줄입니다.
    assert len(items["rows"]) == 2
    assert [row["description"] for row in items["rows"]] == ["샴푸", "화장품 세트"]
    assert [row["quantity"] for row in items["rows"]] == [100, 30]
    assert [row["total_weight"] for row in items["rows"]] == [1200.0, 540.0]
    assert all(row["shipped"] == row["quantity"] and row["backordered"] == 0
               for row in items["rows"])
    assert "order #" in items["note"]


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
    document_service.update_document(shipment, "packing_list", {"item-0-backordered": "5"})
    rows = document_service.get_document(shipment, "packing_list").data["items"]
    assert rows[0]["backordered"] == "5"
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
    doc.data = {"doc_no": "PL-OLD", "consignee": "ABC", "remarks_old": "사람이 적은 메모",
                "comments": "사람이 적은 메모"}
    document_service.shipment_repository.commit()
    assert document_service.is_outdated(doc) is True

    document_service.generate_documents(shipment)          # 덮어쓰기 없이 자동 작성
    rebuilt = document_service.get_document(shipment, "packing_list")
    assert set(rebuilt.data) - {"items"} == set(document_service.DOCUMENT_FIELDS["packing_list"])
    assert rebuilt.data["items"]                           # 품목 표가 생깁니다.
    # 새 서식에도 있는 칸이면 사람이 적은 값을 살립니다.
    assert rebuilt.data["comments"] == "사람이 적은 메모"
    assert "doc_no" not in rebuilt.data                    # 새 서식에 없는 칸은 버립니다.
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

    # 첫 묶음은 ORDER # / DATE, 그다음이 SHIPPED TO입니다.
    assert [f["key"] for f in sections[0]["fields"]] == ["order_no", "doc_date"]
    assert sections[1]["title"] == "SHIPPED TO"
    assert "order #" in sections[1]["note"]
    # 품목 표 자리가 중간에 한 번 들어갑니다.
    assert [s["items"] for s in sections].count(True) == 1
    assert sections[-1]["fields"][-1]["key"] == "packed_by"


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


def test_확정한_서류도_고칠_수_있고_고치면_확정이_풀린다(create_shipment):
    """확정하면 잠기던 것을 열었습니다.

    확정 뒤에 바이어가 주소 한 줄을 고쳐 달라고 하는 일이 잦습니다. 그때마다
    서류를 새로 만들지 않아도 되게 합니다. 대신 고친 서류는 확정이 풀려
    (generated) 다시 검증을 거쳐야 확정됩니다. 고친 내용이 다른 서류와
    어긋난 채로 "확정"이라고 적혀 있는 편이 더 위험합니다.
    """

    shipment = create_shipment()
    document_service.generate_documents(shipment)
    document_service.validate_shipment_documents(shipment)
    assert document_service.finalize_document(shipment, "commercial_invoice").status == "final"

    document_service.update_document(shipment, "commercial_invoice", {"remarks": "주소 수정"})

    document = document_service.get_document(shipment, "commercial_invoice")
    assert document.data["remarks"] == "주소 수정"     # 고친 값이 그대로 들어갑니다.
    assert document.status == "generated"              # 확정이 풀렸습니다.
    with pytest.raises(ValidationError):
        document_service.finalize_document(shipment, "commercial_invoice")

    # 다시 검증하면 확정할 수 있습니다.
    document_service.validate_shipment_documents(shipment)
    assert document_service.finalize_document(shipment, "commercial_invoice").status == "final"


def test_확정한_서류는_다시_만들기로_풀리지_않는다(create_shipment):
    """확정을 푸는 일은 사람이 그 서류를 고칠 때만 일어나야 합니다.

    고쳐서 풀리는 것(update_document)은 사용자가 방금 한 일이라 알고
    있습니다. 그런데 "다시 작성"이나 서식 변경으로도 풀리면, 사용자는
    확정해 둔 줄 알고 있는데 내용이 달라져 있습니다. 그쪽은 막습니다.
    """

    shipment = create_shipment()
    document_service.generate_documents(shipment)
    document_service.validate_shipment_documents(shipment)
    document_service.finalize_document(shipment, "commercial_invoice")

    invoice = document_service.get_document(shipment, "commercial_invoice")
    # 예전 서식으로 만들어진 확정 문서를 흉내 냅니다. (칸 구성이 지금과 다름)
    invoice.data = {"doc_no": "CI-확정본"}
    document_service.shipment_repository.commit()
    assert document_service.is_outdated(invoice) is True

    # 서식이 달라도 확정한 서류는 다시 만들지 않습니다.
    rebuilt = document_service.generate_documents(shipment)
    assert "commercial_invoice" not in [doc.doc_type for doc in rebuilt]

    # 덮어쓰기를 켜도 마찬가지입니다. (확정 안 한 나머지는 다시 만듭니다)
    forced = document_service.generate_documents(shipment, overwrite=True)
    assert "commercial_invoice" not in [doc.doc_type for doc in forced]
    assert forced, "확정하지 않은 서류는 덮어쓰기로 다시 만들어져야 합니다."

    kept = document_service.get_document(shipment, "commercial_invoice")
    assert kept.status == "final"               # 확정이 그대로입니다.
    assert kept.data == {"doc_no": "CI-확정본"}  # 내용도 그대로입니다.

    # 건너뛴 것을 화면에서 이름으로 알릴 수 있어야 합니다.
    assert document_service.DOCUMENT_TYPES["commercial_invoice"] in \
        document_service.locked_documents(shipment)


def test_확정한_서류를_건너뛰었다고_화면이_알려_준다(client, create_shipment):
    """조용히 건너뛰면 "왜 이 서류만 안 바뀌지"를 알 수 없습니다."""

    shipment = create_shipment()
    document_service.generate_documents(shipment)
    document_service.validate_shipment_documents(shipment)
    document_service.finalize_document(shipment, "commercial_invoice")

    response = client.post(f"/documents/{shipment.shipment_id}/generate",
                           follow_redirects=True)
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "확정한 서류는 그대로 두었습니다" in body
    assert document_service.DOCUMENT_TYPES["commercial_invoice"] in body


def test_확정한_서류의_화면에도_수정_단추가_남는다(client, create_shipment):
    """확정하면 화면에서 [수정]이 사라지던 것을 고쳤습니다."""

    shipment = create_shipment()
    document_service.generate_documents(shipment)
    document_service.validate_shipment_documents(shipment)
    document_service.finalize_document(shipment, "commercial_invoice")
    url = f"/documents/{shipment.shipment_id}/commercial_invoice"

    html = client.get(url).get_data(as_text=True)
    assert "수정하기 (확정 해제)" in html
    assert f"{url}?edit=1" in html

    # 확정된 서류도 편집 모드로 열립니다. (예전에는 보기 모드로 돌아갔습니다)
    editing = client.get(f"{url}?edit=1").get_data(as_text=True)
    assert 'name="remarks"' in editing
    assert "수정 완료 · 저장" in editing
    assert "확정이 풀리고" in editing

    # 저장하면 고친 값이 바로 반영되고 확정이 풀립니다. 다시 그리는 서류도 이 값을 씁니다.
    client.post(url, data={"remarks": "바이어 요청으로 주소 수정"}, follow_redirects=True)
    document = document_service.get_document(shipment, "commercial_invoice")
    assert document.data["remarks"] == "바이어 요청으로 주소 수정"
    assert document.status == "generated"
    assert "바이어 요청으로 주소 수정" in client.get(url).get_data(as_text=True)


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
