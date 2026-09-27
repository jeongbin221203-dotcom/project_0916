"""왼쪽 사이드바에 들어갈 것. 모든 화면이 같이 씁니다. (base.html → _sidebar.html)

원래 시작 화면(home.py)에만 있던 목록을 옮겼습니다. 어느 화면에 있든 같은 자리에
같은 항목이 있고, 지금 있는 곳만 표시가 바뀝니다.
"""

from __future__ import annotations

from flask import request, url_for

# key는 "지금 어디에 있나"를 가릴 때 씁니다. blueprints가 그 항목에 속한 화면들입니다.
#
# 순서: 홈 → 서류 작성 → 운송 계획 → Dashboard → 조회 두 가지.
# 서류 작성이 운송 계획보다 앞입니다. 서류에 적은 값이 운송 계획 칸을 미리 채우기
# 때문입니다(work_draft_service). 시작 화면의 단추 순서(routes/home.py)와도 같습니다.
# 두 곳의 순서가 다르면 같은 일을 하는 자리를 화면마다 다른 곳에서 찾게 됩니다.
RAIL = [
    {"key": "home", "icon": "🏠", "tone": "", "label": "홈", "endpoint": "home.index",
     "note": "대화로 묻고 서류를 만듭니다", "blueprints": ("home",)},
    # 서류를 먼저 두었습니다. 대부분 서류를 만들다가 운임을 궁금해합니다.
    {"key": "documents", "icon": "📄", "tone": "green", "label": "수출 서류 작성", "endpoint": "document.new",
     "note": "상업송장·포장명세서를 Shipment 데이터로 자동 작성합니다", "blueprints": ("document",)},
    {"key": "planning", "icon": "📦", "tone": "blue", "label": "운송 예상 견적", "endpoint": "planning.new",
     "note": "출발·도착지와 화물을 넣으면 스케줄과 물류비를 봅니다", "blueprints": ("planning",)},
    # 위쪽 메뉴에 있던 조회 두 가지를 이리로 옮겼습니다. 조회는 어느 화면에서나 자주 씁니다.
    {"key": "container", "icon": "🔎", "tone": "blue", "label": "컨테이너 조회",
     "endpoint": "tracking.container_lookup",
     "note": "컨테이너 번호로 화물 위치를 봅니다", "blueprints": ()},
    {"key": "lookup", "icon": "🏛", "tone": "green", "label": "관세청 조회", "endpoint": "lookup.index",
     "note": "HS부호·관세율·수출입 통계를 관세청 자료로 찾습니다", "blueprints": ("lookup",)},
]

# Dashboard는 사이드바에 두지 않습니다. (2026-09-25 사용자 결정)
#
# 없앤 것이 아니라 자리를 옮긴 것입니다. 들어가는 길이 이미 둘 있습니다.
#   - 오른쪽 위 이름 메뉴 → "내 Dashboard" (마스터는 "전체 Dashboard")
#   - 사이드바 [🧾 최근] 을 열면 나오는 "Dashboard →"
# 사이드바는 매일 쓰는 길(홈·서류·견적·조회)만 둡니다.
#
# 화면과 주소(dashboard.index)는 그대로 살아 있습니다. 아래 목록은 "지금 어느
# 화면인가"를 가릴 때도 쓰이는데, Shipment 상세·추적·AI 도우미는 사이드바에
# 표시할 항목이 없으므로 active_key()가 빈 값을 돌려주면 됩니다.
# (오른쪽 위 메뉴의 표시는 nav_active = request.blueprint 로 따로 정해집니다)
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
