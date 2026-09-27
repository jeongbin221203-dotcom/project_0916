"""Tesseract OCR — 사진·스캔 서류에서 글자를 읽습니다. (우리 컴퓨터에서, 인터넷 안 씀)

쓰는 곳
  - 서류 올리기(document_extract_service): 사진·스캔 PDF의 글자를 읽어 AI에게 함께 넘깁니다.
    그림만 볼 때보다 숫자·영문 오탈자가 줄어듭니다.
  - 계좌번호 가리기(bank_redaction): 그림에서 번호 자리를 찾아 칠합니다.
    한글을 읽으므로 "입금계좌" 같은 이름표도 알아봅니다.
  - 증빙 서류 대조(requirement_service): 사진으로 올린 증명서도 읽습니다.

필요한 것
  1. Tesseract 프로그램 (Windows: UB-Mannheim 설치본, winget install UB-Mannheim.TesseractOCR)
     PATH에 없으면 TESSERACT_CMD에 tesseract.exe 경로를 적습니다. 흔한 설치 경로는 알아서 찾습니다.
  2. 언어 데이터 kor·eng (kor.traineddata, eng.traineddata)
     설치본의 tessdata에 없으면 data/tessdata에 두거나 TESSDATA_DIR에 폴더를 적습니다.
  3. pytesseract (requirements.txt)
하나라도 없으면 available()이 False이고, 부르는 쪽은 OCR 없이 동작합니다.
"""

from __future__ import annotations

import os
import shutil
from functools import lru_cache
from pathlib import Path

from app.collectors.base_client import get_config

# 설치 경로를 적지 않았을 때 찾아볼 곳.
COMMON_PATHS = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
    "/usr/bin/tesseract", "/usr/local/bin/tesseract", "/opt/homebrew/bin/tesseract",
)
PROJECT_TESSDATA = Path(__file__).resolve().parents[2] / "data" / "tessdata"
# 무역 서류는 한글 이름표와 영문 값이 섞여 있습니다. 둘 다 읽습니다.
WANTED_LANGS = ("kor", "eng")
# 작은 사진은 키워서 읽습니다. 글자 높이가 20px 아래면 Tesseract가 많이 틀립니다.
MIN_EDGE = 1600
MAX_EDGE = 3200
PAGE_TIMEOUT = 40


def _cmd() -> str:
    configured = str(get_config("TESSERACT_CMD", "") or "").strip()
    if configured and Path(configured).exists():
        return configured
    found = shutil.which("tesseract")
    if found:
        return found
    return next((path for path in COMMON_PATHS if Path(path).exists()), "")


def _tessdata() -> str:
    configured = str(get_config("TESSDATA_DIR", "") or "").strip()
    if configured and Path(configured).is_dir():
        return configured
    if PROJECT_TESSDATA.is_dir() and any(PROJECT_TESSDATA.glob("*.traineddata")):
        return str(PROJECT_TESSDATA)
    return ""


def _use_tessdata(tessdata: str) -> None:
    """언어 데이터 폴더를 TESSDATA_PREFIX로 알려 줍니다.

    --tessdata-dir 인자로 넘기면 Windows에서 따옴표가 경로에 그대로 붙고(pytesseract가
    posix=False로 나눕니다), 따옴표를 빼면 공백 있는 경로가 깨집니다. 환경변수는 둘 다 괜찮습니다.
    """

    if tessdata:
        os.environ["TESSDATA_PREFIX"] = tessdata


def _config_flags(extra: str = "") -> str:
    return f"--oem 1 {extra}".strip()


@lru_cache(maxsize=4)
def _languages(cmd: str, tessdata: str) -> tuple[str, ...]:
    import pytesseract

    pytesseract.pytesseract.tesseract_cmd = cmd
    _use_tessdata(tessdata)
    try:
        installed = set(pytesseract.get_languages())
    except Exception:
        return ()
    return tuple(lang for lang in WANTED_LANGS if lang in installed)


def _setup() -> tuple[str, str] | None:
    """(tesseract 경로, 언어 "kor+eng"). 쓸 수 없으면 None."""

    try:
        import pytesseract
    except ImportError:
        return None
    cmd = _cmd()
    if not cmd:
        return None
    tessdata = _tessdata()
    langs = _languages(cmd, tessdata)
    if not langs:
        return None
    pytesseract.pytesseract.tesseract_cmd = cmd
    _use_tessdata(tessdata)
    return cmd, "+".join(langs)


def available() -> bool:
    return _setup() is not None


