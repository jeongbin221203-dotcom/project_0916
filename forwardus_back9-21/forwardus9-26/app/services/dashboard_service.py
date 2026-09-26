"""Dashboard — 보는 사람의 권한에 따라 범위가 다른 한 화면.

마스터(role "master"/"admin")  모든 사용자의 Shipment · 플랫폼 통계 · 상태 강제 변경 · 내려받기
일반 회원(role "user")          자기가 만든 Shipment · 내 서류 · 내 일정/B/L 요약

범위를 정하는 곳은 여기 한 곳입니다. 화면(routes/dashboard.py)과 API가 모두 이 함수들을
거치므로, 일반 회원에게 남의 Shipment가 섞여 나갈 길이 없습니다.
(목록은 shipment_service.list_shipments → user_id로 거른 쿼리)
"""

from __future__ import annotations

import csv
import io
from collections import OrderedDict
from datetime import datetime

from app.models.shipment import SHIPMENT_STATUSES, STATUS_LABELS
from app.services import ServiceError, shipment_service

# 상태를 사람이 보는 네 칸으로 묶습니다. 작성 중·취소는 진행 현황에서 뺍니다.
# "통관 진행"에 해당하는 상태가 따로 없어, 도착(arrived) 뒤 배송 완료 전을 통관 진행으로 봅니다.
STATUS_GROUPS = OrderedDict([
    ("waiting", {"label": "선적 대기", "statuses": ("quoted", "booked"),
                 "note": "견적 완료 · 부킹 완료"}),
    ("moving", {"label": "운송 중", "statuses": ("departed", "in_transit"),
                "note": "출항 · 해상/항공 운송 중"}),
    ("customs", {"label": "통관 진행", "statuses": ("arrived",),
                 "note": "도착 후 수입 통관·배송 대기"}),
    ("done", {"label": "도착 완료", "statuses": ("delivered", "closed"),
              "note": "배송 완료 · 종료"}),
])
# 지금 움직이고 있는 화물. (작성 중·완료·취소 제외)
ACTIVE_STATUSES = ("quoted", "booked", "departed", "in_transit", "arrived")
MAX_QUERY = 100
# 한 쪽에 보여 줄 Shipment 수. 마스터 화면은 전체 사용자 것을 모으므로 금방 수백 줄이 됩니다.
PAGE_SIZE = 20
PAGE_SIZES = (20, 50, 100)
RECENT_DOCUMENTS = 6
RECENT_SCHEDULES = 5
# 확정 전 서류 초안. 목록이 길어지면 진행 중인 화물이 밀려납니다.
RECENT_DRAFTS = 8


class Forbidden(ServiceError):
    """권한이 없는 요청. 화면·API 모두 403으로 답합니다."""

    def __init__(self, message: str = "관리자(마스터) 계정만 쓸 수 있습니다."):
        super().__init__(message, "FORBIDDEN", 403)


def require_admin(viewer) -> None:
    if viewer is None or not getattr(viewer, "is_admin", False):
        raise Forbidden()


def scope_of(viewer) -> str:
    return "all" if viewer is not None and viewer.is_admin else "mine"


# --- 목록 ---------------------------------------------------------------------------

def owner_emails() -> dict:
    """마스터 화면에서 Shipment마다 누가 만들었는지 보여 줍니다."""

    from app.models import User

    return {user.id: user.email for user in User.query.all()}


def search(viewer, *, status: str | None = None, q: str = "", owner: str = "",
           owners: dict | None = None) -> list:
    """보는 사람이 볼 수 있는 Shipment 안에서만 거릅니다. 로그인 전이면 비어 있습니다."""

    if status not in SHIPMENT_STATUSES:
        status = None
    # 범위는 여기서 정해집니다. 일반 회원은 user_id로 거른 쿼리만 탑니다.
    shipments = shipment_service.list_shipments(status, viewer=viewer)
    needle = (q or "").strip().lower()[:MAX_QUERY]
    owner = (owner or "").strip().lower()[:MAX_QUERY]
    if not needle and not owner:
        return shipments
    admin = scope_of(viewer) == "all"
    owners = owners if owners is not None else (owner_emails() if admin else {})

    def hit(shipment) -> bool:
        email = (owners.get(shipment.user_id) or "").lower() if admin else ""
        if owner and owner not in email:
            return False
        if not needle:
            return True
        words = [shipment.shipment_id, shipment.project_name, shipment.origin_code,
                 shipment.destination_code, shipment.bl_no,
                 shipment.buyer.name if shipment.buyer else "", email]
        return any(needle in str(word or "").lower() for word in words)

    return [shipment for shipment in shipments if hit(shipment)]


