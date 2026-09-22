"""계좌번호·SWIFT·IBAN을 가립니다. 글자에서도, 그림에서도.

올린 서류는 AI(OpenAI)가 읽습니다. 그 전에 은행 번호를 가려서, 바깥으로는
번호가 나가지 않게 합니다.

글자  은행 이야기를 하는 줄(은행·계좌·A/C·SWIFT…)과 그 아래 두 줄에서
      번호를 [ACCOUNT_1] 같은 표시로 바꿉니다. 돌아온 뒤 은행 칸에만 되돌립니다.

그림  우리 컴퓨터에서 먼저 글자를 읽고(Tesseract OCR, 인터넷 안 씀) 번호 자리를 칠합니다.
      칠한 그림을 한 번 더 읽어 번호가 아직 보이면 그 줄 전체를 칠합니다.
      칠한 그림만 AI에게 보내고, 이용자에게도 그 그림을 보여 줍니다.

      Tesseract는 단어마다 자리를 알려 줍니다. 번호가 들어 있는 단어의 자리를
      그대로 칠하므로 글자 폭을 어림하지 않습니다.

      한글 학습 자료(kor)가 깔려 있으면 한글도 읽지만, 없으면 "입금계좌" 같은
      이름표를 못 봅니다. 그래서 그림에서는 은행이라는 말이 없어도 9자리 이상의
      번호는 모두 지웁니다. (한글을 읽을 때도 같습니다. 이름표를 잘못 읽을 수 있습니다)
      OCR이 설치되어 있지 않으면 그림을 받지 않습니다. 가리지 못한 그림을
      보내는 것보다 받지 않는 것이 낫습니다.

설치  Tesseract 프로그램 + pytesseract 패키지가 둘 다 있어야 합니다.
      Windows: https://github.com/UB-Mannheim/tesseract/wiki 설치 파일
               (기본 자리 C:/Program Files/Tesseract-OCR 은 저절로 찾습니다)
      Linux:   apt-get install tesseract-ocr tesseract-ocr-kor
      다른 자리에 깔았으면 .env에 TESSERACT_CMD=실행 파일 경로 를 적습니다.

한글  학습 자료(kor.traineddata)는 설치 폴더에 넣으려면 관리자 권한이 필요합니다.
      그래서 data/tessdata/ 에 eng·kor 자료를 두면 그것을 먼저 씁니다.
      (TESSDATA_DIR로 다른 폴더를 가리킬 수도 있습니다. git에는 올리지 않습니다)
"""

from __future__ import annotations

import io
import os
import re
import shutil
import threading
from pathlib import Path

# 은행 정보가 나오는 줄을 알아보는 말. 이 줄과 그 아래 BANK_WINDOW 줄 안의 번호를 가립니다.
#
# 처음에는 "A/C 바로 뒤의 번호"만 가렸습니다. 실제 서류를 넣어 보니 거의 다 빠졌습니다.
#   입금계좌 | 신한은행 110-123-456789     (엑셀은 칸을 " | "로 잇고, 은행 이름이 끼어 있음)
#   SWIFT | SHBKKRSE
#   Beneficiary Account                   (번호가 다음 줄에)
#   100-200-300400
# 그래서 이름표 바로 뒤가 아니라 "은행 이야기를 하는 줄 근처"를 봅니다.
_BANK_WORDS = re.compile(r"(?i)bank|account|a/c|acct|\bacc\b|swift|\bbic\b|iban|beneficiary"
                         r"|은행|계좌|예금주|입금")
# 이 말이 있으면 번호가 짧아도(6자리~) 계좌로 봅니다. 없는 은행 줄에서는 9자리부터.
_ACCOUNT_WORDS = re.compile(r"(?i)account|a/c|acct|\bacc\b|iban|계좌")
_SWIFT_WORDS = re.compile(r"(?i)swift|\bbic\b")
BANK_WINDOW = 2
# 숫자 사이에 - . 공백이 끼어도 한 번호로 봅니다. 앞뒤가 글자에 붙어 있으면
# (OS-2026-0917 같은 서류 번호) 번호로 보지 않습니다.
_DIGITS = re.compile(r"(?<![A-Za-z0-9\-./])(\d[\d\-. ]{4,}\d)(?![A-Za-z0-9\-])")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b")
_SWIFT_CODE = re.compile(r"\b[A-Z]{4} ?[A-Z]{2} ?[A-Z0-9]{2}(?: ?[A-Z0-9]{3})?\b")
# 날짜 모양(2026-10-31, 31.10.2026)은 계좌번호가 아닙니다. 은행 줄 바로 아래의
# "Validity: 2026-10-31"까지 가려서 AI가 유효기간을 못 읽은 일이 있었습니다.
_DATE_SHAPE = re.compile(r"(?:19|20)\d{2}[-./]\d{1,2}[-./]\d{1,2}|\d{1,2}[-./]\d{1,2}[-./](?:19|20)\d{2}")
# HS 코드 모양(3305.10-0000)도 번호가 아닙니다. 그림에서는 9자리 이상이면 다 지우므로 따로 뺍니다.
_HS_SHAPE = re.compile(r"\d{4}\.\d{2}(?:[-.]?\d{2,4})?")
LABELLED_DIGITS = 6
LOOSE_DIGITS = 9
TOKEN = re.compile(r"\[(?:ACCOUNT|SWIFT)_\d+\]")


