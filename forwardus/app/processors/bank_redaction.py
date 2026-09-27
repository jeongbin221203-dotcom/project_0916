"""계좌번호·SWIFT·IBAN을 가립니다. 글자에서도, 그림에서도.

올린 서류는 AI(OpenAI)가 읽습니다. 그 전에 은행 번호를 가려서, 바깥으로는
번호가 나가지 않게 합니다.

글자  은행 이야기를 하는 줄(은행·계좌·A/C·SWIFT…)과 그 아래 두 줄에서
      번호를 [ACCOUNT_1] 같은 표시로 바꿉니다. 돌아온 뒤 은행 칸에만 되돌립니다.

그림  우리 컴퓨터에서 먼저 글자를 읽고(OCR, 인터넷 안 씀) 번호 자리를 칠합니다.
      칠한 그림을 한 번 더 읽어 번호가 아직 보이면 그 줄 전체를 칠합니다.
      칠한 그림만 AI에게 보내고, 이용자에게도 그 그림을 보여 줍니다.

      OCR은 Tesseract(한글+영문, app/processors/ocr.py)를 먼저 쓰고, 없으면 RapidOCR를 씁니다.
      Tesseract는 "입금계좌" 같은 한글 이름표도 읽지만, 사진은 잘못 읽을 수 있어
      그림에서는 은행이라는 말이 없어도 9자리 이상의 번호는 모두 지웁니다.
      OCR이 하나도 없으면 그림을 받지 않습니다. 가리지 못한 그림을
      보내는 것보다 받지 않는 것이 낫습니다.
"""

from __future__ import annotations

import io
import logging
import re
import threading

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
#
# 빈칸 자리는 **줄바꿈까지** 봅니다. PDF에서 읽은 글은 줄이 꺾입니다.
# 한 칸(space)만 보던 때는 "SWIFT: DEUT DE\nFF 500"이 **한 글자도 안 가려진
# 채로** 남았습니다. 계좌·SWIFT는 어떤 경우에도 남기지 않기로 한 자리라,
# 줄이 꺾였다고 새면 안 됩니다. (2026-09-26)
_DIGITS = re.compile(r"(?<![A-Za-z0-9\-./])(\d[\d\-.\s]{4,}\d)(?![A-Za-z0-9\-])")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:\s*[A-Z0-9]{4}){2,7}(?:\s*[A-Z0-9]{1,4})?\b")
_SWIFT_CODE = re.compile(r"\b[A-Z]{4}\s*[A-Z]{2}\s*[A-Z0-9]{2}(?:\s*[A-Z0-9]{3})?\b")
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


def _join_wrapped_numbers(lines: list[str]) -> list[str]:
    """줄이 꺾인 계좌·SWIFT를 **한 줄로 붙여 둡니다.**

    왜 필요한가
      아래 되풀이는 줄을 하나씩 봅니다. 그래서 PDF에서 줄이 꺾인 번호는
      어떤 규칙을 써도 잡히지 않습니다. "SWIFT: DEUT DE\\nFF 500"이
      **한 글자도 안 가려진 채로** 남았습니다.

    어디까지만 하나
      **은행 이야기를 하는 줄과 바로 다음 줄**만 봅니다. 그리고 두 줄을 붙였을
      때에만 새로 걸리는 경우에만 붙입니다. 글 전체를 훑었더니 "SAMPLE CO."
      같은 회사명이 SWIFT로 잡혀, 새는 것보다 더 나빴습니다. (2026-09-26)
    """

    out: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        nxt = lines[index + 1] if index + 1 < len(lines) else ""
        window = _BANK_WORDS.search(line) or _BANK_WORDS.search(nxt)
        if nxt and window:
            pair = f"{line} {nxt}"
            for pattern in (_SWIFT_CODE, _IBAN):
                spans = [m.group(0) for m in pattern.finditer(pair)]
                alone = [m.group(0) for m in pattern.finditer(line)]
                alone += [m.group(0) for m in pattern.finditer(nxt)]
                # 붙였을 때에만 새로 걸리는 것이 있으면 두 줄을 한 줄로 둡니다.
                if any(span not in alone for span in spans):
                    out.append(pair)
                    index += 2
                    break
            else:
                out.append(line)
                index += 1
            continue
        out.append(line)
        index += 1
    return out


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

    lines = _join_wrapped_numbers(str(text or "").split("\n"))
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

