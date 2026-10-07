"""중고품 처리 — 서류에 (USED)를 찍고 수입국 규제를 짚습니다. 신품은 그대로여야 합니다."""

import pytest

from app.processors import export_requirements, used_goods
from app.services import document_service, required_docs_service


def test_중고_규칙이_수출요건에_붙는다():
    assert any(i["key"] == "used" for i in export_requirements.check("8429.52", is_used=True))
    assert not any(i["key"] == "used" for i in export_requirements.check("8429.52"))


def test_나라별_중고_안내와_일반_안내():
    assert used_goods.notes_for("CL") and "허위 신고" in used_goods.GENERIC
    assert used_goods.notes_for("ZZ") == []


@pytest.mark.parametrize("condition, label", [("used", "USED"), ("unspecified", "USED"),
                                               ("refurbished", "REFURBISHED"), ("", "")])
def test_서류_품명_표기(condition, label):
    class C:
        product_description = "Excavator"
        used_condition = condition
        used_label = {"used": "USED", "unspecified": "USED", "refurbished": "REFURBISHED"}.get(condition, "")
    assert (f"({label})" in document_service._described(C())) is bool(label)


def test_이미_USED가_적혀_있으면_다시_붙이지_않는다():
    class C:
        product_description = "Used excavator (USED)"
        used_condition = "used"
        used_label = "USED"
    assert document_service._described(C()) == "Used excavator (USED)"


def test_검증기가_중고_값을_받는다():
    from app.validators import ValidationError
    from app.validators.cargo_validator import validate_cargo_handling
    assert validate_cargo_handling({"used_condition": "used"})["used_condition"] == "used"
    assert validate_cargo_handling({})["used_condition"] == ""
    with pytest.raises(ValidationError):
        validate_cargo_handling({"used_condition": "new?"})


@pytest.fixture()
def used_shipment(app, create_shipment, cargo_input):
    from app.models import Shipment
    create_shipment(cargo={**cargo_input, "used_condition": "used"})
    with app.app_context():
        yield Shipment.query.order_by(Shipment.id.desc()).first()


def test_중고로_만든_건은_서류_품명에_USED가_찍힌다(used_shipment):
    data = document_service.build_reference(used_shipment, "commercial_invoice")
    assert "(USED)" in data["product_description"]
    assert any("(USED)" in str(row.get("description", "")) for row in
               document_service.build_items(used_shipment, "packing_list"))


def test_중고로_만든_건은_필수서류_목록에_중고품_행이_생긴다(used_shipment):
    rows = required_docs_service.collect(used_shipment, use_ai=False)
    items = rows.get("items") or rows.get("documents") or []
    assert any("중고품" in str(row.get("title")) for row in items)


def test_신품은_표기도_행도_없다(app, create_shipment):
    from app.models import Shipment
    create_shipment()
    with app.app_context():
        shipment = Shipment.query.order_by(Shipment.id.desc()).first()
        assert "(USED)" not in document_service.build_reference(shipment, "commercial_invoice")["product_description"]
        rows = required_docs_service.collect(shipment, use_ai=False)
        items = rows.get("items") or rows.get("documents") or []
        assert not any("중고품" in str(row.get("title")) for row in items)


def test_포장명세서에_카톤_번호와_치수가_이어진다(app, create_shipment, cargo_input):
    from app.models import Shipment
    create_shipment(cargo={**cargo_input, "quantity": 12, "net_weight_kg": 50, "length_cm": 50, "width_cm": 40, "height_cm": 30})
    with app.app_context():
        shipment = Shipment.query.order_by(Shipment.id.desc()).first()
        rows = document_service.build_items(shipment, "packing_list")
        assert rows[0]["carton_no"] == "1–12" and rows[0]["dimensions"] == "50×40×30"


def test_치수를_모르면_치수_칸을_비운다():
    class C:
        length_cm = None
        width_cm = 40
        height_cm = 30
    assert document_service._dimensions(C()) == ""
