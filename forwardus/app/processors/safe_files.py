"""올린 파일의 '폭탄' 방어 — 작은 파일이 서버 메모리를 다 쓰게 만드는 것을 읽기 **전에** 막습니다.

전수 점검 3회차(관리자)에서 실제로 재현된 것:
  · 9000×9000 PNG 는 258KB 인데 불러오면 RSS 가 88MB → 631MB(Pillow 기본 한도는 경고만 하고 읽습니다).
  · 200MB 짜리 word/document.xml 을 넣은 240KB .docx 는 RSS 308MB → 931MB, 추출 글자 2억 자.
Render 512MB·일꾼 1개에서 이런 파일 하나가 서비스 전체를 내립니다. 가입한 누구나 올릴 수 있는 길입니다.

그래서 **크기를 먼저 보고**(그림은 헤더의 가로×세로, docx 는 zip 목록의 풀린 크기) 넘으면 읽지 않습니다.
"""

from __future__ import annotations

import io
import zipfile

MAX_IMAGE_PIXELS = 25_000_000          # 약 5000×5000. 150dpi A4 스캔(1240×1754 ≈ 2.2M)의 10배
MAX_DOCX_UNCOMPRESSED = 30 * 1024 * 1024
MAX_TEXT_CHARS = 400_000               # 계약서 점검의 한도(MAX_TEXT)와 같습니다


class UnsafeFile(ValueError):
    """읽으면 위험한 파일. 메시지는 이용자에게 그대로 보여 줘도 됩니다."""


def _tighten_pillow() -> None:
    """Pillow 는 한도의 2배를 넘어야 막습니다(그 전엔 경고). 한도를 우리 값의 2배로 낮춥니다."""

    from PIL import Image

    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS * 2


def open_image(source):
    """그림을 엽니다. 가로×세로가 한도를 넘으면 **픽셀을 읽지 않고** 거절합니다.

    source — 경로 또는 bytes. 돌려주는 것은 아직 load() 하지 않은 PIL 이미지입니다(with 로 쓰세요).
    """

    from PIL import Image

    _tighten_pillow()
    image = Image.open(io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else source)
    width, height = image.size
    if width * height > MAX_IMAGE_PIXELS:
        image.close()
        raise UnsafeFile(f"그림이 너무 큽니다({width:,}×{height:,}픽셀). 5,000×5,000 이하로 줄여 다시 올려 주세요.")
    return image


def render_page(page, resolution: int = 150):
    """pdfplumber 쪽을 그림으로. 쪽 크기가 비정상으로 크면 **해상도를 낮춰** 한도 안에서 그립니다.

    MediaBox 가 14400×14400pt 인 PDF 를 150dpi 로 그리면 3만×3만 픽셀(9억)입니다 — 올린 PDF 한 장이
    메모리를 모두 쓸 수 있었습니다(전수 점검 3회차에서 코드로 확인). 평범한 A4 는 그대로입니다.
    """

    width_pt, height_pt = float(page.width or 0), float(page.height or 0)
    if width_pt <= 0 or height_pt <= 0:
        raise UnsafeFile("PDF 쪽 크기를 알 수 없습니다.")
    pixels = (width_pt * resolution / 72) * (height_pt * resolution / 72)
    if pixels > MAX_IMAGE_PIXELS:
        resolution = int((MAX_IMAGE_PIXELS / (width_pt * height_pt)) ** 0.5 * 72)
        if resolution < 20:                               # 너무 커서 글자를 읽을 수 없는 쪽
            raise UnsafeFile("PDF 쪽 크기가 너무 큽니다. 일반 용지(A4) 크기로 다시 저장해 올려 주세요.")
    return page.to_image(resolution=resolution).original.copy()


def check_docx(source) -> None:
    """docx(zip)가 풀리면 너무 커지는지 zip 목록에서 먼저 봅니다. 위험하면 UnsafeFile."""

    try:
        archive = zipfile.ZipFile(io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else source)
    except zipfile.BadZipFile:
        return                                    # 열 수 없는 파일은 읽는 쪽이 따로 거절합니다
    with archive:
        total = sum(info.file_size for info in archive.infolist())
        if total > MAX_DOCX_UNCOMPRESSED or any(info.file_size > MAX_DOCX_UNCOMPRESSED for info in archive.infolist()):
            raise UnsafeFile("Word 파일이 풀리면 너무 큽니다(압축 폭탄으로 보입니다). 내용을 다시 저장해 올려 주세요.")


def clip(text: str) -> str:
    return text[:MAX_TEXT_CHARS]
