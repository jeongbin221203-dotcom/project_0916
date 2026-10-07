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
  ALLOWED_ORIGINS=a.com,b.com   Origin 으로 허용할 **추가 호스트**. 프록시가 Host 를 바꿔 넘기는 배포에서 씁니다.
  TRUST_PROXY_HOPS=1     TRUST_PROXY 일 때 믿을 프록시 단계 수(기본 1). 엣지가 둘이면 2.
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

from flask import Flask, g, jsonify, make_response, request, session

DEFAULT_SECRET = "forwardus-local-dev-key"
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# 로그인 시도 — (이메일 + IP) 마다 이 시간 안에 이만큼 틀리면 잠깐 막습니다.
LOGIN_WINDOW_SECONDS = 600
LOGIN_MAX_FAILURES = 10
# 로그인 없이 쓸 수 있는 무거운 길 — 한 접속자가 분당 이만큼까지.
# AI·서류 읽기처럼 **호출마다 비용이 드는** 길(분당 40) — 로그인 없이도 쓸 수 있습니다.
HEAVY_PREFIXES = ("/api/support-chat", "/api/agent", "/api/attach", "/api/doc-pipeline",
                  "/api/intake", "/documents/extract", "/contract/review", "/planning/api/schedules")
HEAVY_LIMIT_PER_MINUTE = 40
# 경로 중간에 번호가 끼는 비용 큰 길 — 끝 부분으로 맞춥니다(전수 점검 3회차: 번호 때문에 제한을 피해 갔습니다).
HEAVY_SUFFIXES = ("/api/ask", "/requirements/upload", "/analyze", "/customs-filing/translate",
                  "/planning/api/departure-check")
# GET 이어도 외부·AI 를 부르는 길
# 조회 값(쿼리)이 붙은 요청만 셉니다 — 화면을 여는 것까지 세지 않습니다.
HEAVY_GET_PREFIXES = ("/documents/api/required-docs", "/planning/api/hs-codes", "/planning/api/tariff",
                      "/tracking/container", "/lookup/")
HEAVY_GET_SUFFIXES = ("/required-docs",)
# 비용이 없는 계산(화물 CBM·중량)은 입력할 때마다 부르므로 넉넉한 바구니로
DRAFT_SUFFIXES = ("/planning/api/cargo",)
# 파일을 올려 OCR·AI 로 읽는 길 — 한 번에 tesseract 를 여러 번 돌려 동시에 몰리면 메모리·CPU 가 바닥납니다.
FILE_SLOT_PREFIXES = ("/documents/extract", "/api/attach", "/api/doc-pipeline", "/api/intake")
FILE_SLOT_SUFFIXES = ("/requirements/upload",)
MAX_CONCURRENT_FILES = 3
# 서류 미리보기·PDF 는 느려서(미리보기 2초, 5장 PDF 6초) 30개가 몰리면 /health 가 35초 걸렸습니다 — 동시에 3개까지.
MAX_CONCURRENT_DRAFTS = 3
# AI 를 동시에 부르는 요청 수 — 일꾼 스레드(8개)를 다 쓰지 않게 남깁니다. 넘으면 503.
MAX_CONCURRENT_HEAVY = 5
# JSON 본문은 파일이 아니라 글이므로 훨씬 작게(파일 올리기만 40MB)
MAX_JSON_BYTES = 4 * 1024 * 1024
# 서류 미리보기·임시저장·PDF — 입력을 멈출 때마다 자동으로 부르므로 더 넉넉히(분당 120).
# 같은 바구니에 두면 서류 칸을 빨리 고치는 정상 사용자가 429 를 받았습니다(관리자 점검 2회차).
DRAFT_PREFIXES = ("/documents/draft/",)
DRAFT_LIMIT_PER_MINUTE = 120
# 로그인한 사용자의 **접속 IP** 한도는 사용자 한도의 이 배수 — 가입을 여러 번 해서 사용자별 한도를
# 우회하는 것을 막고, 사무실 공용 IP 의 여러 직원은 받아 줍니다.
IP_MULTIPLIER_LOGGED_IN = 4
# 가입 — 한 IP 에서 시간당(무료 가입 폭주로 users 표가 부풀고 AI 한도를 우회하는 것을 막습니다)
SIGNUP_WINDOW_SECONDS = 3600
SIGNUP_MAX_PER_IP = 20
RETRY_AFTER_SECONDS = 30
MAX_BODY_BYTES = 40 * 1024 * 1024        # 계약서 20MB · 증빙 15MB 보다 넉넉히
# 폼 한도는 **퍼센트 인코딩된 본문** 크기에 걸립니다 — 한글은 글자당 9바이트라, 계약서 최대 길이(40만 자)가
# 약 3.6MB 입니다. 기본 500KB 에서는 한글 5만 자만 붙여 넣어도 413 이었습니다. 여유를 두어 8MB.
MAX_FORM_BYTES = 8 * 1024 * 1024


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
            if len(self._hits) > 20000:
                # 만료된(최근 1시간 기록이 없는) 키부터 비웁니다. 그래도 많으면 오래된 순.
                # 가입 창은 1시간이라 그보다 짧게 비우면 안 됩니다.
                for key in [k for k, v in self._hits.items() if not v or now - v[-1] > 3600]:
                    self._hits.pop(key, None)
                if len(self._hits) > 20000:
                    for old in list(self._hits)[:5000]:
                        self._hits.pop(old, None)

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)


