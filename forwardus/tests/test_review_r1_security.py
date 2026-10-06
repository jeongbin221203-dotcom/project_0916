"""전수 점검 1회차(2026-10-06) — 관리자·사용자 관점에서 나온 보안·서버 오류.

  · 로그인 없이 500 을 낼 수 있던 곳(형식이 다른 JSON 값)
  · CSRF(출처 확인) · 쿠키 · 로그인 시도 제한 · 보안 머리글 · Cache-Control
  · 운영자 진단 화면(/lookup/sources) 권한 · 비밀키 기본값 · 요청 크기
  · 초안 PDF 글줄 나누기가 긴 글에서 O(n²) 였던 것
"""

from __future__ import annotations

import io
import time

import pytest

from app import create_app, db
from config import TestConfig


@pytest.fixture()
def app():
    flask_app = create_app(TestConfig)
    flask_app.config["RATE_LIMIT_ENABLED"] = False
    with flask_app.app_context():
        db.create_all()
        yield flask_app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def _signup(client, email="a@example.com"):
    return client.post("/auth/signup", data={"email": email, "password": "secret123",
                                             "password_confirm": "secret123"})


# ── 로그인 없이 500 을 내던 입력 ──────────────────────────────────────────────
BAD_VALUES = [{"a": 1}, [1, 2], 5, True, -1, 1e308, "xxxxxxxxxx"]


@pytest.mark.parametrize("value", BAD_VALUES, ids=[repr(v)[:14] for v in BAD_VALUES])
@pytest.mark.parametrize("path,key", [
    ("/api/support-chat", "question"),
    ("/api/agent", "draft"),
    ("/documents/draft/commercial_invoice.pdf", "draft"),
    ("/documents/suggest-name", "items"),
])
def test_형식이_다른_값을_보내도_500이_아니다(client, path, key, value):
    response = client.post(path, json={key: value})
    assert response.status_code < 500 or response.status_code == 503, (path, key, value)


@pytest.mark.parametrize("path,key", [("/documents/draft/save", "id"), ("/documents/start", "draft_id")])
def test_엄청_큰_숫자_id_도_500이_아니다(client, path, key):
    _signup(client)
    for value in (1e308, 10 ** 40, -5, "9" * 40):
        response = client.post(path, json={key: value})
        assert response.status_code < 500, (path, value, response.status_code)


# ── 출처 확인(CSRF) ──────────────────────────────────────────────────────────
def test_다른_사이트가_보낸_POST_는_거절한다(client):
    _signup(client)
    response = client.post("/shipments/EXP-2026-00001/status", data={"status": "cancelled"},
                           headers={"Origin": "https://evil.example"})
    assert response.status_code == 403


def test_Origin_이_null_이어도_거절한다(client):
    assert client.post("/auth/logout", headers={"Origin": "null"}).status_code == 403


def test_같은_출처_POST_와_Origin_이_없는_POST_는_통과한다(client):
    host = "localhost"
    same = client.post("/auth/signup", data={"email": "b@example.com", "password": "secret123",
                                             "password_confirm": "secret123"},
                       headers={"Origin": f"http://{host}"})
    assert same.status_code != 403
    assert client.post("/auth/logout").status_code != 403


def test_GET_은_Origin_이_달라도_막지_않는다(client):
    assert client.get("/", headers={"Origin": "https://other.example"}).status_code == 200


# ── 쿠키 · 머리글 · 캐시 ──────────────────────────────────────────────────────
def test_세션_쿠키는_SameSite_Lax_와_HttpOnly(client):
    cookie = _signup(client).headers.get("Set-Cookie", "")
    assert "SameSite=Lax" in cookie and "HttpOnly" in cookie


def test_보안_머리글이_붙는다(client):
    headers = client.get("/").headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "SAMEORIGIN"
    assert "Referrer-Policy" in headers


def test_화면과_JSON_은_저장하지_않게_한다(client):
    _signup(client)
    assert client.get("/dashboard").headers["Cache-Control"] == "no-store"
    assert client.get("/api/work-draft").headers["Cache-Control"] == "no-store"


def test_정적_파일은_캐시를_막지_않는다(client):
    response = client.get("/static/css/base.css")
    assert response.headers.get("Cache-Control") != "no-store"


# ── 로그인 시도 제한 ─────────────────────────────────────────────────────────
def test_로그인을_열_번_틀리면_잠깐_막는다(app):
    app.config["RATE_LIMIT_ENABLED"] = True
    client = app.test_client()
    _signup(client, "c@example.com")
    client.post("/auth/logout")
    codes = [client.post("/auth/login", data={"email": "c@example.com", "password": "wrong"}).status_code
             for _ in range(12)]
    assert codes[:10] == [401] * 10 and codes[10:] == [429, 429]
    # 맞는 비밀번호도 막힌 동안은 안 받습니다
    assert client.post("/auth/login", data={"email": "c@example.com", "password": "secret123"}).status_code == 429


def test_다른_이메일은_따로_센다(app):
    app.config["RATE_LIMIT_ENABLED"] = True
    client = app.test_client()
    for _ in range(10):
        client.post("/auth/login", data={"email": "x@example.com", "password": "wrong"})
    assert client.post("/auth/login", data={"email": "y@example.com", "password": "wrong"}).status_code == 401