_engine = None
_engine_lock = threading.Lock()
# 칠한 자리 둘레로 이만큼 더 칠합니다. 글자 폭을 어림해 칠하므로 넉넉하게 둡니다.
PAD_CHARS = 2
PAD_PIXELS = 4
# OCR이 이보다 자신 없게 읽은 줄에 숫자가 이만큼 있으면 줄 전체를 지웁니다.
# 잘못 읽은 줄("H 00 00 0 0 00", 자신감 0.69)에 계좌번호가 있어도 우리 규칙은
# 번호를 못 찾습니다. 품목 줄이 지워질 수 있지만, 번호가 새는 것보다 낫습니다.
#
# Tesseract 기준으로 0.70입니다. 바르게 읽은 낱말도 0.84쯤 나옵니다("DS01227").
# 0.85로 두면 멀쩡한 오퍼 번호가 통째로 칠해집니다. 잘못 읽은 줄은 0.5 안팎입니다.
LOW_CONFIDENCE = 0.70
UNSURE_DIGITS = 6
# 낱말 자리를 아는 OCR(Tesseract)에서 헷갈린 숫자 낱말을 칠하는 기준. 계좌번호를 띄어 쓴
# 조각(110 123 456789)도 4자리 이상이거나 은행 줄에 있습니다.
UNSURE_WORD_DIGITS = 4


def _rapidocr_available() -> bool:
    try:
        import rapidocr  # noqa: F401
    except ImportError:
        return False
    return True


def ocr_available() -> bool:
    """그림 속 번호를 찾을 OCR이 있는지. Tesseract가 먼저, 없으면 RapidOCR."""

    from app.processors import ocr

    return ocr.available() or _rapidocr_available()


def _read(image) -> list[tuple[list, str, float]]:
    """(네 꼭짓점, 글자, 자신감 0~1) 목록. 위에서 아래, 왼쪽에서 오른쪽 순서입니다."""

    from app.processors import ocr

    if ocr.available():
        return ocr.read_lines(image)
    return _read_rapidocr(image)


def _read_rapidocr(image) -> list[tuple[list, str, float]]:
    global _engine
    import numpy

    with _engine_lock:
        if _engine is None:
            from rapidocr import RapidOCR

            logging.getLogger("RapidOCR").setLevel(logging.WARNING)
            _engine = RapidOCR()
        result = _engine(numpy.array(image.convert("RGB")))
    if result.boxes is None:
        return []
    rows = [([list(map(float, point)) for point in box], str(text), float(score))
            for box, text, score in zip(result.boxes, result.txts, result.scores)]
    rows.sort(key=lambda row: (round(min(p[1] for p in row[0]) / 12), min(p[0] for p in row[0])))
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
    joined = "\n".join(row[1] for row in rows)
    _, secrets = redact(joined, everywhere=True)
    originals = sorted(set(secrets.values()), key=len, reverse=True)

    draw = ImageDraw.Draw(image)
    unsure = 0
    for row in rows:
        quad, text, score = row[0], row[1], row[2]
        # Tesseract는 낱말마다 자리와 자신감을 줍니다. (RapidOCR는 줄 단위뿐)
        words = row[3] if len(row) > 3 else None
        if score < LOW_CONFIDENCE and len(_digits_of(text)) >= UNSURE_DIGITS:
            if words:
                # 헷갈리게 읽은 숫자 낱말만 칠합니다. 줄 전체를 칠하면 품명·수량·단가까지 사라집니다.
                # 3자리 이하(수량 500 등)는 은행 줄이 아니면 계좌번호 조각일 수 없어 남깁니다.
                bank_line = bool(_BANK_WORDS.search(text))
                for word_quad, word, word_score in words:
                    digits = len(_digits_of(word))
                    if word_score < LOW_CONFIDENCE and digits and (digits >= UNSURE_WORD_DIGITS or bank_line):
                        draw.rectangle(_whole_box(word_quad), fill="black")
            else:
                draw.rectangle(_whole_box(quad), fill="black")
            unsure += 1
        for original in originals:
            # 번호가 한 낱말이면 그 낱말 자리를 그대로 칠합니다. 글자 폭 어림보다 정확합니다.
            hits = [word_quad for word_quad, word, _ in (words or []) if original in word]
            if hits:
                for word_quad in hits:
                    draw.rectangle(_whole_box(word_quad), fill="black")
                continue
            start = text.find(original)
            while start >= 0:
                draw.rectangle(_span_box(quad, text, start, start + len(original)), fill="black")
                start = text.find(original, start + len(original))

    # 칠한 뒤 다시 읽어 봅니다. 어림한 자리가 빗나가 번호 일부가 남았으면 줄 전체를 칠합니다.
    if originals:
        needles = [_digits_of(original) for original in originals if len(_digits_of(original)) >= 6]
        codes = [original.replace(" ", "") for original in originals if not _digits_of(original)]
        for row in _read(image):
            quad, text = row[0], row[1]
            flat = _digits_of(text)
            if any(needle[:6] in flat or needle[-6:] in flat for needle in needles) or \
                    any(code in text.replace(" ", "") for code in codes):
                draw.rectangle(_whole_box(quad), fill="black")

    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return {"image": buffer.getvalue(), "found": len(originals) + unsure, "unsure_lines": unsure}
