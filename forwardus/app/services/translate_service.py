"""보낼 글을 바이어의 언어로 옮깁니다. (수출신고 자료 · 그대로 보내기)

관세사에게는 우리말로 보내지만, 바이어에게는 그 나라 말로 보내야 합니다.
같은 내용을 사람이 다시 적으면 숫자가 틀립니다. 그래서 AI에게 옮기게 합니다.

지키는 것
  숫자·코드  금액·수량·HS CODE·선박명·날짜는 그대로 둡니다. 옮기는 것은 말뿐입니다.
  계좌번호   보내기 전에 [ACCOUNT_1] 같은 표시로 가리고, 돌아온 뒤 되돌립니다.
             바깥(OpenAI)으로 계좌번호가 나가지 않습니다. (bank_redaction)
  줄 모양    줄바꿈과 "■ - " 같은 머리표를 그대로 둡니다. 붙여 넣어 바로 보내는 글입니다.
"""

from __future__ import annotations

from app.collectors import ai_client
from app.processors import bank_redaction
from app.services import ServiceError

# 고를 수 있는 언어. 수출이 많은 나라부터 둡니다.
LANGUAGES = [
    {"code": "en", "label": "영어 (English)", "name": "English"},
    {"code": "zh", "label": "중국어 간체 (简体中文)", "name": "Simplified Chinese"},
    {"code": "zh-TW", "label": "중국어 번체 (繁體中文)", "name": "Traditional Chinese"},
    {"code": "ja", "label": "일본어 (日本語)", "name": "Japanese"},
    {"code": "vi", "label": "베트남어 (Tiếng Việt)", "name": "Vietnamese"},
    {"code": "id", "label": "인도네시아어 (Bahasa Indonesia)", "name": "Indonesian"},
    {"code": "th", "label": "태국어 (ไทย)", "name": "Thai"},
    {"code": "es", "label": "스페인어 (Español)", "name": "Spanish"},
    {"code": "de", "label": "독일어 (Deutsch)", "name": "German"},
    {"code": "fr", "label": "프랑스어 (Français)", "name": "French"},
    {"code": "ru", "label": "러시아어 (Русский)", "name": "Russian"},
    {"code": "ar", "label": "아랍어 (العربية)", "name": "Arabic"},
    {"code": "ko", "label": "한국어", "name": "Korean"},
]
_BY_CODE = {row["code"]: row for row in LANGUAGES}

MAX_CHARS = 8000
# 옮긴 글은 원문보다 길어집니다. 넉넉히 둡니다. (글자 수의 대략 1.6배 토큰)
MAX_TOKENS = 3000

PROMPT = """You translate Korean export/trade documents for the exporter to send to their buyer.

Rules:
- Translate into {language}. Output the translation only, with no preface or explanation.
- Keep the line breaks, indentation and bullet marks (■, -, ·) exactly as they are.
- Never change numbers, amounts, currencies, dates, HS codes, container/vessel names,
  company names, addresses or codes such as "EXP-2026-00057", "FOB", "TT". Copy them as they are.
- Keep placeholders like [ACCOUNT_1] or [SWIFT_1] exactly as written.
- Korean labels become natural trade terms in the target language
  (예: 수출자 → Exporter, 신고가격 → Declared value).
- "(미입력)" means the exporter has not filled it in; translate it as "(not provided)" or the
  equivalent in the target language."""


def language_label(code: str) -> str:
    row = _BY_CODE.get(code)
    return row["label"] if row else code


def available() -> bool:
    return ai_client.available()


def translate(text: str, code: str) -> dict:
    """글을 고른 언어로 옮깁니다. (옮긴 글, 언어)

    실패하면 ServiceError를 냅니다. 반쯤 옮긴 글을 돌려주지 않습니다 —
    붙여 넣어 그대로 보내는 글이라, 틀린 채로 나가면 바이어가 그대로 읽습니다.
    """

    body = str(text or "").strip()
    if not body:
        raise ServiceError("옮길 내용이 없습니다.", "VALIDATION_ERROR")
    if len(body) > MAX_CHARS:
        raise ServiceError(f"글이 너무 깁니다. {MAX_CHARS:,}자까지 옮길 수 있습니다.",
                           "VALIDATION_ERROR")
    language = _BY_CODE.get(code)
    if language is None:
        raise ServiceError("고를 수 없는 언어입니다.", "VALIDATION_ERROR")
    if not available():
        raise ServiceError("지금은 다른 나라 말로 옮겨 드릴 수 없습니다. "
                           "원문은 그대로 쓰실 수 있습니다.", "AI_UNAVAILABLE", 503)

    # 계좌번호·SWIFT는 가린 채 보내고, 돌아온 뒤 제자리에 되돌립니다.
    masked, secrets = bank_redaction.redact(body)
    result = ai_client.chat(
        [{"role": "system", "content": PROMPT.format(language=language["name"])},
         {"role": "user", "content": masked}],
        max_tokens=MAX_TOKENS)
    if not result["success"]:
        raise ServiceError(result["message"], result.get("error_code") or "AI_FAILED", 502)
    return {"text": bank_redaction.restore(result["data"].strip(), secrets),
            "language": language["label"], "code": language["code"]}
