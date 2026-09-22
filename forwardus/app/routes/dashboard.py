"""Operations dashboard."""

from __future__ import annotations

from flask import Blueprint, render_template

from app.routes.auth import current_user, login_required_response
from app.services import analytics_service

dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")


# '내 Dashboard'는 로그인한 사람의 이름 메뉴에서만 들어옵니다.
# 주소로 바로 들어온 경우에는 로그인 화면으로 보냈다가 다시 돌려보냅니다.
@dashboard_bp.before_request
def require_login():
    return login_required_response()


@dashboard_bp.get("")
def index():
    # 일반 회원은 자기 Shipment로, 마스터는 모든 사용자의 Shipment로 집계합니다.
    viewer = current_user()
    return render_template("dashboard/index.html", viewer=viewer,
                           **analytics_service.build_dashboard(viewer))
