"""사진 속 계좌번호를 지웁니다. 실제 OCR로 봅니다. (인터넷을 쓰지 않습니다)

이용자가 사진으로 올려도 계좌번호는 OpenAI로 나가면 안 됩니다. 그림에 번호를
그려 넣고, 지운 그림을 OCR로 다시 읽어 번호가 사라졌는지 봅니다. 오퍼 번호·
날짜·금액은 남아 있어야 합니다. 그걸 지우면 AI가 서류를 못 읽습니다.
"""

from __future__ import annotations

import io

import pytest

from app.processors import bank_redaction

pytestmark = pytest.mark.skipif(not bank_redaction.ocr_available(),
                                reason="OCR(Tesseract)이 설치되지 않았습니다")

LINES = [
    "OFFER SHEET",
    "Offer No. DS01227 Date: 2026-12-27",
    "Hair Shampoo 500ml 2,100 PCS US$ 1.80 US$ 3,780.00",
    "TOTAL AMOUNT : USD 11,190.00",
    "Bank: Shinhan Bank, SWIFT SHBKKRSE, A/C 100-200-300400",
    # 이름표 없이 번호만 있는 줄. OCR이 이름표를 놓쳐도 번호만으로 지워야 합니다.
    "110-123-456789",
    "Validity: 2027-01-31",
]


def _page(lines=LINES) -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (1400, 80 + 70 * len(lines)), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", 30)
    for index, line in enumerate(lines):
        draw.text((40, 40 + 70 * index), line, font=font, fill="black")
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def _text_of(png: bytes) -> str:
    from PIL import Image

    rows = bank_redaction._read(Image.open(io.BytesIO(png)))
    return "\n".join(text for _, text, _ in rows)


@pytest.fixture(scope="module")
def masked():
    return bank_redaction.redact_image(_page())


def test_지우기_전에는_번호가_읽힌다():
    """시험 그림이 제대로인지부터. 처음부터 안 읽히면 아래 시험이 의미가 없습니다."""

    before = _text_of(_page()).replace(" ", "")
    assert "100-200-300400" in before and "110-123-456789" in before


def test_계좌번호와_SWIFT가_지워진다(masked):
    after = _text_of(masked["image"])
    digits = "".join(ch for ch in after if ch.isdigit())

    assert "100200300400" not in digits and "110123456789" not in digits
    assert "SHBKKRSE" not in after.replace(" ", "")
    assert masked["found"] >= 3


def test_오퍼_번호와_날짜와_금액은_남는다(masked):
    after = _text_of(masked["image"]).replace(" ", "")

    for kept in ("DS01227", "2026-12-27", "3,780.00", "11,190.00", "2027-01-31"):
        assert kept in after, kept


def test_OCR이_잘못_읽은_숫자_줄은_통째로_지운다():
    """칸을 넓게 띄운 줄은 OCR이 잘못 읽기 쉽습니다. 그 줄에 계좌번호가 있으면
    우리 규칙이 번호를 못 찾아도 지워져야 합니다."""

    garbled = "Hair Shampoo 500ml   2,100 PCS   A/C 100-200-300400   US$ 3,780.00"
    result = bank_redaction.redact_image(_page([garbled]))

    digits = "".join(ch for ch in _text_of(result["image"]) if ch.isdigit())
    assert "300400" not in digits and "100200" not in digits


def test_한글_이름표가_붙은_계좌번호도_지운다():
    """Tesseract는 한글도 읽습니다. "입금계좌 신한은행 …" 줄의 번호가 지워지고 금액은 남습니다."""

    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (1400, 260), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(r"C:\Windows\Fonts\malgun.ttf", 34)
    draw.text((40, 40), "입금계좌 신한은행 110-123-456789", font=font, fill="black")
    draw.text((40, 140), "합계 금액 USD 11,190.00", font=font, fill="black")
    buffer = io.BytesIO()
    image.save(buffer, "PNG")

    result = bank_redaction.redact_image(buffer.getvalue())
    after = _text_of(result["image"]).replace(" ", "")
    assert "110123456789" not in "".join(ch for ch in after if ch.isdigit())
    assert "11,190.00" in after