def test_로그인에_성공하면_실패_횟수를_지운다(app):
    app.config["RATE_LIMIT_ENABLED"] = True
    client = app.test_client()
    _signup(client, "d@example.com")
    client.post("/auth/logout")
    for _ in range(5):
        client.post("/auth/login", data={"email": "d@example.com", "password": "wrong"})
    assert client.post("/auth/login", data={"email": "d@example.com", "password": "secret123"}).status_code == 302


def test_없는_계정과_있는_계정의_응답은_같다(client):
    _signup(client, "e@example.com")
    client.post("/auth/logout")
    a = client.post("/auth/login", data={"email": "e@example.com", "password": "wrong"})
    b = client.post("/auth/login", data={"email": "nobody@example.com", "password": "wrong"})
    assert a.status_code == b.status_code == 401
    assert "맞지 않습니다" in a.get_data(as_text=True) and "맞지 않습니다" in b.get_data(as_text=True)


def test_공백만_있는_비밀번호는_가입할_수_없다(client):
    response = client.post("/auth/signup", data={"email": "f@example.com", "password": " " * 8,
                                                 "password_confirm": " " * 8})
    assert response.status_code == 400


# ── 무거운 길의 횟수 제한 ────────────────────────────────────────────────────
def test_로그인_없이_쓰는_무거운_길은_분당_제한이_있다(app):
    app.config["RATE_LIMIT_ENABLED"] = True
    client = app.test_client()
    codes = [client.post("/api/support-chat", json={"question": "안녕"}).status_code for _ in range(45)]
    assert 429 in codes and codes.index(429) >= 40


def test_가벼운_길은_제한하지_않는다(app):
    app.config["RATE_LIMIT_ENABLED"] = True
    client = app.test_client()
    assert all(client.get("/health").status_code == 200 for _ in range(60))


# ── 운영자 진단 화면 ─────────────────────────────────────────────────────────
def test_진단_화면은_로그인_없이_열리지_않는다(client):
    for path in ("/lookup/sources", "/lookup/sources/check"):
        assert client.get(path).status_code in (302, 401)


def test_일반_회원은_진단_화면에서_403(client):
    _signup(client)
    for path in ("/lookup/sources", "/lookup/sources/check"):
        assert client.get(path).status_code == 403


def test_마스터는_진단_화면을_본다(app):
    from app.models import User

    client = app.test_client()
    _signup(client, "m@example.com")
    user = User.query.filter_by(email="m@example.com").first()
    user.is_master = True
    db.session.commit()
    assert client.get("/lookup/sources").status_code == 200


# ── 비밀키 · 요청 크기 ───────────────────────────────────────────────────────
def test_운영_환경에서_기본_비밀키면_기동을_멈춘다(monkeypatch):
    class Prod(TestConfig):
        TESTING = False
        DEBUG = False
        SECRET_KEY = "forwardus-local-dev-key"

    monkeypatch.setenv("RENDER", "true")
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app(Prod)


def test_REQUIRE_SECRET_KEY_도_같다(monkeypatch):
    class Prod(TestConfig):
        TESTING = False
        DEBUG = False
        SECRET_KEY = "forwardus-local-dev-key"

    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.delenv("DYNO", raising=False)
    monkeypatch.setenv("REQUIRE_SECRET_KEY", "1")
    with pytest.raises(RuntimeError):
        create_app(Prod)


def test_로컬에서는_기본_비밀키로_뜬다(monkeypatch):
    class Local(TestConfig):
        TESTING = False
        DEBUG = False
        SECRET_KEY = "forwardus-local-dev-key"

    for name in ("RENDER", "DYNO", "REQUIRE_SECRET_KEY"):
        monkeypatch.delenv(name, raising=False)
    assert create_app(Local) is not None


def test_운영_환경이면_쿠키를_https_로만_보낸다(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    flask_app = create_app(TestConfig)
    assert flask_app.config["SESSION_COOKIE_SECURE"] is True


def test_너무_큰_본문은_413_이다(app):
    app.config["MAX_CONTENT_LENGTH"] = 1024
    client = app.test_client()
    response = client.post("/api/support-chat", data=b"x" * 5000, content_type="application/json")
    assert response.status_code == 413


# ── PDF 글줄 나누기 ──────────────────────────────────────────────────────────
def test_띄어쓰기_없는_긴_글도_초안_PDF_가_빨리_나온다(client):
    start = time.monotonic()
    response = client.post("/documents/draft/commercial_invoice.pdf",
                           json={"draft": {"exporter_name": "Y" * 20000, "buyer_name": "B" * 5000,
                                           "product_description": "P" * 5000}})
    assert time.monotonic() - start < 10
    assert response.status_code in (200, 400)


def test_글줄_나누기는_폭을_넘지_않는다():
    from PIL import Image, ImageDraw, ImageFont

    from app.processors import document_form

    draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    try:
        font = ImageFont.truetype("arial.ttf", 20)
    except OSError:
        pytest.skip("시험용 글꼴이 없는 환경")
    lines = document_form._wrap(draw, "A" * 300 + " " + "가" * 100 + "\nsecond line", font, 400)
    assert all(draw.textlength(line, font=font) <= 400 for line in lines)
    assert "".join(lines).replace(" ", "").count("A") == 300
    assert lines[-1] == "second line"
