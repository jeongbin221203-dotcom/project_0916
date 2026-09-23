"""신용장(L/C) 날짜로 안전한 선적예정일을 냅니다.

L/C에는 날짜가 둘 있고, 둘 다 지켜야 은행에서 대금을 받습니다.

  최종선적일 (44C Latest date of shipment)  이 날까지 배에 실어야 합니다. (B/L의 On Board Date)
  유효기일   (31D Date of expiry)           이 날까지 은행에 서류를 내야 합니다.

여기에 제시기간(48 Period for presentation)이 걸립니다. 선적일로부터 며칠 안에 서류를
내야 하고, 적혀 있지 않으면 UCP 600 제14조 (c)에 따라 **21일**입니다. 그리고 어느 경우에도
유효기일을 넘길 수 없습니다.

그래서 실제로 지켜야 하는 선적 마감은 둘 중 **빠른 날**입니다.

  ① 최종선적일
  ② 유효기일 − 제시기간        (서류 만들어 은행에 낼 시간을 빼면 이 날까지 실어야 합니다)

②가 ①보다 빠른 L/C가 흔합니다. 최종선적일만 보고 배를 잡으면 서류가 늦어 대금을 못 받습니다.
이 계산은 AI가 아니라 우리 코드가 합니다. 날짜를 잘못 짚으면 돈이 걸립니다.

여기서 내는 날은 "이 날까지 실으면 안전하다"는 권고일 뿐, 은행·선사의 확정 일정이 아닙니다.
최종 확인은 개설은행의 조건 원문으로 하세요.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.processors.schedule_calculator import LEAD_TIMES, grade_margin

# UCP 600 제14조 (c). 제시기간이 L/C에 적혀 있지 않을 때 씁니다.
DEFAULT_PRESENTATION_DAYS = 21
# 제시기간으로 받아들일 범위. 벗어나면 잘못 읽은 것으로 보고 기본값을 씁니다.
MIN_PRESENTATION_DAYS = 1
MAX_PRESENTATION_DAYS = 90
# 마감일에 딱 맞춰 싣지 않게 두는 여유. 배는 하루 이틀 밀리는 일이 흔합니다.
SAFETY_DAYS = {"SEA": 3, "AIR": 1}
# 선적 마감까지 최소한 이만큼은 남아 있어야 준비가 됩니다. (아래 prep_days 계산)
LATE_LEVELS = ("late", "tight")


def _mode(transport_mode: str | None) -> str:
    return "AIR" if str(transport_mode or "").upper() == "AIR" else "SEA"


def prep_days(transport_mode: str | None) -> int:
    """화물 준비가 끝난 뒤 배에 실리기까지 걸리는 날. (수출통관 + 선적 마감)"""

    lead = LEAD_TIMES[_mode(transport_mode)]
    return lead["export_customs"] + lead["cut_off"]


def presentation_days(value) -> tuple[int, bool]:
    """제시기간(일)과 "L/C에 적혀 있었는가". 이상한 값은 기본 21일로 돌립니다."""

    try:
        days = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return DEFAULT_PRESENTATION_DAYS, False
    if MIN_PRESENTATION_DAYS <= days <= MAX_PRESENTATION_DAYS:
        return days, True
    return DEFAULT_PRESENTATION_DAYS, False


def plan(*, latest_shipment: date | None = None, expiry: date | None = None,
         presentation: int | None = None, transport_mode: str = "SEA",
         today: date | None = None) -> dict | None:
    """L/C 날짜로 "언제까지 실어야 하고, 언제 실으면 안전한지"를 냅니다.

    날짜가 하나도 없으면 None입니다. 하나만 있어도 계산합니다.

    돌려주는 것
      deadline            실제로 지켜야 하는 선적 마감일 (①②중 빠른 날)
      deadline_reason     그 날이 나온 이유 ("expiry" | "latest_shipment" | "both")
      recommended_etd     권하는 선적예정일 (마감일에서 여유를 뺀 날)
      cargo_ready_by      화물이 준비되어 있어야 하는 날 (통관·선적 마감 앞)
      presentation_by     서류를 은행에 내야 하는 날 (선적일 + 제시기간, 유효기일 이내)
      days_left           오늘부터 마감까지 남은 날
      level / label       여유 등급 (late · tight · caution · ok)
      feasible            오늘 준비를 시작해도 마감을 지킬 수 있는가
      notes               사람에게 보여 줄 설명 (한국어)
    """

    if latest_shipment is None and expiry is None:
        return None

    today = today or date.today()
    days, stated = presentation_days(presentation)
    mode = _mode(transport_mode)
    notes: list[str] = []

    # ② 유효기일에서 서류 낼 시간을 뺀 날
    by_expiry = expiry - timedelta(days=days) if expiry else None
    candidates = [value for value in (latest_shipment, by_expiry) if value]
    deadline = min(candidates)
    if latest_shipment and by_expiry and latest_shipment == by_expiry:
        reason = "both"
    elif by_expiry and deadline == by_expiry:
        reason = "expiry"
    else:
        reason = "latest_shipment"

    if reason == "expiry":
        notes.append(f"유효기일({expiry.isoformat()})에서 서류 제시기간 {days}일을 뺀 "
                     f"{deadline.isoformat()}이 실제 선적 마감입니다."
                     + (f" L/C의 최종선적일({latest_shipment.isoformat()})보다 빠릅니다."
                        if latest_shipment else ""))
    elif latest_shipment:
        notes.append(f"L/C 최종선적일 {latest_shipment.isoformat()}까지 실어야 합니다.")
    if not stated and expiry:
        notes.append(f"제시기간이 L/C에 없어 UCP 600 제14조(c)의 {DEFAULT_PRESENTATION_DAYS}일로 봤습니다.")

    safety = SAFETY_DAYS[mode]
    needed = prep_days(mode)
    recommended = deadline - timedelta(days=safety)
    earliest = today + timedelta(days=needed)
    feasible = earliest <= deadline
    if recommended < earliest:
        # 여유를 두면 이미 늦습니다. 준비가 끝나는 가장 이른 날로 당깁니다.
        recommended = min(earliest, deadline) if feasible else deadline
        if feasible:
            notes.append(f"마감이 가까워 여유 {safety}일을 두지 못했습니다. "
                         f"수출통관·선적 마감({needed}일)을 감안한 가장 이른 날로 잡았습니다.")

    days_left = (deadline - today).days
    level, label = grade_margin(days_left - needed)
    if not feasible:
        notes.append(f"오늘 준비를 시작해도 {deadline.isoformat()}까지 싣기 어렵습니다. "
                     "선적기일 연장(Amendment)을 개설은행에 요청하는 것이 안전합니다.")
    elif level in LATE_LEVELS:
        notes.append("일정이 촉박합니다. 선사 스케줄을 먼저 확보하고 서류를 미리 준비하세요.")

    presentation_by = recommended + timedelta(days=days)
    if expiry and presentation_by > expiry:
        presentation_by = expiry
    notes.append(f"선적 후 {days}일 안에, 늦어도 {presentation_by.isoformat()}까지 "
                 "은행에 서류를 내야 합니다.")

    return {
        "deadline": deadline,
        "deadline_reason": reason,
        "latest_shipment": latest_shipment,
        "expiry": expiry,
        "presentation_days": days,
        "presentation_stated": stated,
        "recommended_etd": recommended,
        "cargo_ready_by": recommended - timedelta(days=needed),
        "presentation_by": presentation_by,
        "days_left": days_left,
        "level": level,
        "label": label,
        "feasible": feasible,
        "transport_mode": mode,
        "notes": notes,
    }


def as_text(result: dict | None) -> dict | None:
    """화면·API로 보낼 모양. 날짜를 글자로 바꿉니다."""

    if not result:
        return None
    out = dict(result)
    for key in ("deadline", "latest_shipment", "expiry", "recommended_etd", "cargo_ready_by",
                "presentation_by"):
        value = out.get(key)
        out[key] = value.isoformat() if isinstance(value, date) else ""
    return out