def _is_account_number(candidate: str, minimum: int) -> bool:
    candidate = candidate.strip()
    return (sum(ch.isdigit() for ch in candidate) >= minimum
            and not _DATE_SHAPE.fullmatch(candidate) and not _HS_SHAPE.fullmatch(candidate))


def redact(text: str, *, everywhere: bool = False) -> tuple[str, dict]:
    """계좌번호·SWIFT·IBAN을 [ACCOUNT_1] 같은 표시로 바꿉니다. (가린 글, 표시 → 원래 값)

    은행 이야기를 하는 줄과 그 아래 두 줄만 봅니다. 오퍼 번호·날짜·금액을 가리면
    AI가 그 값을 못 읽기 때문입니다.

    everywhere=True는 그림용입니다. 한글 이름표를 못 읽으니, 은행 줄이 아니어도
    9자리 이상 번호는 가립니다.
    """

    secrets: dict[str, str] = {}

    def token(kind: str, original: str) -> str:
        for key, value in secrets.items():          # 같은 번호는 같은 표시로
            if value == original and key.startswith(f"[{kind}"):
                return key
        key = f"[{kind}_{sum(1 for key in secrets if key.startswith(f'[{kind}')) + 1}]"
        secrets[key] = original
        return key

    lines = str(text or "").split("\n")
    bank_left = account_left = swift_left = 0
    for index, line in enumerate(lines):
        if _BANK_WORDS.search(line):
            bank_left = BANK_WINDOW + 1
        if _ACCOUNT_WORDS.search(line):
            account_left = BANK_WINDOW + 1
        if _SWIFT_WORDS.search(line):
            swift_left = BANK_WINDOW + 1
        if bank_left or everywhere:
            minimum = LABELLED_DIGITS if account_left else LOOSE_DIGITS
            if bank_left:
                line = _IBAN.sub(lambda m: token("ACCOUNT", m.group(0)), line)
            line = _DIGITS.sub(
                lambda m: token("ACCOUNT", m.group(1))
                if _is_account_number(m.group(1), minimum) else m.group(0), line)
            if swift_left:
                line = _SWIFT_CODE.sub(lambda m: token("SWIFT", m.group(0)), line)
        lines[index] = line
        bank_left, account_left, swift_left = (max(0, left - 1) for left in
                                               (bank_left, account_left, swift_left))
    return "\n".join(lines), secrets


def strip_bank_numbers(value: str) -> tuple[str, bool]:
    """은행 칸이 아닌 곳(결제 조건·비고 등)에 섞인 계좌번호를 지웁니다. (지운 글, 지웠는지)

    "T/T to Shinhan Bank A/C 100-200-300400"처럼 결제 조건에 계좌가 들어오는 일이
    흔합니다. 그대로 두면 서버에 저장되고 미리보기에도 가려지지 않습니다.
    가린 표시([ACCOUNT_1])가 들어온 경우도 같이 지웁니다. 되돌리지 않습니다.
    """

    text = str(value or "")
    cleaned, _ = redact(text)
    cleaned = TOKEN.sub("[계좌번호]", cleaned)
    return cleaned, cleaned != text


def restore(value: str, secrets: dict) -> str:
    for token, original in secrets.items():
        value = value.replace(token, original)
    return value


# --- 그림 --------------------------------------------------------------------------

