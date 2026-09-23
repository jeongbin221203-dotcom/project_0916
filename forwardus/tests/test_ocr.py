"""Tesseract OCR — 사진·스캔 서류 읽기와 그림 속 계좌번호 가리기.

규칙은 가짜 OCR 결과로 봅니다(설치 여부와 상관없이 돕니다). 실제 Tesseract가 있으면
한글 이름표까지 읽는지도 봅니다.
"""

from __future__ import annotations

import io

import pytest

from app.processors import bank_redaction, ocr


def _quad(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def _png(width=900, height=200):
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buffer, "PNG")
    return buffer.getvalue()


def _black(png: bytes, box) -> bool:
    """box 안이 까맣게 칠해졌는지. (가운데 한 점을 봅니다)"""

    from PIL import Image

    image = Image.open(io.BytesIO(png)).convert("L")
    x = (box[0] + box[2]) // 2
    y = (box[1] + box[3]) // 2
    return image.getpixel((x, y)) < 40


# --- 그림 속 번호 칠하기 (낱말 자리를 아는 OCR) ------------------------------------------

def test_번호_낱말_자리만_정확히_칠한다(monkeypatch):
    before = [
        (_quad(10, 10, 700, 40), "입금계좌: 신한은행 110-123-456789", 0.95,
         [(_quad(10, 10, 120, 40), "입금계좌:", 0.9), (_quad(130, 10, 260, 40), "신한은행", 0.9),
          (_quad(400, 10, 700, 40), "110-123-456789", 0.95)]),
    ]
    # 칠한 뒤 다시 읽으면 번호가 사라진 줄이 나옵니다. (남아 있으면 줄 전체를 칠합니다)
    after = [(_quad(10, 10, 700, 40), "입금계좌: 신한은행", 0.95, before[0][3][:2])]
    reads = iter([before, after])
    monkeypatch.setattr(bank_redaction, "_read", lambda image: next(reads))

    result = bank_redaction.redact_image(_png())

    assert _black(result["image"], (400, 10, 700, 40))       # 번호는 칠하고
    assert not _black(result["image"], (130, 10, 260, 40))   # 은행 이름은 남깁니다


def test_헷갈린_숫자_낱말만_칠하고_짧은_수량은_남긴다(monkeypatch):
    rows = [
        (_quad(10, 60, 880, 90), "품명 립스틱 (10510) 수량 500 CTNS 단가 USD 12.50 금액 6,250.00", 0.55,
         [(_quad(10, 60, 80, 90), "품명", 0.6), (_quad(200, 60, 320, 90), "(10510)", 0.55),
          (_quad(400, 60, 450, 90), "500", 0.6), (_quad(700, 60, 880, 90), "6,250.00", 0.95)]),
    ]
    monkeypatch.setattr(bank_redaction, "_read", lambda image: rows)

    result = bank_redaction.redact_image(_png())

    assert _black(result["image"], (200, 60, 320, 90))       # 헷갈린 5자리
    assert not _black(result["image"], (400, 60, 450, 90))   # 수량 500은 계좌 조각일 수 없음
    assert not _black(result["image"], (700, 60, 880, 90))   # 자신 있게 읽은 금액
    assert not _black(result["image"], (10, 60, 80, 90))     # 품명 이름표


def test_은행_줄이면_짧은_헷갈린_숫자도_칠한다(monkeypatch):
    rows = [
        (_quad(10, 110, 700, 140), "A/C 110 123 4567", 0.5,
         [(_quad(10, 110, 60, 140), "A/C", 0.9), (_quad(100, 110, 160, 140), "110", 0.5),
          (_quad(200, 110, 260, 140), "123", 0.5), (_quad(300, 110, 400, 140), "4567", 0.5)]),
    ]
    monkeypatch.setattr(bank_redaction, "_read", lambda image: rows)

    result = bank_redaction.redact_image(_png())

    for box in ((100, 110, 160, 140), (200, 110, 260, 140), (300, 110, 400, 140)):
        assert _black(result["image"], box), box


def test_낱말_자리를_모르는_OCR은_예전처럼_줄째_칠한다(monkeypatch):
    rows = [(_quad(10, 10, 700, 40), "H 00 00 0 0 00 1234", 0.6)]      # RapidOCR 모양 (3칸)
    monkeypatch.setattr(bank_redaction, "_read", lambda image: rows)

    result = bank_redaction.redact_image(_png())

    assert _black(result["image"], (10, 10, 700, 40))


