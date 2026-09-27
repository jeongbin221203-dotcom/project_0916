"""사업자등록번호가 **있을 수 있는 번호인지** 봅니다.

왜 필요한가
  수출신고서에 반드시 들어가는 번호입니다. 예전에는 "숫자 10자리"만 보았습니다.
  그래서 0000000000 · 1234567890 · 9999999999 가 그대로 통과해 관세사에게
  넘어갔습니다. 신고가 반려되고, 더 나쁘게는 한 자리를 잘못 적어 **남의 회사
  번호**가 되어도 아무도 모릅니다.

  국세청이 정한 검증번호(끝자리) 규칙이 있습니다. 한 자리만 틀려도 걸립니다.
  바깥을 부르지 않고 그 자리에서 확인합니다. (2026-09-26)

규칙 (국세청 사업자등록번호 검증)
  앞 9자리에 가중치 1·3·7·1·3·7·1·3·5 를 곱해 더하고,
  9번째 자리 × 5 의 **십의 자리**를 한 번 더 더합니다.
  (10 − 합 % 10) % 10 이 끝자리와 같아야 합니다.

  예) 124-81-00998
      1·6·28·8·3·0·0·27·45 = 118,  +⌊45/10⌋ = 122
      (10 − 2) % 10 = 8  →  끝자리 8 과 같습니다.

여기서 하지 않는 것
  이 번호가 **실제로 발급되어 살아 있는지**는 국세청 조회로만 알 수 있습니다.
  여기서는 "모양이 맞는가"까지입니다. 화면에도 그렇게 적습니다.
"""

from __future__ import annotations

from app.validators import ValidationError

WEIGHTS = (1, 3, 7, 1, 3, 7, 1, 3, 5)
LENGTH = 10


def digits_of(value) -> str:
    """적어 준 글에서 숫자만 뽑습니다. (123-45-67890 도 받습니다)"""

    return "".join(ch for ch in str(value or "") if ch.isdigit())


def check_digit(nine: str) -> int:
    """앞 9자리로 끝자리를 구합니다."""

    total = sum(int(ch) * weight for ch, weight in zip(nine, WEIGHTS))
    total += int(nine[8]) * 5 // 10
    return (10 - total % 10) % 10


def is_valid(value) -> bool:
    digits = digits_of(value)
    if len(digits) != LENGTH:
        return False
    # 가운데 두 자리는 사업자 구분입니다. 00 은 발급되지 않습니다.
    if digits[3:5] == "00":
        return False
    return check_digit(digits[:9]) == int(digits[9])


def format_no(value) -> str:
    """123-45-67890 모양으로."""

    digits = digits_of(value)
    return f"{digits[:3]}-{digits[3:5]}-{digits[5:]}" if len(digits) == LENGTH else str(value or "")


def parse(value, *, field: str = "exporter_business_no", label: str = "사업자등록번호",
          required: bool = False) -> str:
    """모양을 보고 123-45-67890 으로 돌려줍니다. 비어 있으면 빈 글자."""

    text = str(value or "").strip()
    digits = digits_of(value)
    if not digits:
        # 아무것도 안 적은 것과, 적었는데 숫자가 하나도 없는 것은 다릅니다.
        # 뒤엣것을 조용히 비우면 적은 사람은 저장된 줄 압니다.
        if text:
            raise ValidationError(
                f"{label}에 숫자가 없습니다. ('{text[:20]}') 숫자 10자리로 적어 주세요.", field)
        if required:
            raise ValidationError(f"{label}을(를) 입력해주세요.", field)
        return ""
    if len(digits) != LENGTH:
        raise ValidationError(
            f"{label}는 숫자 10자리입니다. (적으신 것: {len(digits)}자리)", field)
    if not is_valid(digits):
        raise ValidationError(
            f"{label} '{format_no(digits)}'는 있을 수 없는 번호입니다. "
            "끝자리 검증번호가 맞지 않습니다 — 한 자리를 잘못 적으신 것 같습니다. "
            "수출신고서에 그대로 들어가는 번호라 틀리면 신고가 반려됩니다.", field)
    return format_no(digits)
