"""Operations dashboard."""

from __future__ import annotations

from flask import Blueprint, redirect, render_template, request, url_for

from app.routes.auth import current_user
from app.services import analytics_service

dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")


# '내 Dashboard'는 로그인한 사람의 이름 메뉴에서만 들어옵니다.
# 주소로 바로 들어온 경우에는 로그인 화면으로 보냈다가 다시 돌려보냅니다.
@dashboard_bp.before_request
def require_login():
    if not current_user():
        return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
    return None


@dashboard_bp.get("")
def index():
    return render_template("dashboard/index.html", **analytics_service.build_dashboard())
