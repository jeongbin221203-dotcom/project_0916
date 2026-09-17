"""금액·비율 표기 함수 모음 (화면 표시와 시사점 문장 공용)."""

import math

CURRENCY_SYMBOLS = {"KRW": "₩", "USD": "$", "EUR": "€"}
MINUS_SIGN = "−"


def round_half_up(value: float, digits: int = 0) -> float:
    """0.5 올림 반올림 결과 반환 (HTML 초안의 Math.round 규칙과 동일)."""
    factor = 10 ** digits
    return math.floor(value * factor + 0.5) / factor


def format_number(value: float, digits: int = 0) -> str:
    """천 단위 구분 기호가 포함된 숫자 문자열 반환."""
    return f"{round_half_up(value, digits):,.{digits}f}"


def format_krw(value: float) -> str:
    """원화 금액 문자열 반환 (예: ₩1,234,567)."""
    rounded_value = round_half_up(value)
    sign = MINUS_SIGN if rounded_value < 0 else ""
    return f"{sign}₩{abs(rounded_value):,.0f}"


def format_krw_compact(value: float) -> str:
    """만원·억원 단위 축약 금액 문자열 반환."""
    abs_value = abs(value)
    sign = MINUS_SIGN if value < 0 else ""
    if abs_value >= 100_000_000:
        return f"{sign}{format_number(abs_value / 100_000_000, 2)}억원"
    if abs_value >= 10_000:
        return f"{sign}{format_number(abs_value / 10_000, 1)}만원"
    return format_krw(value)


def format_money(value: float, currency: str, digits: int = 2) -> str:
    """통화 기호가 포함된 금액 문자열 반환 (원화는 정수 표기)."""
    if currency == "KRW":
        return format_krw(value)
    return f"{CURRENCY_SYMBOLS.get(currency, '')}{format_number(value, digits)}"


def format_percent(ratio: float, digits: int = 1) -> str:
    """비율(0~1)을 백분율 문자열로 변환."""
    return f"{format_number(ratio * 100, digits)}%"


def format_signed_percent(ratio: float, digits: int = 1, ascii_minus: bool = False) -> str:
    """부호가 포함된 백분율 문자열 반환 (st.metric delta용 ASCII 부호 선택 가능)."""
    minus = "-" if ascii_minus else MINUS_SIGN
    if ratio > 0.00049:
        sign = "+"
    elif ratio < -0.00049:
        sign = minus
    else:
        sign = ""
    return f"{sign}{format_number(abs(ratio) * 100, digits)}%"


def format_rate_percent(rate: float) -> str:
    """세율·요율을 불필요한 0 없이 백분율로 표기 (예: 0.0008 → 0.08%)."""
    text = f"{rate * 100:.3f}".rstrip("0").rstrip(".")
    return f"{text}%"


def escape_markdown(text: str) -> str:
    """Streamlit 마크다운에서 수식으로 해석되는 달러 기호 이스케이프."""
    return text.replace("$", "\\$")
