"""보안 울타리 — 쿠키·요청 출처·횟수 제한·응답 머리글·비밀키.

전수 점검 1회차(2026-10-06, 관리자 관점)에서 나온 것을 한곳에 모았습니다.

  · 상태를 바꾸는 요청(POST·PUT·PATCH·DELETE)에 **CSRF 방어가 없었습니다.** 다른 사이트의
    폼이 로그인한 마스터의 브라우저로 "상태 강제 변경"을 보낼 수 있었습니다.
  · 로그인 시도 횟수 제한이 없었습니다. 같은 계정에 30번 틀려도 계속 받았습니다.
  · 로그인 없이 쓰는 AI·외부 API 길(상담·에이전트·서류 읽기)에 제한이 없어, 몇 건의 느린 요청으로
    일꾼(스레드 8개)이 막히고 AI 호출비가 샐 수 있었습니다.
  · 로그아웃 뒤 '뒤로 가기'에 이전 사용자의 대시보드가 남았습니다(Cache-Control 없음).
  · 보안 응답 머리글이 없었고, SECRET_KEY 를 안 넣으면 알려진 기본 키로 마스터 쿠키를 만들 수 있었습니다.

환경 변수
  REQUIRE_SECRET_KEY=1   (또는 RENDER·DYNO 가 있으면) SECRET_KEY 가 기본값이면 **기동을 멈춥니다.**
  SESSION_COOKIE_SECURE=1  (또는 RENDER 가 있으면) 쿠키를 https 로만 보냅니다.
  TRUST_PROXY=1          (또는 RENDER·DYNO) 프록시가 붙인 실제 접속 IP·주소를 믿습니다.
                         이게 꺼진 채 프록시 뒤에 있으면 모든 사용자가 같은 IP 로 보여 횟수 제한이 한꺼번에 걸립니다.

테스트(TESTING)에서는 횟수 제한을 꺼 둡니다. 시험이 같은 주소로 수백 번 부르기 때문입니다.
제한을 시험할 때는 config["RATE_LIMIT_ENABLED"] = True 로 켭니다.
"""

from __future__ import annotations

import os
import threading
import time
from urllib.parse import urlparse

from flask import Flask, jsonify, make_response, request, session

DEFAULT_SECRET = "forwardus-local-dev-key"
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# 로그인 시도 — (이메일 + IP) 마다 이 시간 안에 이만큼 틀리면 잠깐 막습니다.
LOGIN_WINDOW_SECONDS = 600
LOGIN_MAX_FAILURES = 10
# 로그인 없이 쓸 수 있는 무거운 길 — 한 접속자가 분당 이만큼까지.
HEAVY_PREFIXES = ("/api/support-chat", "/api/agent", "/api/attach", "/api/doc-pipeline",
                  "/api/intake", "/documents/extract", "/documents/draft/", "/contract/review",
                  "/planning/api/schedules")
HEAVY_LIMIT_PER_MINUTE = 40
MAX_BODY_BYTES = 40 * 1024 * 1024        # 계약서 20MB · 증빙 15MB 보다 넉넉히


def _env_on(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes", "on")


def on_platform() -> bool:
    """Render·Heroku 같은 운영 환경인가."""

    return bool(os.getenv("RENDER") or os.getenv("DYNO"))


class Window:
    """접속자별로 최근 시각을 세는 슬라이딩 창. 프로세스 안에서만 셉니다(일꾼마다 따로)."""

    def __init__(self) -> None:
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def count(self, key: str, seconds: float, now: float | None = None) -> int:
        now = now if now is not None else time.monotonic()
        with self._lock:
            recent = [t for t in self._hits.get(key, ()) if now - t < seconds]
            self._hits[key] = recent
            return len(recent)

    def add(self, key: str, now: float | None = None) -> None:
        now = now if now is not None else time.monotonic()
        with self._lock:
            self._hits.setdefault(key, []).append(now)
            if len(self._hits) > 20000:          # 오래된 접속자부터 비웁니다
                for old in list(self._hits)[:5000]:
                    self._hits.pop(old, None)

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)


def client_ip() -> str:
    return request.remote_addr or "?"


def rate_limit_on(app: Flask) -> bool:
    return bool(app.config.get("RATE_LIMIT_ENABLED", not app.config.get("TESTING", False)))


def login_key(email: str) -> str:
    return f"{client_ip()}|{(email or '').strip().lower()[:200]}"


