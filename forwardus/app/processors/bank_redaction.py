"""계좌번호·SWIFT·IBAN을 가립니다. 글자에서도, 그림에서도.

올린 서류는 AI(OpenAI)가 읽습니다. 그 전에 은행 번호를 가려서, 바깥으로는
번호가 나가지 않게 합니다.

글자  은행 이야기를 하는 줄(은행·계좌·A/C·SWIFT…)과 그 아래 두 줄에서
      번호를 [ACCOUNT_1] 같은 표시로 바꿉니다. 돌아온 뒤 은행 칸에만 되돌립니다.

그림  우리 컴퓨터에서 먼저 글자를 읽고(Tesseract OCR, 인터넷 안 씀) 번호 자리를
      칠합니다. 칠한 그림을 한 번 더 읽어 번호가 아직 보이면 그 줄 전체를 칠합니다.
      칠한 그림만 AI에게 보내고, 이용자에게도 그 그림을 보여 줍니다.

      OCR은 이름표를 잘못 읽거나 놓칠 수 있습니다. 그래서 그림에서는 은행이라는
      말이 없어도 9자리 이상의 번호는 모두 지웁니다.
      OCR이 설치되어 있지 않으면 그림을 받지 않습니다. 가리지 못한 그림을
      보내는 것보다 받지 않는 것이 낫습니다.
"""

from __future__ import annotations

import io
import re

from app.collectors import ocr_client

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

    everywhere=True는 그림용입니다. OCR이 이름표를 놓칠 수 있으니, 은행 줄이
    아니어도 9자리 이상 번호는 가립니다.
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

# 칠한 자리 둘레로 이만큼 더 칠합니다. 글자 폭을 어림해 칠하므로 넉넉하게 둡니다.
PAD_CHARS = 2
PAD_PIXELS = 4
# OCR이 이보다 자신 없게 읽은 줄에 숫자가 이만큼 있으면 줄 전체를 지웁니다.
# 잘못 읽은 줄("H 00 00 0 0 00")에 계좌번호가 있어도 우리 규칙은 번호를 못 찾습니다.
# 품목 줄이 지워질 수 있지만, 번호가 새는 것보다 낫습니다. (Tesseract 자신감 0~100을 0~1로 봅니다)
LOW_CONFIDENCE = 0.6
UNSURE_DIGITS = 6
# 이보다 좁은 그림은 키워서 읽습니다. 작은 글자는 Tesseract가 놓치기 쉽습니다.
OCR_MIN_WIDTH = 1500


def ocr_available() -> bool:
    return ocr_client.available()


def _read(image) -> list[tuple[list, str, float]]:
    """(네 꼭짓점, 글자, 자신감 0~1) 목록. 한 줄이 한 항목이고, 위에서 아래 순서입니다.

    Tesseract가 단어마다 돌려주는 상자를 줄 단위로 묶습니다. 좌표는 원래 그림 기준입니다.
    """

    from PIL import ImageOps

    pytesseract = ocr_client._pytesseract()
    gray = ImageOps.grayscale(image)
    scale = 1.0
    if gray.width < OCR_MIN_WIDTH:
        scale = OCR_MIN_WIDTH / gray.width
        gray = gray.resize((OCR_MIN_WIDTH, round(gray.height * scale)))
    data = pytesseract.image_to_data(gray, lang=ocr_client.languages(),
                                     output_type=pytesseract.Output.DICT)

    lines: dict[tuple, list] = {}
    for index, word in enumerate(data["text"]):
        word = str(word).strip()
        conf = float(data["conf"][index])
        if not word or conf < 0:
            continue
        key = (data["block_num"][index], data["par_num"][index], data["line_num"][index])
        left, top = data["left"][index] / scale, data["top"][index] / scale
        right = left + data["width"][index] / scale
        bottom = top + data["height"][index] / scale
        lines.setdefault(key, []).append((left, top, right, bottom, word, conf))

    rows = []
    for words in lines.values():
        words.sort(key=lambda item: item[0])
        left = min(item[0] for item in words)
        top = min(item[1] for item in words)
        right = max(item[2] for item in words)
        bottom = max(item[3] for item in words)
        quad = [[left, top], [right, top], [right, bottom], [left, bottom]]
        text = ocr_client.tidy(" ".join(item[4] for item in words))
        score = sum(item[5] for item in words) / len(words) / 100
        rows.append((quad, text, score))
    rows.sort(key=lambda row: (round(row[0][0][1] / 12), row[0][0][0]))
    return rows


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
    rows = _read(image)
    joined = "\n".join(text for _, text, _ in rows)
    _, secrets = redact(joined, everywhere=True)
    originals = sorted(set(secrets.values()), key=len, reverse=True)

    draw = ImageDraw.Draw(image)
    unsure = 0
    for quad, text, score in rows:
        if score < LOW_CONFIDENCE and len(_digits_of(text)) >= UNSURE_DIGITS:
            draw.rectangle(_whole_box(quad), fill="black")
            unsure += 1
            continue
        for original in originals:
            start = text.find(original)
            while start >= 0:
                draw.rectangle(_span_box(quad, text, start, start + len(original)), fill="black")
                start = text.find(original, start + len(original))

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
