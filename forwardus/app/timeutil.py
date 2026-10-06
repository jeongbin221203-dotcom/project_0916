"""한국 시각 기준 날짜·시각.

서버(Render 컨테이너)는 UTC 입니다. date.today() 를 그대로 쓰면 한국 시각 00:00~08:59 에 만든
상업송장·견적송장의 날짜가 **전날**로 찍히고, 1월 1일 새벽에는 견적번호의 연도가 전년도가 됩니다.
(전수 점검 1회차, 전문가 관점)

우리 사용자는 한국 수출자이고 서류 날짜는 한국 날짜입니다. 한국은 서머타임이 없어 +9시간 고정으로
충분합니다(tzdata 가 없는 Windows 에서도 동작).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

KST = timezone(timedelta(hours=9), "KST")


def now_kst() -> datetime:
    return datetime.now(KST)


def today_kst() -> date:
    return now_kst().date()