def login_blocked(app: Flask, email: str) -> bool:
    if not rate_limit_on(app):
        return False
    return app.extensions["login_window"].count(login_key(email), LOGIN_WINDOW_SECONDS) >= LOGIN_MAX_FAILURES


def login_failed(app: Flask, email: str) -> None:
    if rate_limit_on(app):
        app.extensions["login_window"].add(login_key(email))


def login_succeeded(app: Flask, email: str) -> None:
    app.extensions["login_window"].reset(login_key(email))


def _wants_json() -> bool:
    return (request.path.startswith("/api") or "/api/" in request.path or request.is_json
            or "application/json" in (request.headers.get("Accept") or ""))


def _refuse(message: str, code: str, status: int):
    if _wants_json():
        return jsonify({"success": False, "error_code": code, "message": message}), status
    response = make_response(message, status)
    response.headers["Content-Type"] = "text/plain; charset=utf-8"
    return response


def install(app: Flask) -> None:
    """create_app 이 한 번 부릅니다."""

    config = app.config
    secret = config.get("SECRET_KEY") or ""
    platform = on_platform()
    if secret == DEFAULT_SECRET and not config.get("TESTING") and not config.get("DEBUG"):
        if platform or _env_on("REQUIRE_SECRET_KEY"):
            raise RuntimeError("SECRET_KEY 가 기본값입니다. 환경 변수 SECRET_KEY 에 긴 무작위 글자를 넣어야 "
                               "기동합니다 — 기본 키로는 누구나 로그인 쿠키(마스터 포함)를 만들 수 있습니다.")
        app.logger.warning("SECRET_KEY 가 기본값입니다. 로컬 개발에서만 쓰세요.")

    # 쿠키 — 다른 사이트가 보낸 요청에는 실리지 않게(Lax). https 환경이면 https 로만.
    # Flask 기본 설정에 이미 None 으로 들어 있어 setdefault 로는 바뀌지 않습니다.
    config["SESSION_COOKIE_SAMESITE"] = config.get("SESSION_COOKIE_SAMESITE") or "Lax"
    config["SESSION_COOKIE_HTTPONLY"] = True
    if _env_on("SESSION_COOKIE_SECURE") or platform:
        config["SESSION_COOKIE_SECURE"] = True
    config.setdefault("MAX_CONTENT_LENGTH", MAX_BODY_BYTES)

    if _env_on("TRUST_PROXY") or platform:
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    app.extensions["login_window"] = Window()
    app.extensions["heavy_window"] = Window()

    @app.before_request
    def guard():
        # 1) 출처 확인(CSRF) — 브라우저는 POST 에 Origin 을 실어 보냅니다. 우리 주소가 아니면 거절합니다.
        if request.method in UNSAFE_METHODS:
            origin = request.headers.get("Origin")
            if origin and origin != "null":
                if urlparse(origin).netloc.lower() != (request.host or "").lower():
                    return _refuse("다른 사이트에서 보낸 요청은 받지 않습니다.", "BAD_ORIGIN", 403)
            elif origin == "null":
                return _refuse("출처를 알 수 없는 요청은 받지 않습니다.", "BAD_ORIGIN", 403)
        # 2) 로그인 없이 쓰는 무거운 길의 횟수 제한
        if request.method == "POST" and rate_limit_on(app) \
                and any(request.path.startswith(prefix) for prefix in HEAVY_PREFIXES):
            who = f"u{session.get('user_id')}" if session.get("user_id") else f"ip{client_ip()}"
            window = app.extensions["heavy_window"]
            if window.count(who, 60) >= HEAVY_LIMIT_PER_MINUTE:
                return _refuse("요청이 너무 많습니다. 잠시 뒤 다시 해 주세요.", "RATE_LIMITED", 429)
            window.add(who)
        return None

    @app.errorhandler(413)
    def too_large(_error):
        mb = MAX_BODY_BYTES // (1024 * 1024)
        return _refuse(f"보낸 내용이 너무 큽니다. {mb}MB 이하로 줄여 주세요.", "PAYLOAD_TOO_LARGE", 413)

    @app.after_request
    def headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        if request.is_secure:
            response.headers.setdefault("Strict-Transport-Security", "max-age=15552000")
        # 화면·JSON 은 저장하지 않게 — 로그아웃 뒤 '뒤로 가기'에 이전 사용자의 화면이 남았습니다.
        kind = (response.mimetype or "")
        if (kind in ("text/html", "application/json") and not request.path.startswith("/static")
                and "Cache-Control" not in response.headers):
            response.headers["Cache-Control"] = "no-store"
        return response