_ocr_lock = threading.Lock()
_ocr_state: dict = {}
# 칠한 자리 둘레로 이만큼 더 칠합니다.
PAD_CHARS = 2
PAD_PIXELS = 4
# OCR이 이보다 자신 없게 읽은 줄에 숫자가 이만큼 있으면 줄 전체를 지웁니다.
# 잘못 읽은 줄에 계좌번호가 있어도 우리 규칙은 번호를 못 찾습니다.
# 품목 줄이 지워질 수 있지만, 번호가 새는 것보다 낫습니다.
# 줄의 자신감은 그 줄에서 가장 자신 없는 단어의 것입니다(Tesseract 0~100 → 0~1).
# 바르게 읽은 줄도 단어 하나가 0.84쯤 나옵니다("DS01227"). 잘못 읽은 줄은 0.5 안팎입니다.
LOW_CONFIDENCE = 0.70
UNSURE_DIGITS = 6
# Tesseract는 글자 높이가 30px 안팎일 때 가장 잘 읽습니다. 작은 그림은 키워서 읽습니다.
MIN_READ_WIDTH = 1600
# Windows 설치 파일이 기본으로 까는 자리. PATH에 없어도 여기서 찾습니다.
_WINDOWS_PATHS = (r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                  r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe")
# 프로젝트에 둔 학습 자료. 설치 폴더에 한글 자료를 넣을 권한이 없을 때 씁니다.
_PROJECT_TESSDATA = Path(__file__).resolve().parents[2] / "data" / "tessdata"


def _tessdata_folder() -> str:
    """쓸 학습 자료 폴더. 없으면 빈 글자(설치 폴더를 씁니다).

    Tesseract에는 TESSDATA_PREFIX로 알립니다. --tessdata-dir로 넘기면 Windows에서
    따옴표가 그대로 붙어 폴더를 못 찾습니다.
    """

    configured = os.getenv("TESSDATA_DIR", "").strip()
    folder = Path(configured) if configured else _PROJECT_TESSDATA
    return str(folder) if (folder / "eng.traineddata").exists() else ""


def _tesseract_cmd() -> str:
    """Tesseract 실행 파일. .env의 TESSERACT_CMD → PATH → Windows 기본 자리 순서로 찾습니다."""

    configured = os.getenv("TESSERACT_CMD", "").strip()
    if configured:
        return configured if Path(configured).exists() else ""
    found = shutil.which("tesseract")
    if found:
        return found
    for candidate in _WINDOWS_PATHS:
        if Path(candidate).exists():
            return candidate
    return ""


def _setup() -> dict:
    """한 번만 확인합니다. (쓸 수 있는지, 읽을 언어)"""

    with _ocr_lock:
        if _ocr_state:
            return _ocr_state
        _ocr_state.update(ready=False, lang="eng")
        try:
            import pytesseract
        except ImportError:
            return _ocr_state
        command = _tesseract_cmd()
        if not command:
            return _ocr_state
        pytesseract.pytesseract.tesseract_cmd = command
        folder = _tessdata_folder()
        if folder:
            os.environ["TESSDATA_PREFIX"] = folder
        try:
            pytesseract.get_tesseract_version()
            languages = set(pytesseract.get_languages(config=""))
        except Exception:                    # noqa: BLE001 - 깨진 설치도 "없음"으로 봅니다
            return _ocr_state
        if "eng" not in languages:
            return _ocr_state
        _ocr_state.update(ready=True, lang="kor+eng" if "kor" in languages else "eng")
        return _ocr_state


def ocr_available() -> bool:
    return _setup()["ready"]


def _read_lines(image) -> list[dict]:
    """줄마다 {quad, text, score, words}. words는 [(시작, 끝, 상자)] — text 안의 글자 자리입니다.

    위에서 아래, 왼쪽에서 오른쪽 순서입니다. score는 0~1 (줄에서 가장 자신 없는 단어).
    """

    import pytesseract

    state = _setup()
    image = image.convert("RGB")
    scale = 1.0
    if image.width < MIN_READ_WIDTH:
        scale = MIN_READ_WIDTH / image.width
        image = image.resize((round(image.width * scale), round(image.height * scale)))
    # psm 6: 한 덩어리의 글로 보고 줄 단위로 읽습니다. 서류처럼 줄이 가지런한 글에 맞습니다.
    data = pytesseract.image_to_data(image, lang=state["lang"],
                                     config="--oem 1 --psm 6",
                                     output_type=pytesseract.Output.DICT)

    lines: dict[tuple, list] = {}
    for i, word in enumerate(data["text"]):
        word = str(word or "").strip()
        confidence = float(data["conf"][i])
        if not word or confidence < 0:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        box = (data["left"][i] / scale, data["top"][i] / scale,
               (data["left"][i] + data["width"][i]) / scale,
               (data["top"][i] + data["height"][i]) / scale)
        lines.setdefault(key, []).append((word, confidence / 100, box))

    rows = []
    for words in lines.values():
        words.sort(key=lambda row: row[2][0])
        text, spans = "", []
        for word, _, box in words:
            if text:
                text += " "
            spans.append((len(text), len(text) + len(word), box))
            text += word
        left = min(box[0] for _, _, box in words)
        top = min(box[1] for _, _, box in words)
        right = max(box[2] for _, _, box in words)
        bottom = max(box[3] for _, _, box in words)
        rows.append({"quad": [[left, top], [right, top], [right, bottom], [left, bottom]],
                     "text": text, "score": min(score for _, score, _ in words),
                     "words": spans})
    rows.sort(key=lambda row: (round(row["quad"][0][1] / 12), row["quad"][0][0]))
    return rows


def _read(image) -> list[tuple[list, str, float]]:
    """(네 꼭짓점, 글자, 자신감) 목록. 위에서 아래, 왼쪽에서 오른쪽 순서입니다."""

    return [(row["quad"], row["text"], row["score"]) for row in _read_lines(image)]


def _word_box(row: dict, start: int, end: int) -> tuple[int, int, int, int] | None:
    """text의 start~end 글자가 걸친 단어들을 모두 덮는 상자."""

    boxes = [box for s, e, box in row["words"] if s < end and e > start]
    if not boxes:
        return None
    return (int(min(b[0] for b in boxes)) - PAD_PIXELS, int(min(b[1] for b in boxes)) - PAD_PIXELS,
            int(max(b[2] for b in boxes)) + PAD_PIXELS, int(max(b[3] for b in boxes)) + PAD_PIXELS)


def _span_box(quad: list, text: str, start: int, end: int) -> tuple[int, int, int, int]:
    """글자 상자 안에서 start~end 글자가 차지하는 자리. 글자 폭을 같다고 어림합니다."""

    left = min(p[0] for p in quad)
    right = max(p[0] for p in quad)
    top = min(p[1] for p in quad)
    bottom = max(p[1] for p in quad)
    per = (right - left) / max(1, len(text))
    x0 = left + per * max(0, start - PAD_CHARS) - PAD_PIXELS
    x1 = left + per * min(len(text), end + PAD_CHARS) + PAD_PIXELS
    return int(x0), int(top - PAD_PIXELS), int(x1), int(bottom + PAD_PIXELS)


def _whole_box(quad: list) -> tuple[int, int, int, int]:
    return (int(min(p[0] for p in quad)) - PAD_PIXELS, int(min(p[1] for p in quad)) - PAD_PIXELS,
            int(max(p[0] for p in quad)) + PAD_PIXELS, int(max(p[1] for p in quad)) + PAD_PIXELS)


def _digits_of(text: str) -> str:
    return "".join(ch for ch in text if ch.isdigit())


def redact_image(png: bytes) -> dict:
    """그림에서 은행 번호를 칠합니다.

    돌려주는 것
      image     칠한 그림(PNG). 이것만 바깥으로 나갑니다.
      found     칠한 번호의 수

    지운 번호는 되살리지 않습니다. OCR은 숫자를 잘못 읽을 수 있어, 그 번호를
    결제 계좌로 서류에 찍으면 안 됩니다. 사진으로 올린 경우 은행 정보는
    이용자가 직접 적습니다.
    """

    from PIL import Image, ImageDraw

    image = Image.open(io.BytesIO(png)).convert("RGB")
    rows = _read_lines(image)
    joined = "\n".join(row["text"] for row in rows)
    _, secrets = redact(joined, everywhere=True)
    originals = sorted(set(secrets.values()), key=len, reverse=True)

    draw = ImageDraw.Draw(image)
    unsure = 0
    for row in rows:
        quad, text = row["quad"], row["text"]
        if row["score"] < LOW_CONFIDENCE and len(_digits_of(text)) >= UNSURE_DIGITS:
            draw.rectangle(_whole_box(quad), fill="black")
            unsure += 1
            continue
        for original in originals:
            start = text.find(original)
            while start >= 0:
                end = start + len(original)
                # 번호가 걸친 단어의 자리를 그대로 칠합니다. 못 찾으면 글자 폭으로 어림합니다.
                box = _word_box(row, start, end) or _span_box(quad, text, start, end)
                draw.rectangle(box, fill="black")
                start = text.find(original, end)

    # 칠한 뒤 다시 읽어 봅니다. 어림한 자리가 빗나가 번호 일부가 남았으면 줄 전체를 칠합니다.
    if originals:
        needles = [_digits_of(original) for original in originals if len(_digits_of(original)) >= 6]
        codes = [original.replace(" ", "") for original in originals if not _digits_of(original)]
        for quad, text, _ in _read(image):
            flat = _digits_of(text)
            if any(needle[:6] in flat or needle[-6:] in flat for needle in needles) or \
                    any(code in text.replace(" ", "") for code in codes):
                draw.rectangle(_whole_box(quad), fill="black")

    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return {"image": buffer.getvalue(), "found": len(originals) + unsure, "unsure_lines": unsure}
