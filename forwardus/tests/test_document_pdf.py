"""서류 PDF가 사람이 낼 수 있는 물건으로 나오는가.

PDF 는 글자를 **그림으로 그려** 넣습니다. 그래서 글꼴이 없으면 오류가 나지 않고
값만 사라집니다. 이용자는 내려받아 은행·세관에 내고서야 반송으로 압니다.
"""

from __future__ import annotations

import hashlib

import pytest
from PIL import Image, ImageDraw

from app.processors import document_form
from app.services import ServiceError, draft_document_service


DRAFT = {
    "fields": {"exporter": "주식회사 한빛무역", "consignee": "SAMPLE CO., LTD.",
               "incoterms": "FOB", "currency": "USD"},
    "items": [{"description": "제주 감귤 10kg 상자", "quantity": "100",
               "unit_price": "12.50", "amount": "1250.00"}],
}


def _shapes(font, chars):
    """글자마다 그려 본 그림의 지문. 서로 다른 글자가 같은 지문이면 네모입니다."""

    seen = {}
    for ch in chars:
        page = Image.new("L", (40, 40), 255)
        ImageDraw.Draw(page).text((4, 4), ch, font=font, fill=0)
        seen.setdefault(hashlib.md5(page.tobytes()).hexdigest(), []).append(ch)
    return seen


def test_글꼴이_없으면_서류를_만들지_않는다(monkeypatch):
    """한글이 전부 네모로 찍힌 PDF 가 86KB 로 멀쩡히 만들어지고 있었습니다.

    서식의 라벨(⑦수출자·㉕품명)까지 한글이라 서류가 통째로 네모가 됩니다.
    fonts_ready() 는 진작 있었지만 **아무 데서도 부르지 않았습니다.**
    (2026-09-26)
    """

    monkeypatch.setattr(document_form, "FONT_CANDIDATES", ())
    monkeypatch.setattr(document_form, "BOLD_CANDIDATES", ())
    assert not document_form.fonts_ready()

    # 기본 글꼴에는 한글이 없어 서로 다른 글자가 같은 그림 하나로 찍힙니다
    groups = _shapes(document_form._font(16), "주식회사한빛무역감귤")
    assert len(groups) == 1, "기본 글꼴이 한글을 그리게 되었다면 이 시험을 다시 보세요"

    with pytest.raises(ServiceError) as caught:
        draft_document_service.pdf_bytes("commercial_invoice", DRAFT)
    assert caught.value.error_code == "FONT_MISSING"
    assert "글꼴" in str(caught.value)


def test_글꼴이_있으면_한글이_글자대로_찍힌다():
    if not document_form.fonts_ready():
        pytest.skip("이 컴퓨터에 한글 글꼴이 없습니다")
    groups = _shapes(document_form._font(16), "주식회사한빛무역감귤상자부산항")
    assert len(groups) == len("주식회사한빛무역감귤상자부산항")


@pytest.mark.parametrize("kind", list(draft_document_service.FORMS))
def test_서류마다_A4_한_장짜리_PDF가_나온다(kind):
    if not document_form.fonts_ready():
        pytest.skip("이 컴퓨터에 한글 글꼴이 없습니다")
    data = draft_document_service.pdf_bytes(kind, DRAFT)
    assert data.startswith(b"%PDF-")
    assert b"%%EOF" in data[-2048:]
    assert len(data) > 5_000, "너무 작으면 흰 종이일 수 있습니다"
    pages = data.count(b"/Type /Page\n") + data.count(b"/Type /Page ")
    assert pages == 1


def test_여러_서류를_묶으면_쪽_수가_맞는다():
    if not document_form.fonts_ready():
        pytest.skip("이 컴퓨터에 한글 글꼴이 없습니다")
    kinds = list(draft_document_service.FORMS)
    merged = draft_document_service.pdf_documents(
        [{"kind": kind, "data": draft_document_service.render(kind, DRAFT)["data"]}
         for kind in kinds])
    pages = merged.count(b"/Type /Page\n") + merged.count(b"/Type /Page ")
    assert pages == len(kinds)
