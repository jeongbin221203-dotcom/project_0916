"""Shipment 수정·삭제 — 잘못 만든 건을 되돌릴 수 있어야 하고, 남의 건은 못 건드려야 합니다."""

import pytest

from app.extensions import db
from app.models import Shipment, TradeDocument
from app.services import document_service, shipment_service


@pytest.fixture()
def made(app, create_shipment):
    create_shipment()
    with app.app_context():
        shipment = Shipment.query.order_by(Shipment.id.desc()).first()
        document_service.generate_documents(shipment)
        db.session.commit()
        yield shipment


def _form(shipment, **override):
    snap = shipment_service._party_snapshot(shipment)
    return {**snap, **override}


def test_바이어와_수출자를_고치면_서류에도_반영된다(made):
    result = shipment_service.update_shipment(
        made, _form(made, buyer_name="NEW BUYER LLC", exporter_name="NEW EXPORTER CO."))
    assert {"buyer_name", "exporter_name"} <= set(result["changed"])
    invoice = next(d for d in made.documents if d.doc_type == "commercial_invoice")
    assert invoice.data["consignee"] == "NEW BUYER LLC" and invoice.data["exporter"] == "NEW EXPORTER CO."
    assert invoice.status == "generated"


def test_직접_고쳐_둔_칸은_덮어쓰지_않는다(made):
    invoice = next(d for d in made.documents if d.doc_type == "commercial_invoice")
    data = dict(invoice.data)
    data["consignee"] = "HAND EDITED BUYER"
    document_service.document_repository.upsert(made, "commercial_invoice", data, "generated", "manual")
    db.session.commit()
    result = shipment_service.update_shipment(made, _form(made, buyer_name="NEW BUYER LLC"))
    invoice = next(d for d in made.documents if d.doc_type == "commercial_invoice")
    assert invoice.data["consignee"] == "HAND EDITED BUYER"
    assert result["kept"] and all("_" not in item for item in result["kept"])   # 내부 키가 아니라 칸 이름


def test_확정된_서류는_건드리지_않는다(made):
    invoice = next(d for d in made.documents if d.doc_type == "commercial_invoice")
    invoice.status = "final"
    db.session.commit()
    before = invoice.data["consignee"]
    shipment_service.update_shipment(made, _form(made, buyer_name="NEW BUYER LLC"))
    assert next(d for d in made.documents if d.doc_type == "commercial_invoice").data["consignee"] == before


def test_바뀐_게_없으면_아무것도_안_한다(made):
    assert shipment_service.update_shipment(made, _form(made)) == {"changed": [], "documents": [], "kept": []}


def test_서류에_반영하지_않기를_고를_수_있다(made):
    invoice = next(d for d in made.documents if d.doc_type == "commercial_invoice")
    before = invoice.data["consignee"]
    result = shipment_service.update_shipment(made, _form(made, buyer_name="NEW BUYER LLC"), propagate=False)
    assert result["documents"] == []
    assert next(d for d in made.documents if d.doc_type == "commercial_invoice").data["consignee"] == before


def test_같은_바이어를_쓰는_다른_건은_바뀌지_않는다(app, create_shipment):
    create_shipment()
    create_shipment()
    with app.app_context():
        one, two = Shipment.query.order_by(Shipment.id).all()[-2:]
        name_before = two.buyer.name
        shipment_service.update_shipment(one, _form(one, buyer_name="ONLY FIRST CHANGES"))
        assert one.buyer.name == "ONLY FIRST CHANGES" and two.buyer.name == name_before


def test_닫힌_건은_고칠_수_없다(made):
    from app.services import ServiceError
    made.status = "closed"
    with pytest.raises(ServiceError):
        shipment_service.update_shipment(made, _form(made, buyer_name="X"))


def test_영문_칸이_비면_거절한다(made):
    from app.validators import ValidationError
    with pytest.raises(ValidationError):
        shipment_service.update_shipment(made, _form(made, exporter_name=""))


def test_건을_지우면_딸린_것이_모두_사라진다(app, made):
    pk = made.id
    shipment_service.delete_shipment(made)
    assert db.session.get(Shipment, pk) is None
    assert TradeDocument.query.filter_by(shipment_pk=pk).count() == 0


def _owned(create_shipment, email):
    from app.models import User
    shipment = create_shipment()
    shipment.user_id = User.query.filter_by(email=email).one().id
    db.session.commit()
    return shipment


def _member(app, email):
    browser = app.test_client()
    assert browser.post("/auth/signup", data={"email": email, "password": "secret123",
                                              "password_confirm": "secret123"}).status_code == 302
    return browser


def test_화면에서_수정하고_삭제한다(app, create_shipment):
    browser = _member(app, "owner@example.com")
    shipment = _owned(create_shipment, "owner@example.com")
    shipment_id = shipment.shipment_id
    assert browser.get(f"/shipments/{shipment_id}/edit").status_code == 200
    detail = browser.get(f"/shipments/{shipment_id}").get_data(as_text=True)
    assert "당사자 정보 수정" in detail and "건 삭제" in detail

    snap = shipment_service._party_snapshot(shipment)
    response = browser.post(f"/shipments/{shipment_id}/edit", data={**snap, "buyer_name": "EDITED BUYER", "propagate": "1"})
    assert response.status_code == 302
    assert db.session.get(Shipment, shipment.id).buyer.name == "EDITED BUYER"

    # 영문 칸을 비우면 400 과 안내
    bad = browser.post(f"/shipments/{shipment_id}/edit", data={**snap, "exporter_name": ""})
    assert bad.status_code == 400

    # 건 번호를 틀리게 적으면 지워지지 않는다
    browser.post(f"/shipments/{shipment_id}/delete", data={"confirm": "WRONG"})
    assert db.session.get(Shipment, shipment.id) is not None
    assert browser.post(f"/shipments/{shipment_id}/delete", data={"confirm": shipment_id}).status_code == 302
    db.session.expire_all()
    assert Shipment.query.filter_by(shipment_id=shipment_id).first() is None


