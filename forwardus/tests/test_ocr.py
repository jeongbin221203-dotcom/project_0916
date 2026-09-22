"""Tesseract OCR: 사진·스캔 서류 읽기."""

from __future__ import annotations

import io

import pytest

from app.collectors import ocr_client
from app.services import requirement_service


class _Upload:
    def __init__(self, data: bytes, filename: str):
        self.filename = filename
        self.mimetype = "application/octet-stream"
        self._data = data

    def read(self, *_args):
        return self._data


def _png(text: str = "", size=(900, 240)) -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", size, "white")
    if text:
        try:
            font = ImageFont.truetype("arial.ttf", 64)
        except OSError:
            font = ImageFont.load_default()
        ImageDraw.Draw(image).text((30, 70), text, fill="black", font=font)
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def _scanned_pdf() -> bytes:
    """글자 층 없이 그림만 든 PDF(스캔 서류와 같은 모양)."""

    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (600, 800), "white").save(out, format="PDF")
    return out.getvalue()


def _fake_review(calls):
    def review(text, context):
        calls["text"] = text
        return {"success": True, "source": "api", "data": {
            "document_type": "자유판매증명서", "status": "ok", "summary": "어긋난 곳이 없습니다.", "findings": []}}
    return review


def test_photo_is_read_with_ocr_and_sent_for_review(app, create_shipment, monkeypatch):
    """사진 서류는 OCR로 읽은 글자를 AI 대조에 넘깁니다."""

    calls = {}
    monkeypatch.setattr(ocr_client, "available", lambda: True)
    monkeypatch.setattr(ocr_client, "read_image", lambda path: "FREE SALE CERTIFICATE\nShampoo")
    monkeypatch.setattr(requirement_service.ai_client, "review_document", _fake_review(calls))
    with app.app_context():
        shipment = create_shipment()
        document = requirement_service.upload(shipment, _Upload(_png(), "cfs.jpg"), "cosmetic")
        reviewed = requirement_service.analyze(shipment, document.id)
        assert reviewed.review_status == "ok"
        assert "FREE SALE CERTIFICATE" in calls["text"]
        requirement_service.delete_upload(shipment, document.id)


def test_scanned_pdf_page_falls_back_to_ocr(app, create_shipment, monkeypatch):
    """글자 층이 없는 PDF 페이지만 OCR로 다시 읽습니다."""

    calls, pages = {}, []
    monkeypatch.setattr(ocr_client, "available", lambda: True)
    monkeypatch.setattr(ocr_client, "read_pdf_page", lambda path, index: pages.append(index) or "CERTIFICATE OF ORIGIN")
    monkeypatch.setattr(requirement_service.ai_client, "review_document", _fake_review(calls))
    with app.app_context():
        shipment = create_shipment()
        document = requirement_service.upload(shipment, _Upload(_scanned_pdf(), "co.pdf"), "cosmetic")
        requirement_service.analyze(shipment, document.id)
        assert pages == [0]
        assert "CERTIFICATE OF ORIGIN" in calls["text"]
        requirement_service.delete_upload(shipment, document.id)


def test_without_tesseract_the_reason_is_explained(app, create_shipment, monkeypatch):
    """Tesseract가 없으면 지어내지 않고, 설치가 필요하다고 알려 줍니다."""

    monkeypatch.setattr(ocr_client, "available", lambda: False)
    with app.app_context():
        shipment = create_shipment()
        for data, name in ((_png(), "scan.png"), (_scanned_pdf(), "scan.pdf")):
            document = requirement_service.upload(shipment, _Upload(data, name), "cosmetic")
            reviewed = requirement_service.analyze(shipment, document.id)
            assert reviewed.review_status == "failed"
            assert "Tesseract" in reviewed.review_summary and "TESSERACT_CMD" in reviewed.review_summary
            requirement_service.delete_upload(shipment, document.id)


def test_one_failing_page_does_not_lose_the_others(app, monkeypatch, tmp_path):
    """OCR이 한 페이지에서 실패해도 오류로 멈추지 않고 빈 글자로 넘깁니다."""

    def boom(path, index):
        raise RuntimeError("tesseract crashed")

    monkeypatch.setattr(ocr_client, "available", lambda: True)
    monkeypatch.setattr(ocr_client, "read_pdf_page", boom)
    path = tmp_path / "scan.pdf"
    path.write_bytes(_scanned_pdf())
    with app.app_context():
        assert requirement_service.extract_text(path, ".pdf").strip() == ""


def test_languages_keep_only_installed_ones(app, monkeypatch):
    """설정한 언어 중 설치된 것만 씁니다. 한글 자료가 없으면 영어로라도 읽습니다."""

    class FakeTess:
        def __init__(self, installed):
            self.installed = installed

        def get_languages(self, config=""):
            return self.installed

    with app.app_context():
        monkeypatch.setattr(ocr_client, "_pytesseract", lambda: FakeTess(["eng", "kor", "osd"]))
        assert ocr_client.languages() == "kor+eng"
        monkeypatch.setattr(ocr_client, "_pytesseract", lambda: FakeTess(["eng", "osd"]))
        assert ocr_client.languages() == "eng"


def test_wrong_tesseract_path_counts_as_not_installed(app):
    app.config["TESSERACT_CMD"] = r"C:\nowhere\tesseract.exe"
    try:
        with app.app_context():
            assert ocr_client.tesseract_cmd() == ""
            assert ocr_client.available() is False
    finally:
        app.config["TESSERACT_CMD"] = ""


@pytest.mark.skipif(not ocr_client.available(), reason="이 컴퓨터에 Tesseract가 설치돼 있지 않습니다")
def test_real_tesseract_reads_printed_text(app, tmp_path):
    """실제 Tesseract로 그림 속 글자를 읽습니다(설치된 컴퓨터에서만)."""

    path = tmp_path / "invoice.png"
    path.write_bytes(_png("INVOICE 20260922"))
    with app.app_context():
        text = requirement_service.extract_text(path, ".png")
    assert "20260922" in text.replace(" ", "")


def test_tidy_joins_hangul_split_into_single_letters():
    """한국어 모델이 글자마다 띄어 읽은 결과를 붙입니다. 영문·숫자 띄어쓰기는 그대로 둡니다."""

    assert ocr_client.tidy("자 유 판 매 증 명 서 FREE SALE") == "자유판매증명서 FREE SALE"
    assert ocr_client.tidy("수출자 : 포워드어스") == "수출자 : 포워드어스"
    assert ocr_client.tidy("Invoice No. 1 2 3\n\n\n\nEND") == "Invoice No. 1 2 3\n\nEND"
