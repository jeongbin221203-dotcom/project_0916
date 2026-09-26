"""Tesseract OCR 언어 데이터(kor·eng)를 data/tessdata에 내려받습니다.

    python data/setup_tessdata.py

Windows 설치본(UB-Mannheim)은 영어만 들어 있고, 한글을 더하려면 Program Files에
써야 해 관리자 권한이 필요합니다. 그래서 프로젝트 안(data/tessdata)에 두고
app/processors/ocr.py가 여기를 먼저 찾게 했습니다. 파일이 커서(약 37MB) git에는 넣지 않습니다.

Tesseract 프로그램은 따로 설치합니다.
    Windows  winget install UB-Mannheim.TesseractOCR
    macOS    brew install tesseract
    Ubuntu   sudo apt install tesseract-ocr
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

LANGS = ("kor", "eng")
# 표준 모델(tessdata). tessdata_fast보다 느리지만 한글 정확도가 낫습니다.
URL = "https://github.com/tesseract-ocr/tessdata/raw/main/{lang}.traineddata"
TARGET = Path(__file__).resolve().parent / "tessdata"


def main() -> int:
    TARGET.mkdir(parents=True, exist_ok=True)
    for lang in LANGS:
        path = TARGET / f"{lang}.traineddata"
        if path.exists() and path.stat().st_size > 1_000_000:
            print(f"{lang}: 이미 있습니다 ({path.stat().st_size / 1e6:.1f} MB)")
            continue
        print(f"{lang}: 내려받는 중…")
        temp = path.with_suffix(".part")
        urllib.request.urlretrieve(URL.format(lang=lang), temp)
        temp.replace(path)
        print(f"{lang}: {path.stat().st_size / 1e6:.1f} MB")
    print(f"완료: {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
