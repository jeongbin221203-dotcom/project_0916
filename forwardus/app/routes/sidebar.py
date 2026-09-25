"""왼쪽 사이드바에 들어갈 것. 모든 화면이 같이 씁니다. (base.html → _sidebar.html)

원래 시작 화면(home.py)에만 있던 목록을 옮겼습니다. 어느 화면에 있든 같은 자리에
같은 항목이 있고, 지금 있는 곳만 표시가 바뀝니다.
"""

from __future__ import annotations

from flask import request, url_for

# key는 "지금 어디에 있나"를 가릴 때 씁니다. blueprints가 그 항목에 속한 화면들입니다.
RAIL = [
    {"key": "home", "icon": "🏠", "tone": "", "label": "홈", "endpoint": "home.index",
     "note": "대화로 묻고 서류를 만듭니다", "blueprints": ("home",)},
    # 서류를 먼저 두었습니다. 대부분 서류를 만들다가 운임을 궁금해합니다.
    {"key": "documents", "icon": "📄", "tone": "green", "label": "수출서류작성", "endpoint": "document.new",
     "note": "상업송장·포장명세서를 Shipment 데이터로 자동 작성합니다", "blueprints": ("document",)},
    {"key": "planning", "icon": "📦", "tone": "blue", "label": "운송 예상 견적", "endpoint": "planning.new",
     "note": "출발·도착지와 화물을 넣으면 스케줄과 물류비를 봅니다", "blueprints": ("planning",)},
    # Shipment 상세·추적·AI 도우미 화면은 Dashboard 아래에 있습니다.
    # Dashboard는 사이드바에 내놓지 않습니다. 이용자는 홈에서 대화로 일을 끝내고,
    # 현황 화면은 마스터가 볼 때만 필요합니다. 주소(/dashboard)는 그대로 살아 있습니다.
    {"key": "dashboard", "icon": "📊", "tone": "violet", "label": "Dashboard", "endpoint": "dashboard.index",
     "note": "내 Shipment 현황 (마스터는 전체)", "master_only": True,
     "blueprints": ("dashboard", "shipment", "tracking", "assistant")},
    # 위쪽 메뉴에 있던 조회 두 가지를 이리로 옮겼습니다. 조회는 어느 화면에서나 자주 씁니다.
    {"key": "container", "icon": "🔎", "tone": "blue", "label": "컨테이너 조회",
     "endpoint": "tracking.container_lookup",
     "note": "컨테이너 번호로 화물 위치를 봅니다", "blueprints": ()},
    {"key": "lookup", "icon": "🏛", "tone": "green", "label": "관세청 조회", "endpoint": "lookup.index",
     "note": "HS부호·관세율·수출입 통계를 관세청 자료로 찾습니다", "blueprints": ("lookup",)},
]
RECENT_COUNT = 3


def active_key() -> str:
    blueprint = request.blueprint or ""
    # 컨테이너 조회는 tracking 안에 있지만 Shipment 화면이 아닙니다. 사이드바에서는 따로 봅니다.
    if request.endpoint == "tracking.container_lookup":
        return "container"
    return next((item["key"] for item in RAIL if blueprint in item["blueprints"]), "")


def context(viewer) -> dict:
    """사이드바 조각이 쓰는 값. 최근 Shipment는 보는 사람 것만(로그인 전이면 없음)."""

    from app.services import shipment_service

    current = active_key()
    master = bool(viewer is not None and getattr(viewer, "is_master", False))
    items = [{**item, "url": url_for(item["endpoint"]), "active": item["key"] == current}
             for item in RAIL if master or not item.get("master_only")]
    recent = shipment_service.list_shipments(viewer=viewer)[:RECENT_COUNT] if viewer else []
    return {"links": items, "recent": recent}