def client_ip() -> str:
    """접속 IP. IPv6 는 /64(가정·회사에 주는 단위)로 묶습니다 — 주소만 바꿔 제한을 피하지 못하게."""

    addr = request.remote_addr or "?"
    if ":" in addr:
        try:
            import ipaddress
            ip = ipaddress.ip_address(addr.split("%")[0])
            if ip.version == 6:
                return str(ipaddress.ip_network(f"{ip}/64", strict=False).network_address) + "/64"
        except ValueError:
            pass
    return addr


def rate_limit_on(app: Flask) -> bool:
    return bool(app.config.get("RATE_LIMIT_ENABLED", not app.config.get("TESTING", False)))


def login_key(email: str) -> str:
    return f"{client_ip()}|{(email or '').strip().lower()[:200]}"


def login_blocked(app: Flask, email: str) -> bool:
    if not rate_limit_on(app):
        return False
    return app.extensions["login_window"].count(login_key(email), LOGIN_WINDOW_SECONDS) >= LOGIN_MAX_FAILURES


def login_attempt(app: Flask, email: str) -> bool:
    """로그인 **시도를 먼저 기록**하고, 한도를 넘었으면 True(막음).

    예전에는 비밀번호를 검사한 **뒤에** 실패를 적어서, 같은 이메일로 60건을 동시에 보내면 10회 한도인데 37번을
    추측할 수 있었습니다(전수 점검 5회차). 성공하면 login_succeeded 가 기록을 지웁니다.
    """

    if not rate_limit_on(app):
        return False
    window = app.extensions["login_window"]
    key = login_key(email)
    window.add(key)
    count = window.count(key, LOGIN_WINDOW_SECONDS)
    if count == LOGIN_MAX_FAILURES + 1:
        app.logger.warning("로그인 잠금: ip=%s email=%s", client_ip(), mask_email(email))
    return count > LOGIN_MAX_FAILURES


def login_failed(app: Flask, email: str) -> None:
    """실패 기록은 login_attempt 가 이미 했습니다(시도 시점). 남겨 둔 자리 — 호출해도 더 세지 않습니다."""


def login_succeeded(app: Flask, email: str) -> None:
    app.extensions["login_window"].reset(login_key(email))


def mask_email(email: str) -> str:
    """로그에는 이메일 앞 3자만(개인정보를 남기지 않습니다)."""

    text = (email or "").strip().lower()
    return (text[:3] + "***") if text else "-"


