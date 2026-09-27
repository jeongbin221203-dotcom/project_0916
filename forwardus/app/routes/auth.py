"""로그인 · 회원가입 · 로그아웃."""

from __future__ import annotations

import re
from functools import wraps
from urllib.parse import urlparse

from flask import (Blueprint, flash, g, jsonify, redirect, render_template, request,
                   session, url_for)

from app.extensions import db
from app.models import User

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LENGTH = 8


def current_user() -> User | None:
    """세션에 담긴 회원을 돌려줍니다. 한 요청 안에서는 한 번만 읽습니다.

    기억해 둔 회원이 세션의 회원과 다르면 다시 읽습니다. 앱 컨텍스트를 여러
    요청이 나눠 쓰는 경우(테스트)에 앞 요청의 회원이 남지 않게 합니다.
    """

    user_id = session.get("user_id")
    cached = g.get("current_user_cache")
    if cached is None or cached[0] != user_id:
        cached = (user_id, db.session.get(User, user_id) if user_id else None)
        g.current_user_cache = cached
    return cached[1]


def login_required_response():
    """로그인하지 않았을 때 돌려줄 응답. 로그인했으면 None입니다.

    화면은 로그인 화면으로 보냈다가 돌아오게 하고, API는 401 JSON으로 답합니다.
    """

    if current_user():
        return None
    wants_json = (request.path.startswith("/api") or "/api/" in request.path
                  or request.is_json)
    if wants_json:
        return jsonify({"success": False, "error_code": "LOGIN_REQUIRED",
                        "message": "로그인이 필요합니다."}), 401
    # 폼을 보낸 경우에는 그 주소로 돌아갈 수 없으므로 로그인 화면만 엽니다.
    next_url = request.full_path.rstrip("?") if request.method == "GET" else None
    return redirect(url_for("auth.login", next=next_url))


def login_required(view):
    """이 화면은 로그인한 회원만 씁니다."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        return login_required_response() or view(*args, **kwargs)

    return wrapper


def _safe_next(target: str | None) -> str:
    """로그인 뒤 돌아갈 곳. 바깥 사이트로 보내지 않도록 우리 경로만 받습니다."""

    if target and target.startswith("/") and not target.startswith("//") \
            and "\\" not in target:
        parsed = urlparse(target)
        if not parsed.scheme and not parsed.netloc:
            return target
    return url_for("dashboard.index")


def _log_in(user: User) -> None:
    session.clear()
    session["user_id"] = user.id
    g.current_user_cache = (user.id, user)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(url_for("dashboard.index"))

    next_url = request.values.get("next", "")
    email = ""
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first() if email else None
        if user and user.check_password(password):
            _log_in(user)
            flash(f"{user.name or user.email}님, 환영합니다.", "success")
            return redirect(_safe_next(next_url))
        flash("이메일 또는 비밀번호가 맞지 않습니다.", "error")
        return render_template("auth/login.html", email=email, next_url=next_url), 401

    return render_template("auth/login.html", email=email, next_url=next_url)


@auth_bp.route("/signup", methods=["GET", "POST"])
def signup():
    if current_user():
        return redirect(url_for("dashboard.index"))

    form = {"email": "", "name": ""}
    error = ""
    if request.method == "POST":
        form["email"] = request.form.get("email", "").strip().lower()
        form["name"] = request.form.get("name", "").strip()
        password = request.form.get("password", "")
        password_confirm = request.form.get("password_confirm", "")

        if not EMAIL_PATTERN.match(form["email"]) or len(form["email"]) > 200:
            error = "올바른 이메일 주소를 적어 주세요."
        elif len(form["name"]) > 100:
            error = "이름은 100자까지 적을 수 있습니다."
        elif len(password) < MIN_PASSWORD_LENGTH:
            error = f"비밀번호는 {MIN_PASSWORD_LENGTH}자 이상이어야 합니다."
        elif password != password_confirm:
            error = "비밀번호 확인이 일치하지 않습니다."
        elif User.query.filter_by(email=form["email"]).first():
            error = "이미 가입된 이메일입니다."

        if not error:
            user = User(email=form["email"], name=form["name"])
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            _log_in(user)
            flash("회원가입이 완료되었습니다.", "success")
            return redirect(url_for("dashboard.index"))
        return render_template("auth/signup.html", form=form, error=error), 400

    return render_template("auth/signup.html", form=form, error=error)


@auth_bp.post("/logout")
def logout():
    session.clear()
    g.pop("current_user_cache", None)
    flash("로그아웃되었습니다.", "success")
    return redirect(url_for("home.index"))
