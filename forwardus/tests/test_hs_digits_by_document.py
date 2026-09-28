"""서류마다 HS 자릿수가 다릅니다. (2026-09-28)

왜 나누나
  HS 는 **6자리까지만 세계 공통**입니다. 그 아래는 나라마다 다르고,
  숫자가 같아도 뜻이 다를 수 있습니다.

      한국 HSK  6601.99-2000  = 양산 (Sun umbrellas)
      터키 GTIP 6601.99.20    = 기타 중 캐노피가 직물인 것

  같은 "9920" 인데 하나는 해가리개, 하나는 천 덮개 장우산입니다.
  한국 10자리를 상업송장에 찍어 터키로 보내면, 받는 쪽이 그것을 자기 나라
  코드로 읽어 엉뚱한 세번으로 신고할 수 있습니다.

실무 표준
    수출신고서(한국 세관)  HSK 10자리   6601.91-0000 · 6601.99-9000
    상업송장(바이어·터키)   HS  6자리    6601.91 · 6601.99
    터키 12자리 확정        현지 관세사·수입자 몫
"""

from __future__ import annotations

import pytest

from app.processors.document_validator import _normalize
from app.services.document_service import hs_for_document


@pytest.mark.parametrize("doc_type", [
    "commercial_invoice", "proforma_invoice", "packing_list",
    "shipping_instruction", "booking_request",
])
def test_바깥으로_나가는_서류는_6자리(doc_type):
    assert hs_for_document("6601910000", doc_type) == "6601.91"


@pytest.mark.parametrize("doc_type", ["", "customs_filing", "export_declaration"])
def test_그_밖에는_10자리_그대로(doc_type):
    """우리 세관에 내는 신고자료는 10자리라야 합니다."""

    assert hs_for_document("6601910000", doc_type) == "6601910000"


def test_외_N건도_앞자리만_줄인다():
    """품목이 여럿이면 "6601910000 외 1건" 으로 옵니다."""

    assert hs_for_document("6601910000 외 1건", "commercial_invoice") == "6601.91 외 1건"


@pytest.mark.parametrize("code", ["", "6601", "660191", "알 수 없음"])
def test_6자리가_안_되면_건드리지_않는다(code):
    """반쪽 부호를 더 자르면 아무 뜻도 없어집니다."""

    got = hs_for_document(code, "commercial_invoice")
    assert got == code or got == "6601.91"


def test_검증기는_6자리로_맞댄다():
    """송장에 6자리를 찍고 기록에 10자리가 있어도 **어긋남이 아닙니다.**

    자릿수가 다르다고 경고를 띄우면 멀쩡한 서류에 빨간 글이 붙고,
    사람이 경고를 안 믿게 됩니다.
    """

    assert _normalize("6601910000", "hs_code") == _normalize("6601.91", "hs_code")
    assert _normalize("6601910000", "hs_code") != _normalize("6601.99", "hs_code")


def test_실제_서류에_6자리가_찍힌다(app, create_shipment):
    """함수가 아니라 **build_reference 가 그 값을 쓰는지**를 봅니다."""

    from app.extensions import db
    from app.services.document_service import build_reference

    shipment = create_shipment()
    shipment.cargos[0].hs_code = "6601910000"
    db.session.commit()

    assert build_reference(shipment, "commercial_invoice")["hs_code"] == "6601.91"
    assert build_reference(shipment, "packing_list")["hs_code"] == "6601.91"
    # 서류 종류를 안 주면 10자리 그대로입니다 (검증 기준값으로 씁니다)
    assert build_reference(shipment)["hs_code"] == "6601910000"


def test_포장명세서_줄의_ITEM_NUMBER_도_6자리(app, create_shipment):
    """포장명세서는 ITEM NUMBER 칸에 HS 를 적습니다. 그 줄도 6자리라야 합니다.

    합계 칸만 고치면 줄에는 10자리가 그대로 남습니다.
    (2026-09-28 되돌림 검사에서 드러남 — 제 시험이 줄을 안 봤습니다)
    """

    from app.extensions import db
    from app.services.document_service import build_items

    shipment = create_shipment()
    shipment.cargos[0].hs_code = "6601910000"
    db.session.commit()

    rows = build_items(shipment, "packing_list")
    assert rows and rows[0]["item_number"] == "6601.91", rows[0]


def test_서류를_실제로_만들면_6자리가_들어간다(app, create_shipment):
    """generate_documents 가 서류 종류를 넘기는지를 봅니다.

    build_reference 를 서류마다 부르지 않으면 한 벌(10자리)이 모든 서류에
    그대로 들어갑니다. 함수만 보면 이 배선을 못 봅니다.
    """

    from app.extensions import db
    from app.services.document_service import generate_documents

    shipment = create_shipment()
    shipment.cargos[0].hs_code = "6601910000"
    db.session.commit()

    made = {doc.doc_type: doc.data for doc in
            generate_documents(shipment, ["commercial_invoice"], overwrite=True)}
    assert made["commercial_invoice"]["hs_code"] == "6601.91", made["commercial_invoice"]