def signup_blocked(app: Flask) -> bool:
    """한 IP 에서 시간당 가입 시도가 너무 많으면 막습니다. 시도마다 셉니다."""

    if not rate_limit_on(app):
        return False
    window = app.extensions["signup_window"]
    key = f"signup|{client_ip()}"
    if window.count(key, SIGNUP_WINDOW_SECONDS) >= SIGNUP_MAX_PER_IP:
        app.logger.warning("가입 제한: ip=%s", client_ip())
        return True
    window.add(key)
    return False


def _allowed_hosts() -> set[str]:
    """ALLOWED_ORIGINS 는 'https://a.com' 처럼 주소 전체로 적어도, 'a.com' 으로 적어도 받습니다."""

    hosts = set()
    for item in os.getenv("ALLOWED_ORIGINS", "").split(","):
        item = item.strip().lower().rstrip("/")
        if not item:
            continue
        hosts.add(urlparse(item).netloc if "://" in item else item)
    return hosts


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
    # Flask 기본 설정에 이미 None 으로 들어 있어 setdefault 로는 **꺼진 채**였습니다(관리자 점검 2회차).
    # SameSite 에서 겪은 것과 같은 함정입니다 — 직접 지정합니다. 시험도 기본 설정으로 413 을 확인합니다.
    config["MAX_CONTENT_LENGTH"] = config.get("MAX_CONTENT_LENGTH") or MAX_BODY_BYTES
    # 기본값(500,000)이 이미 들어 있어 `or` 로는 안 바뀝니다 — 큰 쪽을 씁니다.
    config["MAX_FORM_MEMORY_SIZE"] = max(int(config.get("MAX_FORM_MEMORY_SIZE") or 0), MAX_FORM_BYTES)

    if _env_on("TRUST_PROXY") or platform:
        from werkzeug.middleware.proxy_fix import ProxyFix
        try:
            hops = max(1, int(os.getenv("TRUST_PROXY_HOPS", "1")))
        except ValueError:
            hops = 1
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=hops, x_proto=1, x_host=1)

    app.extensions["login_window"] = Window()
    app.extensions["heavy_window"] = Window()
    app.extensions["signup_window"] = Window()
    heavy_slots = threading.BoundedSemaphore(MAX_CONCURRENT_HEAVY)
    file_slots = threading.BoundedSemaphore(MAX_CONCURRENT_FILES)
    draft_slots = threading.BoundedSemaphore(MAX_CONCURRENT_DRAFTS)

    @app.before_request
    def guard():
        # 1) 출처 확인(CSRF) — 브라우저는 POST 에 Origin 을 실어 보냅니다. 우리 주소가 아니면 거절합니다.
        if request.method in UNSAFE_METHODS:
            origin = request.headers.get("Origin")
            if origin:
                try:
                    host = "" if origin == "null" else urlparse(origin).netloc.lower()
                except ValueError:                       # "http://[::1" 처럼 깨진 값이 500 을 냈습니다
                    host = ""
                if not host or (host != (request.host or "").lower() and host not in _allowed_hosts()):
                    app.logger.warning("출처 거절: origin=%.60r host=%r path=%.200r ip=%s", origin, request.host,
                                       request.path, client_ip())
                    return _refuse("요청한 주소가 이 사이트와 다릅니다. 주소창의 주소로 직접 들어와 다시 해 주세요."
                                   " (프록시·별칭 주소를 쓴다면 운영자가 ALLOWED_ORIGINS 에 추가해야 합니다)",
                                   "BAD_ORIGIN", 403)
        # 2) 비용이 드는 길의 횟수 제한 — 접속자별(+ 접속 IP 별) 슬라이딩 창
        if request.is_json:
            # 길이를 미리 알리지 않는 청크 전송은 content_length 가 없어 아래 검사를 건너뛰었습니다 —
            # 30MB JSON 하나로 메모리가 136MB → 950MB(전수 점검 4회차). 읽는 쪽 한도도 함께 낮춥니다.
            request.max_content_length = min(request.max_content_length or MAX_JSON_BYTES, MAX_JSON_BYTES)
        if request.is_json and request.content_length and request.content_length > MAX_JSON_BYTES:
            return _refuse(f"보낸 내용이 너무 큽니다. 글 내용은 {MAX_JSON_BYTES // (1024 * 1024)}MB 이하로 줄여 주세요.",
                           "PAYLOAD_TOO_LARGE", 413)
        heavy_get = (request.method == "GET" and bool(request.args)
                     and (request.path.startswith(HEAVY_GET_PREFIXES) or request.path.endswith(HEAVY_GET_SUFFIXES)))
        if (request.method == "POST" or heavy_get) and rate_limit_on(app):
            path = request.path
            if (any(path.startswith(prefix) for prefix in HEAVY_PREFIXES)
                    or path.endswith(HEAVY_SUFFIXES) or heavy_get):
                bucket, limit = "heavy", HEAVY_LIMIT_PER_MINUTE
            elif any(path.startswith(prefix) for prefix in DRAFT_PREFIXES) or path.endswith(DRAFT_SUFFIXES):
                bucket, limit = "draft", DRAFT_LIMIT_PER_MINUTE
            else:
                bucket, limit = "", 0
            if bucket:
                user_id = session.get("user_id")
                window = app.extensions["heavy_window"]
                keys = [(f"{bucket}|ip{client_ip()}", limit * (IP_MULTIPLIER_LOGGED_IN if user_id else 1))]
                if user_id:
                    keys.append((f"{bucket}|u{user_id}", limit))
                if any(window.count(key, 60) >= cap for key, cap in keys):
                    app.logger.warning("요청 제한: bucket=%s ip=%s user=%s", bucket, client_ip(), user_id or "-")
                    response = _refuse("요청이 너무 많습니다. 잠시 뒤 다시 해 주세요.", "RATE_LIMITED", 429)
                    target = response[0] if isinstance(response, tuple) else response
                    target.headers["Retry-After"] = str(RETRY_AFTER_SECONDS)
                    return response
                for key, _cap in keys:
                    window.add(key)
                if request.method == "POST":
                    pool = None
                    if path.startswith(FILE_SLOT_PREFIXES) or path.endswith(FILE_SLOT_SUFFIXES):
                        pool, name = file_slots, "file_slot"
                    elif bucket == "draft" and path.startswith(DRAFT_PREFIXES):
                        pool, name = draft_slots, "draft_slot"
                    elif path.endswith(("/api/ask", "/analyze", "/translate")) or path.startswith(
                            ("/api/support-chat", "/api/agent", "/contract/review")):
                        pool, name = heavy_slots, "heavy_slot"
                    if pool is not None:
                        if not pool.acquire(blocking=False):
                            response = _refuse("지금 요청이 몰려 있습니다. 잠시 뒤 다시 해 주세요.", "BUSY", 503)
                            target = response[0] if isinstance(response, tuple) else response
                            target.headers["Retry-After"] = str(RETRY_AFTER_SECONDS)
                            return response
                        setattr(g, name, pool)
        return None

    @app.teardown_request
    def release_slot(_exc):
        for name in ("heavy_slot", "file_slot", "draft_slot"):
            pool = g.pop(name, None)
            if pool is not None:
                pool.release()

    @app.errorhandler(413)
    def too_large(_error):
        mb = MAX_BODY_BYTES // (1024 * 1024)
        form = MAX_FORM_BYTES // (1024 * 1024)
        return _refuse(f"보낸 내용이 너무 큽니다. 파일은 {mb}MB 이하로, 붙여 넣은 글은 약 {form}MB 이하"
                       "(한글 약 80만 자)로 줄여 주세요.", "PAYLOAD_TOO_LARGE", 413)

    @app.after_request
    def headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        if request.is_secure:
            response.headers.setdefault("Strict-Transport-Security", "max-age=15552000")
        # 화면·JSON 은 저장하지 않게 — 로그아웃 뒤 '뒤로 가기'에 이전 사용자의 화면이 남았습니다.
        kind = (response.mimetype or "")
        if (kind in ("text/html", "application/json", "text/csv", "text/plain")
                and not request.path.startswith("/static")
                and "Cache-Control" not in response.headers):
            response.headers["Cache-Control"] = "no-store"
        return response