def paginate(rows: list, page: int = 1, per_page: int = PAGE_SIZE) -> dict:
    """목록을 쪽으로 나눕니다.

    **세는 것은 전체, 그리는 것만 한 쪽입니다.** 통계 칸과 CSV 내려받기는 거른 목록
    전체를 그대로 씁니다. 쪽을 넘긴다고 합계가 달라지면 관리자가 숫자를 못 믿습니다.

    쪽 번호가 범위를 벗어나면(주소를 직접 고쳤거나, 거르고 나서 결과가 줄었거나)
    빈 화면 대신 가장 가까운 쪽을 보여 줍니다.
    """

    per_page = per_page if per_page in PAGE_SIZES else PAGE_SIZE
    total = len(rows)
    pages = max(1, -(-total // per_page))          # 올림 나눗셈
    page = max(1, min(page, pages))
    start = (page - 1) * per_page
    items = rows[start:start + per_page]
    # 열쇠 이름이 "rows"인 이유: 화면(Jinja)에서 page.items라고 쓰면 dict의 items() 메서드가
    # 먼저 잡혀 목록 대신 함수가 옵니다. 이름만 바꿔 그 함정을 없앱니다.
    return {"rows": items, "page": page, "pages": pages, "per_page": per_page,
            "total": total, "start": start + 1 if items else 0, "end": start + len(items),
            "has_prev": page > 1, "has_next": page < pages,
            "prev_page": page - 1, "next_page": page + 1,
            "numbers": page_numbers(page, pages)}


def page_numbers(page: int, pages: int, window: int = 2) -> list:
    """쪽 번호 줄. 사이가 끊기는 자리는 None으로 둡니다(화면에서 '…'로 그립니다).

    쪽이 아무리 늘어도 줄이 넘치지 않게 처음·끝과 지금 쪽 둘레만 남깁니다.
    """

    if pages <= 7:
        return list(range(1, pages + 1))
    keep = {1, pages} | {n for n in range(page - window, page + window + 1) if 1 <= n <= pages}
    ordered = sorted(keep)
    numbers: list = []
    for index, number in enumerate(ordered):
        if index and number - ordered[index - 1] > 1:
            numbers.append(None)
        numbers.append(number)
    return numbers


def status_cards(shipments) -> list[dict]:
    counts = {key: 0 for key in STATUS_GROUPS}
    for shipment in shipments:
        for key, group in STATUS_GROUPS.items():
            if shipment.status in group["statuses"]:
                counts[key] += 1
    return [{"key": key, "label": group["label"], "note": group["note"], "count": counts[key],
             "statuses": list(group["statuses"])} for key, group in STATUS_GROUPS.items()]


# --- 마스터 ---------------------------------------------------------------------------

def _this_month(value) -> bool:
    now = datetime.utcnow()
    return bool(value) and value.year == now.year and value.month == now.month


def platform_stats(viewer) -> dict:
    """플랫폼 전체 통계. 마스터만 부를 수 있습니다."""

    require_admin(viewer)
    from app.models import TradeDocument, User

    shipments = shipment_service.list_shipments(viewer=viewer)
    documents = TradeDocument.query.all()
    return {
        "active": sum(1 for s in shipments if s.status in ACTIVE_STATUSES),
        "total": len(shipments),
        "cards": status_cards(shipments),
        "users": User.query.count(),
        "month_quotes": sum(1 for s in shipments if _this_month(s.created_at)),
        "month_documents": sum(1 for d in documents if _this_month(d.created_at)),
    }


def force_status(viewer, shipment_id: str, status: str):
    """관리자가 상태를 직접 바꿉니다. 정해진 전환 순서를 따르지 않습니다."""

    require_admin(viewer)
    if status not in SHIPMENT_STATUSES:
        raise ServiceError("알 수 없는 상태입니다.", "INVALID_STATUS")
    shipment = shipment_service.get_or_404(shipment_id, viewer=viewer)
    shipment.status = status
    from app.repositories import shipment_repository

    shipment_repository.commit()
    return shipment


EXPORT_COLUMNS = [("shipment_id", "Shipment ID"), ("owner", "작성자"), ("project_name", "견적명"),
                  ("route", "Route"), ("mode", "Mode"), ("buyer", "Buyer"), ("etd", "ETD"),
                  ("eta", "ETA"), ("bl_no", "B/L No."), ("status", "상태"),
                  ("total_cost_krw", "물류비(원)"), ("created_at", "생성일")]


def export_csv(viewer, shipments, owners: dict) -> bytes:
    """엑셀에서 바로 열리는 CSV. 한글이 깨지지 않게 UTF-8 BOM을 붙입니다. 마스터만."""

    require_admin(viewer)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([label for _, label in EXPORT_COLUMNS])
    for shipment in shipments:
        row = shipment_row(shipment, owners)
        row["status"] = row["status_label"]
        writer.writerow([_cell(row.get(key)) for key, _ in EXPORT_COLUMNS])
    return ("﻿" + buffer.getvalue()).encode("utf-8")


def _cell(value) -> str:
    text = "" if value is None else str(value)
    # 엑셀이 수식으로 읽지 않게 합니다. (=, +, -, @로 시작하는 값)
    return "'" + text if text[:1] in ("=", "+", "-", "@") else text


# --- 개인 ---------------------------------------------------------------------------

def personal(viewer, shipments) -> dict:
    """내 Shipment에 딸린 최근 서류와 일정·B/L 요약, 그리고 아직 확정 전인 초안."""

    documents = sorted((doc for s in shipments for doc in s.documents),
                       key=lambda doc: doc.updated_at or doc.created_at, reverse=True)
    moving = [s for s in shipments if s.status in ACTIVE_STATUSES]
    schedules = []
    for shipment in sorted(moving, key=lambda s: (s.etd is None, s.etd))[:RECENT_SCHEDULES]:
        events = [event for event in shipment.tracking_events if event.event_code != "eta_changed"]
        latest = max(events, key=lambda event: event.event_time) if events else None
        schedules.append({"shipment": shipment, "latest_event": latest})
    return {"documents": documents[:RECENT_DOCUMENTS], "schedules": schedules,
            # 스케줄을 아직 안 고른 건. 사람이 지은 견적명으로 보여 줍니다.
            "drafts": open_drafts(viewer), "cards": status_cards(shipments)}


def open_drafts(viewer) -> list[dict]:
    """확정 전(Shipment 없음) 서류 초안. 목록에 바로 그릴 모양으로 돌려줍니다.

    Shipment가 없어 shipment_row로는 그릴 수 없습니다. 같은 표에 섞지 않고
    "작성 중"으로 따로 세웁니다. 언제 끝났는지 모르는 건과 진행 중인 화물을
    한 줄에 놓으면 상태 칸이 거짓말을 하게 됩니다.
    """

    from app.services import document_draft_service

    rows = []
    for record in document_draft_service.list_open(viewer)[:RECENT_DRAFTS]:
        draft = record.draft or {}
        rows.append({
            "id": record.id,
            "quote_title": record.quote_title,
            "kinds": record.kinds,
            "kind_count": len(record.kinds),
            "route": _draft_route(draft),
            "buyer": str(draft.get("buyer_name") or ""),
            "updated_at": record.updated_at.strftime("%Y-%m-%d") if record.updated_at else "",
            "source": record.source,
        })
    return rows


def _draft_route(draft: dict) -> str:
    """초안의 출발지 → 도착지. 아직 안 골랐으면 빈 문자열."""

    origin = str(draft.get("origin_code") or "").strip()
    destination = str(draft.get("destination_code") or "").strip()
    return f"{origin} → {destination}" if origin and destination else ""


# --- API 모양 ------------------------------------------------------------------------

def _date(value) -> str:
    return value.isoformat() if value else ""


def shipment_row(shipment, owners: dict | None = None) -> dict:
    row = {
        "shipment_id": shipment.shipment_id,
        "project_name": shipment.project_name,
        "route": f"{shipment.origin_code} → {shipment.destination_code}",
        "mode": shipment.mode_label,
        "buyer": shipment.buyer.name if shipment.buyer else "",
        "etd": _date(shipment.etd), "eta": _date(shipment.eta),
        "bl_no": shipment.bl_no or "",
        "status": shipment.status, "status_label": STATUS_LABELS.get(shipment.status, shipment.status),
        "total_cost_krw": shipment.total_cost_krw,
        "created_at": shipment.created_at.strftime("%Y-%m-%d") if shipment.created_at else "",
    }
    # 작성자는 마스터에게만 보냅니다. 일반 회원 응답에는 키 자체가 없습니다.
    if owners is not None:
        row["owner"] = owners.get(shipment.user_id) or ""
    return row
