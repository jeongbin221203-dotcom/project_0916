"""Schedule date calculations."""

from __future__ import annotations

from datetime import date, timedelta

from app.validators import ValidationError

# Default lead times in days. Kept as constants so they can be tuned per route later.
LEAD_TIMES = {
    "SEA": {"final_delivery": 2, "import_customs": 2, "cut_off": 2, "export_customs": 2},
    "AIR": {"final_delivery": 1, "import_customs": 1, "cut_off": 1, "export_customs": 1},
}
DEFAULT_TRANSIT_DAYS = {"SEA": 14, "AIR": 2}


# 날짜에 더할 수 있는 최대 소요일. 이보다 길면 자료가 잘못된 것입니다.
MAX_TRANSIT_DAYS = 3_650


def calculate_eta(etd: date, transit_days: int) -> date:
    """출항일에 소요일을 더해 도착일을 냅니다.

    날짜 범위를 벗어나면 파이썬이 OverflowError를 냅니다. 그대로 두면 화면이
    500으로 죽으므로, 우리 오류로 바꿔 사람이 읽을 수 있게 알려 줍니다.
    """

    try:
        days = int(transit_days)
    except (TypeError, ValueError):
        raise ValidationError("소요일을 숫자로 읽지 못했습니다.", "transit_days") from None
    if not 0 <= days <= MAX_TRANSIT_DAYS:
        raise ValidationError("소요일이 올바르지 않습니다.", "transit_days")
    try:
        return etd + timedelta(days=days)
    except (OverflowError, OSError) as error:
        raise ValidationError("출발일이 너무 멀어 도착일을 낼 수 없습니다.",
                              "requested_departure_date") from error


def calculate_cargo_ready_date(etd: date, transport_mode: str) -> date:
    """Latest cargo ready date for a given ETD (cut-off + export customs before ETD)."""

    lead = LEAD_TIMES["AIR" if transport_mode == "AIR" else "SEA"]
    return etd - timedelta(days=lead["cut_off"] + lead["export_customs"])


# 출발 희망일 여유(일) 구간. 촉박할수록 붉게, 여유로울수록 초록으로 표시합니다.
MARGIN_LEVELS = [
    (0, "late", "납기 초과"),
    (3, "tight", "일정 촉박"),
    (7, "caution", "여유 적음"),
]
MARGIN_OK = ("ok", "여유 있음")


def grade_margin(margin_days: int) -> tuple[str, str]:
    """여유 일수를 등급(late/tight/caution/ok)과 설명으로 바꿉니다."""

    for limit, level, label in MARGIN_LEVELS:
        if margin_days < limit:
            return level, label
    return MARGIN_OK


def check_departure_margin(
    departure_date: date,
    buyer_required_date: date,
    transport_mode: str,
    transit_days: int,
) -> dict:
    """출발 희망일이 Buyer 납기에 맞는지 계산합니다."""

    lead = LEAD_TIMES["AIR" if transport_mode == "AIR" else "SEA"]
    eta = departure_date + timedelta(days=transit_days)
    latest_eta = buyer_required_date - timedelta(days=lead["final_delivery"] + lead["import_customs"])
    latest_etd = latest_eta - timedelta(days=transit_days)
    margin_days = (latest_etd - departure_date).days
    level, label = grade_margin(margin_days)
    return {
        "transit_days": transit_days,
        "eta": eta,
        "latest_etd": latest_etd,
        "margin_days": margin_days,
        "level": level,
        "label": label,
    }


def check_buyer_deadline(eta: date, buyer_required_date: date | None, transport_mode: str) -> dict | None:
    """Return whether the ETA leaves enough time for import customs and delivery."""

    if not buyer_required_date:
        return None
    lead = LEAD_TIMES["AIR" if transport_mode == "AIR" else "SEA"]
    latest_eta = buyer_required_date - timedelta(days=lead["final_delivery"] + lead["import_customs"])
    margin = (latest_eta - eta).days
    return {"latest_eta": latest_eta, "margin_days": margin, "on_time": margin >= 0}
