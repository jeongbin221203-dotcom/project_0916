"""이미 만든 건에서 서류 작성 칸을 가져오기. (1차 수정사항 7번)

같은 바이어에게 두 번째로 보내는 일이 흔합니다. 그때마다 주소·품목·조건을
처음부터 다시 적게 하면 오타가 납니다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.services import ServiceError, document_draft_service, document_source_service

STATIC = Path(__file__).parent.parent / "app/static"


def _master(app):
    from app.models import User
    return User.query.filter_by(email=app.config["MASTER_EMAIL"]).one()


def _draft(app, title="2026-10 멕시코 화장품", **draft):
    body = {"quote_title": title,
            "draft": {"buyer_name": "ABC Beauty", "incoterms": "CIF", **draft},
            "documents": [{"kind": "commercial_invoice", "title": "Invoice", "data": {}}]}
    return document_draft_service.save(_master(app), body)


def test_고를_수_있는_건에_작성_중과_지난_건이_함께_나온다(app, create_shipment):
    shipment = create_shipment()
    _draft(app)

    rows = document_source_service.list_sources(_master(app))
    kinds = [row["kind"] for row in rows]
    assert "draft" in kinds and "shipment" in kinds
    # 이어 쓸 초안이 먼저입니다. 고를 일이 더 잦습니다.
    assert kinds.index("draft") < kinds.index("shipment")

    picked = next(row for row in rows if row["kind"] == "shipment")
    assert picked["id"] == shipment.shipment_id
    assert picked["title"] == shipment.project_name
    assert shipment.origin_code in picked["note"]


def test_로그인하지_않았으면_아무것도_고를_수_없다(app):
    assert document_source_service.list_sources(None) == []
    with pytest.raises(ServiceError):
        document_source_service.load(None, "shipment", "SHP-1")


def test_지난_건에서_바이어와_품목을_가져온다(app, create_shipment):
    shipment = create_shipment()
    loaded = document_source_service.load(_master(app), "shipment", shipment.shipment_id)

    fields = loaded["fields"]
    assert fields["incoterms"] == shipment.incoterms
    assert fields["origin_code"] == shipment.origin_code
    assert fields["destination_code"] == shipment.destination_code
    if shipment.buyer:
        assert fields["buyer_name"] == shipment.buyer.name

    assert loaded["items"], "품목도 함께 가져와야 합니다."
    first = loaded["items"][0]
    assert first["product_description"] == shipment.cargos[0].product_description
    # 30.0처럼 소수점이 남으면 사람이 다시 지웁니다.
    assert not first["quantity"].endswith(".0")


def test_지난_건의_견적명은_가져오지_않는다(app, create_shipment):
    """지난 건을 본떠 새로 쓰는 것입니다. 같은 이름이 둘이면 구분이 안 됩니다."""

    shipment = create_shipment()
    loaded = document_source_service.load(_master(app), "shipment", shipment.shipment_id)
    assert "project_name" not in loaded["fields"]


def test_작성_중이던_초안은_이름까지_이어_쓴다(app):
    """초안은 "그 건을 이어 쓰는" 것이라 이름이 그대로 따라옵니다."""

    saved = _draft(app, title="이어 쓸 건", destination_code="MXZLO")
    loaded = document_source_service.load(_master(app), "draft", saved["id"])

    assert loaded["fields"]["project_name"] == "이어 쓸 건"
    assert loaded["fields"]["buyer_name"] == "ABC Beauty"
    assert loaded["fields"]["destination_code"] == "MXZLO"


def test_남의_건은_가져올_수_없다(app, create_shipment):
    from app.models import User
    from app.extensions import db

    shipment = create_shipment()
    stranger = User(email="stranger@example.com", name="남")
    stranger.set_password("password123")
    db.session.add(stranger)
    db.session.commit()

    with pytest.raises(ServiceError):
        document_source_service.load(stranger, "shipment", shipment.shipment_id)
    assert document_source_service.list_sources(stranger) == []


def test_없는_종류를_고르면_거절한다(app):
    with pytest.raises(ServiceError):
        document_source_service.load(_master(app), "buyer", "1")


def test_화면에_고르는_칸이_나오고_값을_받아_온다(app, client, create_shipment):
    shipment = create_shipment()
    _draft(app, title="작성 중이던 건")

    body = client.get("/documents/new").get_data(as_text=True)
    assert "data-doc-source" in body
    assert "이미 만든 건에서 가져오기" in body
    assert "작성 중이던 건" in body and shipment.project_name in body
    # 고른 뒤 값을 받아 올 주소가 화면에 심겨 있어야 합니다.
    assert "sourceUrl" in body

    response = client.get(f"/documents/api/sources/shipment/{shipment.shipment_id}")
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["fields"]["incoterms"] == shipment.incoterms
    assert data["items"]


def test_화면이_고른_건으로_칸을_비우고_다시_채운다():
    """앞서 적어 둔 값이 섞이면 어느 건의 값인지 알 수 없습니다.

    올린 서류로 채울 때와 같은 규칙입니다.
    """

    js = (STATIC / "js/doc_form.js").read_text(encoding="utf-8")
    block = js[js.index("[data-doc-source]"):js.index('window.addEventListener("beforeunload"')]
    assert "clearForm();" in block
    assert "FORWARDUS_DOC_FILL" in block
    # 가져오지 못하면 고른 것을 되돌려 둡니다. 채워진 줄 알면 안 됩니다.
    assert 'sourcePick.value = "";' in block