def status() -> dict:
    """무엇이 있고 무엇이 빠졌는지. 화면·로그에서 안내할 때 씁니다."""

    try:
        import pytesseract  # noqa: F401
        package = True
    except ImportError:
        package = False
    cmd = _cmd()
    langs = _languages(cmd, _tessdata()) if (package and cmd) else ()
    return {"package": package, "program": cmd, "tessdata": _tessdata(),
            "languages": list(langs), "ready": bool(package and cmd and langs),
            "korean": "kor" in langs}


def _prepare(image):
    """회색조 · 대비 늘리기 · 작은 사진은 키우기. (돌려준 그림, 원래 크기 대비 배율)"""

    from PIL import Image, ImageOps

    picture = image.convert("L")
    picture = ImageOps.autocontrast(picture, cutoff=1)
    longest = max(picture.size)
    scale = 1.0
    if longest < MIN_EDGE:
        scale = min(MIN_EDGE / longest, 3.0)
    elif longest > MAX_EDGE:
        scale = MAX_EDGE / longest
    if scale != 1.0:
        picture = picture.resize((round(picture.width * scale), round(picture.height * scale)),
                                 Image.LANCZOS)
    return picture, scale


def read_text(image) -> str:
    """그림 한 장의 글자. 줄바꿈을 살립니다. 쓸 수 없으면 빈 글자입니다."""

    setup = _setup()
    if not setup:
        return ""
    import pytesseract

    picture, _ = _prepare(image)
    try:
        # psm 3: 쪽 전체를 알아서 나눠 읽습니다. 표·칸이 많은 무역 서류에 맞습니다.
        text = pytesseract.image_to_string(picture, lang=setup[1], config=_config_flags("--psm 3"),
                                           timeout=PAGE_TIMEOUT)
    except Exception:
        return ""
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def read_lines(image) -> list[tuple[list, str, float, list]]:
    """줄마다 (네 꼭짓점, 글자, 자신감 0~1, 낱말 목록). 위→아래, 왼→오른 순서.
    좌표는 원래 그림 기준입니다. 낱말 목록은 [(네 꼭짓점, 글자, 자신감)]입니다.

    계좌번호 가리기(bank_redaction)가 번호 자리를 칠할 때 씁니다. 줄의 자신감은 숫자가 든
    낱말 가운데 가장 낮은 값입니다(숫자가 없으면 1). 한글 낱말은 Tesseract 자신감이 대개
    낮게 나와, 줄 전체로 재면 멀쩡한 품목 줄까지 의심하게 됩니다. 의심스러운 줄에서도
    낱말 목록이 있으면 숫자가 든 그 낱말만 칠할 수 있습니다.
    """

    setup = _setup()
    if not setup:
        return []
    import pytesseract

    picture, scale = _prepare(image)
    try:
        data = pytesseract.image_to_data(picture, lang=setup[1], config=_config_flags("--psm 3"),
                                         output_type=pytesseract.Output.DICT, timeout=PAGE_TIMEOUT)
    except Exception:
        return []
    groups: dict[tuple, dict] = {}
    for index, word in enumerate(data.get("text", [])):
        word = str(word or "").strip()
        if not word:
            continue
        key = (data["block_num"][index], data["par_num"][index], data["line_num"][index])
        left, top = data["left"][index], data["top"][index]
        right, bottom = left + data["width"][index], top + data["height"][index]
        try:
            conf = float(data["conf"][index])
        except (TypeError, ValueError):
            conf = -1.0
        row = groups.setdefault(key, {"words": [], "box": [left, top, right, bottom], "conf": 100.0})
        row["words"].append((_quad(left, top, right, bottom, scale), word,
                             max(0.0, conf) / 100 if conf >= 0 else 1.0))
        box = row["box"]
        row["box"] = [min(box[0], left), min(box[1], top), max(box[2], right), max(box[3], bottom)]
        if conf >= 0 and any(ch.isdigit() for ch in word):
            row["conf"] = min(row["conf"], conf)

    rows = []
    for row in groups.values():
        quad = _quad(*row["box"], scale)
        rows.append((quad, " ".join(text for _, text, _ in row["words"]),
                     max(0.0, row["conf"]) / 100, row["words"]))
    rows.sort(key=lambda row: (round(row[0][0][1] / 12), row[0][0][0]))
    return rows


def _quad(left, top, right, bottom, scale) -> list:
    x0, y0, x1, y1 = (value / scale for value in (left, top, right, bottom))
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