def test_남의_건은_수정도_삭제도_못_한다(app, create_shipment):
    _member(app, "owner2@example.com")
    shipment = _owned(create_shipment, "owner2@example.com")
    stranger = _member(app, "stranger@example.com")
    snap = shipment_service._party_snapshot(shipment)
    assert stranger.get(f"/shipments/{shipment.shipment_id}/edit").status_code == 404
    assert stranger.post(f"/shipments/{shipment.shipment_id}/edit", data={**snap, "buyer_name": "HACK"}).status_code == 404
    assert stranger.post(f"/shipments/{shipment.shipment_id}/delete",
                         data={"confirm": shipment.shipment_id}).status_code == 404
    db.session.expire_all()
    assert Shipment.query.filter_by(shipment_id=shipment.shipment_id).first() is not None


def test_로그인_없이는_수정_삭제_주소가_막힌다(app, anon_client, create_shipment):
    shipment = create_shipment()
    assert anon_client.get(f"/shipments/{shipment.shipment_id}/edit").status_code in (302, 401, 404)
    assert anon_client.post(f"/shipments/{shipment.shipment_id}/delete",
                            data={"confirm": shipment.shipment_id}).status_code in (302, 401, 404)
    assert Shipment.query.filter_by(shipment_id=shipment.shipment_id).first() is not None


def test_서류_하나를_고치면_다른_서류의_같은_값도_따라간다(made):
    invoice = next(d for d in made.documents if d.doc_type == "commercial_invoice")
    old_consignee = invoice.data["consignee"]
    form = {"consignee": "RENAMED CONSIGNEE LLC"}
    document_service.update_document(made, "commercial_invoice", form, propagate=True)
    docs = {d.doc_type: d for d in made.documents}
    others = [d for t, d in docs.items() if t != "commercial_invoice" and "consignee" in d.data]
    assert others, "consignee 칸이 있는 다른 서류가 있어야 시험이 의미가 있습니다"
    assert all(d.data["consignee"] == "RENAMED CONSIGNEE LLC" for d in others)
    assert old_consignee != "RENAMED CONSIGNEE LLC"


def test_전파를_끄면_다른_서류는_그대로(made):
    document_service.update_document(made, "commercial_invoice", {"consignee": "ONLY HERE"}, propagate=False)
    others = [d for d in made.documents if d.doc_type != "commercial_invoice" and "consignee" in d.data]
    assert others and all(d.data["consignee"] != "ONLY HERE" for d in others)


def test_직접_다르게_적어_둔_칸은_전파가_덮지_않는다(made):
    packing = next(d for d in made.documents if d.doc_type == "packing_list")
    data = dict(packing.data)
    data["consignee"] = "PL SPECIAL NAME"
    document_service.document_repository.upsert(made, "packing_list", data, "generated", "manual")
    db.session.commit()
    document_service.update_document(made, "commercial_invoice", {"consignee": "NEW NAME"}, propagate=True)
    assert next(d for d in made.documents if d.doc_type == "packing_list").data["consignee"] == "PL SPECIAL NAME"


def test_확정_서류가_옛_정보로_남으면_알려_준다(made):
    invoice = next(d for d in made.documents if d.doc_type == "commercial_invoice")
    invoice.status = "final"
    db.session.commit()
    result = shipment_service.update_shipment(made, _form(made, exporter_name="NEW EXPORTER CO."))
    assert result["locked"], "확정 서류가 옛 수출자로 남는다는 알림이 있어야 합니다"


def test_견적_단계_밖이거나_확정_서류가_있으면_지울_수_없다(made):
    assert shipment_service.delete_blocked_reason(made) == ""
    invoice = next(d for d in made.documents if d.doc_type == "commercial_invoice")
    invoice.status = "final"
    assert "확정" in shipment_service.delete_blocked_reason(made)
    invoice.status = "validated"
    made.status = "booked"
    assert "지울 수 없습니다" in shipment_service.delete_blocked_reason(made)
    made.status = "cancelled"
    assert shipment_service.delete_blocked_reason(made) == ""


def test_화면에서도_부킹된_건은_지워지지_않는다(app, create_shipment):
    from app.models import User
    browser = _member(app, "late@example.com")
    shipment = create_shipment()
    shipment.user_id = User.query.filter_by(email="late@example.com").one().id
    shipment.status = "booked"
    db.session.commit()
    browser.post(f"/shipments/{shipment.shipment_id}/delete", data={"confirm": shipment.shipment_id})
    db.session.expire_all()
    assert Shipment.query.filter_by(shipment_id=shipment.shipment_id).first() is not None


def test_너무_긴_주소와_이상한_이메일은_조용히_잘라_저장하지_않는다(made):
    from app.validators import ValidationError
    with pytest.raises(ValidationError):
        shipment_service.update_shipment(made, _form(made, exporter_address="A" * 600))
    with pytest.raises(ValidationError):
        shipment_service.update_shipment(made, _form(made, buyer_email="not-an-email"))
    shipment_service.update_shipment(made, _form(made, buyer_email="buyer@example.com"))


def test_출처_거절_로그에_개행이_들어가지_않는다(app, caplog):
    import logging
    client = app.test_client()
    with caplog.at_level(logging.WARNING):
        client.post("/shipments/x%0d%0a[FAKE]%20INJECTED/delete", headers={"Origin": "http://evil.com"})
    assert all("\n[FAKE]" not in record.getMessage() for record in caplog.records)