def test_Tesseract가_있으면_그것을_먼저_쓴다(monkeypatch):
    monkeypatch.setattr(ocr, "available", lambda: True)
    monkeypatch.setattr(ocr, "read_lines", lambda image: ["tesseract"])
    monkeypatch.setattr(bank_redaction, "_read_rapidocr", lambda image: ["rapidocr"])

    assert bank_redaction.ocr_available()
    assert bank_redaction._read(None) == ["tesseract"]


# --- 사진·스캔 서류 읽기 ---------------------------------------------------------------

def test_사진_서류는_OCR_글자를_가린_뒤_그림과_함께_넘긴다(monkeypatch):
    from PIL import Image

    from app.services import document_extract_service as extract

    monkeypatch.setattr(extract.ocr, "available", lambda: True)
    monkeypatch.setattr(extract.bank_redaction, "ocr_available", lambda: True)
    monkeypatch.setattr(extract.ocr, "read_text", lambda image: (
        "COMMERCIAL INVOICE\nShipper: SAMPLE CO.\n입금계좌: 신한은행 110-123-456789\n"
        "Beneficiary 1002003004005\nSWIFT: SHBKKRSE"))
    monkeypatch.setattr(extract.bank_redaction, "redact_image",
                        lambda png: {"image": png, "found": 0, "unsure_lines": 0})
    image = Image.new("RGB", (400, 200), "white")

    found = extract.ocr_text("", [image])
    text, urls, notes = extract._protect("", [image], found)

    assert text.startswith(extract.OCR_LABEL)
    assert "Shipper: SAMPLE CO." in text
    # 이름표가 없어도(그림과 같은 기준) 9자리 이상 번호는 가립니다.
    assert "110-123-456789" not in text and "1002003004005" not in text and "SHBKKRSE" not in text
    assert len(urls) == 1 and any("가린 뒤" in note for note in notes)


def test_글자가_있는_PDF는_OCR하지_않는다(monkeypatch):
    from app.services import document_extract_service as extract

    monkeypatch.setattr(extract.ocr, "available", lambda: True)
    monkeypatch.setattr(extract.bank_redaction, "ocr_available", lambda: True)
    monkeypatch.setattr(extract.ocr, "read_text", lambda image: pytest.fail("OCR을 부르면 안 됩니다"))

    assert extract.ocr_text("COMMERCIAL INVOICE " * 5, [object()]) == ""


def test_증빙_사진도_OCR로_읽는다(tmp_path, monkeypatch):
    from PIL import Image

    from app.services import requirement_service

    path = tmp_path / "certificate.png"
    Image.new("RGB", (300, 100), "white").save(path)
    monkeypatch.setattr(ocr, "read_text", lambda image: "CERTIFICATE OF ORIGIN")

    assert requirement_service.extract_text(path, ".png") == "CERTIFICATE OF ORIGIN"


def test_OCR이_없으면_설치가_필요하다고_알린다(monkeypatch):
    from app.services import requirement_service

    monkeypatch.setattr(ocr, "available", lambda: False)
    assert "Tesseract" in requirement_service._unreadable_message(".jpg")
    monkeypatch.setattr(ocr, "available", lambda: True)
    assert "흐리거나" in requirement_service._unreadable_message(".jpg")


# --- 실제 Tesseract ---------------------------------------------------------------------

# 한글 데이터(kor.traineddata)까지 있어야 도는 시험입니다. 영어만 깔린 곳에서는 건너뜁니다.
real = pytest.mark.skipif(not ocr.status()["korean"],
                          reason="Tesseract 한글 데이터(kor)가 없습니다. python data/setup_tessdata.py")


@real
def test_실제_Tesseract가_한글_이름표와_영문_값을_읽는다(app):
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.truetype(r"C:\Windows\Fonts\malgun.ttf", 28)
    image = Image.new("RGB", (1000, 160), "white")
    draw = ImageDraw.Draw(image)
    draw.text((30, 30), "입금계좌: 신한은행", font=font, fill="black")
    draw.text((30, 90), "SWIFT: SHBKKRSE  Amount: USD 6,250.00", font=font, fill="black")

    with app.app_context():
        text = ocr.read_text(image).replace(" ", "")
        status = ocr.status()

    assert status["ready"] and status["korean"]
    assert "계좌" in text and "은행" in text
    assert "SHBKKRSE" in text and "6,250.00" in text
