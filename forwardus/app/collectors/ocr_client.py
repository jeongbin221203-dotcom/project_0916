"""Tesseract OCR로 사진·스캔 서류의 글자를 읽습니다.

글자가 이미 들어 있는 PDF는 pdfplumber로 뽑는 편이 정확하고 빠릅니다. 여기는
사진(PNG·JPG)과, 글자 없이 그림만 들어 있는 스캔 PDF 페이지를 맡습니다.

Tesseract는 파이썬 패키지가 아니라 따로 설치하는 프로그램입니다. 설치돼 있지
않으면 읽지 않고 그렇다고 알려 줍니다. (없는 글자를 지어내지 않습니다)

설치 위치는 .env의 TESSERACT_CMD로 지정합니다. 비우면 PATH와 Windows 기본
설치 위치(C:\\Program Files\\Tesseract-OCR)에서 찾습니다. 읽을 언어는
TESSERACT_LANG(기본 kor+eng)이고, 설치되지 않은 언어는 빼고 읽습니다.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from app.collectors.base_client import get_config

WINDOWS_DEFAULT_CMD = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
DEFAULT_LANG = "kor+eng"
# 스캔 PDF를 그림으로 바꿀 해상도. OCR은 300dpi 안팎에서 가장 잘 읽습니다.
PDF_RENDER_DPI = 300
# 이보다 좁은 사진은 키워서 읽습니다. 작은 글자는 Tesseract가 놓치기 쉽습니다.
MIN_OCR_WIDTH = 1500
# PDF 페이지를 그림으로 바꿀 때 이보다 넓게는 키우지 않습니다. 지나치게 키우면 흐려집니다.
MAX_RENDER_WIDTH = 2600
# 한국어 모델은 글자마다 띄어 읽는 일이 잦습니다("자 유 판 매"). 한 글자씩 떨어진 한글을 붙입니다.
_SPACED_HANGUL = re.compile(r"(?<![가-힣])(?:[가-힣] ){2,}[가-힣](?![가-힣])")


def tesseract_cmd() -> str:
    """쓸 수 있는 tesseract 실행 파일 경로. 못 찾으면 빈 글자."""

    configured = str(get_config("TESSERACT_CMD", "") or "").strip().strip('"')
    if configured:
        return configured if Path(configured).is_file() or shutil.which(configured) else ""
    found = shutil.which("tesseract")
    if found:
        return found
    return str(WINDOWS_DEFAULT_CMD) if WINDOWS_DEFAULT_CMD.is_file() else ""


def available() -> bool:
    if not tesseract_cmd():
        return False
    try:
        import pytesseract  # noqa: F401
    except ImportError:
        return False
    return True


def _pytesseract():
    import pytesseract

    pytesseract.pytesseract.tesseract_cmd = tesseract_cmd()
    return pytesseract


def languages() -> str:
    """설정한 언어 중 실제로 설치된 것만 골라 'kor+eng' 꼴로 돌려줍니다."""

    wanted = [lang for lang in str(get_config("TESSERACT_LANG", DEFAULT_LANG) or DEFAULT_LANG).split("+") if lang]
    try:
        installed = set(_pytesseract().get_languages(config=""))
    except Exception:
        return "+".join(wanted)
    usable = [lang for lang in wanted if lang in installed]
    if usable:
        return "+".join(usable)
    return "eng" if "eng" in installed else "+".join(wanted)


def image_to_text(image) -> str:
    """PIL 그림 한 장에서 글자를 읽습니다."""

    from PIL import ImageOps

    # 흑백으로 바꾸고, 너무 작은 사진은 키워서 읽습니다. 스캔 서류가 더 잘 읽힙니다.
    gray = ImageOps.grayscale(image)
    if gray.width < MIN_OCR_WIDTH:
        ratio = MIN_OCR_WIDTH / gray.width
        gray = gray.resize((MIN_OCR_WIDTH, round(gray.height * ratio)))
    return tidy(_pytesseract().image_to_string(gray, lang=languages()))


def tidy(text: str) -> str:
    """OCR 결과 다듬기: 한 글자씩 떨어진 한글을 붙이고 빈 줄을 줄입니다."""

    text = _SPACED_HANGUL.sub(lambda match: match.group(0).replace(" ", ""), text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def read_image(path: Path) -> str:
    from PIL import Image, ImageOps

    with Image.open(path) as image:
        # 휴대폰 사진은 회전 정보만 달고 옵니다. 바로 세워서 읽습니다.
        return image_to_text(ImageOps.exif_transpose(image))


def read_pdf_page(path: Path, index: int) -> str:
    """PDF의 한 페이지를 그림으로 바꿔 읽습니다(글자 없는 스캔 페이지용)."""

    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(path))
    try:
        page = pdf[index]
        scale = min(PDF_RENDER_DPI / 72, MAX_RENDER_WIDTH / max(page.get_width(), 1))
        bitmap = page.render(scale=scale)
        return image_to_text(bitmap.to_pil())
    finally:
        pdf.close()
