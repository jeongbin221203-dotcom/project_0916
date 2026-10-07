"""전수 점검 2회차(2026-10-07) — 관리자 관점.

1회차 보안 수정의 구멍(413 이 꺼져 있던 것 · 가입으로 한도 우회), 배포 직후 겪을 문제(프록시·끊긴
DB 연결), 마스터 대시보드(질의 수·KPI 카드·통계), 운영 위생(/health · CSV · 기동 실패).
"""

from __future__ import annotations

import pytest
from sqlalchemy import event

from app import create_app, db
from app.models import Shipment, User
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
def limited(app):
    app.config["RATE_LIMIT_ENABLED"] = True
    return app


def _signup(client, email):
    return client.post("/auth/signup", data={"email": email, "password": "secret123",
                                             "password_confirm": "secret123"})


# ── 413 — **기본 설정 그대로**(전에는 시험이 값을 직접 넣어 꺼져 있던 것을 가렸습니다) ────────────────
def test_기본_설정에서_본문_상한이_켜져_있다(app):
    assert app.config["MAX_CONTENT_LENGTH"] == 40 * 1024 * 1024
    assert app.config["MAX_FORM_MEMORY_SIZE"] >= 8 * 1024 * 1024


def test_상한을_넘는_본문은_기본_설정에서_413(app):
    client = app.test_client()
    response = client.post("/api/support-chat", data=b"x" * (41 * 1024 * 1024), content_type="application/json")
    assert response.status_code == 413
    assert response.get_json()["error_code"] == "PAYLOAD_TOO_LARGE"
    assert "4MB" in response.get_json()["message"]


def test_붙여_넣은_긴_계약서_폼은_받는다(app):
    """계약서 최대 길이(40만 자)의 한글은 폼으로 보내면 약 3.6MB — 폼 기본 한도(500KB)에 걸렸습니다."""

    client = app.test_client()
    text = ("계약서 조항입니다. " * 40_000)[:400_000]                 # 40만 자 한글
    assert len(text) == 400_000
    response = client.post("/contract/review", data={"text": text})
    assert response.status_code != 413


# ── 가입으로 한도 우회 ────────────────────────────────────────────────────────────────
def test_한_IP_의_가입_시도는_시간당_제한이_있다(limited):
    # 가입하면 그 클라이언트는 로그인 상태라 가입 화면이 바로 넘어갑니다 — 시도마다 새 브라우저로.
    codes = [_signup(limited.test_client(), f"u{i}@example.com").status_code for i in range(23)]
    assert 429 in codes and codes.index(429) == 20
    assert all(code in (302, 400) for code in codes[:20])


def test_가입이_막혀도_로그인은_할_수_있다(limited):
    client = limited.test_client()
    _signup(client, "first@example.com")
    client.post("/auth/logout")
    for i in range(25):
        _signup(client, f"x{i}@example.com")
    assert client.post("/auth/login", data={"email": "first@example.com", "password": "secret123"}).status_code == 302


def test_계정을_여러_개_만들어도_접속_IP_한도는_넘지_못한다(limited):
    """사용자별 40 한도를 계정 갈아타기로 우회하는 길 — IP 한도(로그인 사용자는 4배 = 160)가 막습니다."""

    codes = []
    for index in range(6):
        client = limited.test_client()
        with client.session_transaction() as session:
            session["user_id"] = 1000 + index                 # 가입 제한과 따로 — 세션만 달리 가진 사용자들
        codes += [client.post("/api/support-chat", json={"question": "안녕"}).status_code for _ in range(35)]
    assert 429 in codes and codes.index(429) >= 160 - 1


def test_서류_미리보기는_AI_바구니와_따로_넉넉하다(limited):
    client = limited.test_client()
    _signup(client, "draft@example.com")
    for _ in range(40):
        client.post("/api/support-chat", json={"question": "안녕"})            # AI 바구니는 다 찼습니다
    codes = [client.post("/documents/draft/preview", json={"draft": {}}).status_code for _ in range(100)]
    assert 429 not in codes


def test_429_는_Retry_After_를_준다(limited):
    client = limited.test_client()
    last = None
    for _ in range(45):
        last = client.post("/api/support-chat", json={"question": "안녕"})
    assert last.status_code == 429 and last.headers["Retry-After"] == "30"


# ── Origin ───────────────────────────────────────────────────────────────────────────
def test_깨진_Origin_값도_500_이_아니라_403(app):
    client = app.test_client()
    for origin in ("http://[::1", "http://", "://x", "http://exa mple.com:99999999"):
        assert client.post("/auth/logout", headers={"Origin": origin}).status_code == 403, origin


def test_추가_허용_호스트는_ALLOWED_ORIGINS_로(app, monkeypatch):
    client = app.test_client()
    assert client.post("/auth/logout", headers={"Origin": "https://alias.example.com"}).status_code == 403
    monkeypatch.setenv("ALLOWED_ORIGINS", "alias.example.com, other.example.com")
    assert client.post("/auth/logout", headers={"Origin": "https://alias.example.com"}).status_code != 403
    assert client.post("/auth/logout", headers={"Origin": "https://evil.example.com"}).status_code == 403


def test_Origin_거절_메시지는_무엇을_하라고_말한다(app):
    body = app.test_client().post("/auth/logout", headers={"Origin": "https://evil.example"}).get_data(as_text=True)
    assert "ALLOWED_ORIGINS" in body and "주소" in body


def test_잠금과_거절은_로그에_남는다(limited, caplog):
    import logging

    client = limited.test_client()
    with caplog.at_level(logging.WARNING):
        client.post("/auth/logout", headers={"Origin": "https://evil.example"})
        for _ in range(11):
            client.post("/auth/login", data={"email": "someone@example.com", "password": "wrong"})
    text = caplog.text
    assert "출처 거절" in text and "로그인 잠금" in text
    assert "someone@example.com" not in text and "som***" in text          # 이메일은 앞 3자만


# ── 프록시 ───────────────────────────────────────────────────────────────────────────
def test_프록시_단계_수를_환경_변수로_정한다(monkeypatch):
    monkeypatch.setenv("TRUST_PROXY", "1")
    monkeypatch.setenv("TRUST_PROXY_HOPS", "2")
    flask_app = create_app(TestConfig)
    client = flask_app.test_client()
    response = client.get("/health", headers={"X-Forwarded-For": "9.9.9.9, 10.0.0.1, 10.0.0.2"})
    assert response.status_code == 200
    assert flask_app.wsgi_app.__class__.__name__ == "ProxyFix" and flask_app.wsgi_app.x_for == 2


def test_잘못된_프록시_단계_값은_1로_본다(monkeypatch):
    monkeypatch.setenv("TRUST_PROXY", "1")
    monkeypatch.setenv("TRUST_PROXY_HOPS", "abc")
    assert create_app(TestConfig).wsgi_app.x_for == 1


# ── DB 연결 · 헬스체크 · 기동 ─────────────────────────────────────────────────────────
def test_끊긴_연결에서_복구하는_엔진_설정이_있다(app):
    options = app.config["SQLALCHEMY_ENGINE_OPTIONS"]
    assert options["pool_pre_ping"] is True and options["pool_recycle"] <= 300


def test_헬스체크는_DB_를_본다(app, monkeypatch):
    client = app.test_client()
    assert client.get("/health").get_json() == {"status": "ok"}

    from sqlalchemy.orm import scoped_session

    def boom(self, *args, **kwargs):
        raise RuntimeError("connection lost")

    monkeypatch.setattr(scoped_session, "execute", boom)
    response = client.get("/health")
    assert response.status_code == 503 and response.get_json()["status"] == "db_down"


def test_필요한_열이_다_있으면_빠진_열_목록은_비어_있다(app):
    from app import _missing_schema

    assert _missing_schema() == []


def test_준비_작업이_진짜_실패하면_기동을_멈춘다(monkeypatch):
    import app as app_module
    from sqlalchemy.exc import OperationalError

    def boom(_database):
        raise OperationalError("ALTER TABLE", {}, Exception("permission denied"))

    monkeypatch.setattr(app_module, "migrate_buyer_columns", boom)
    monkeypatch.setattr(app_module, "_missing_schema", lambda: ["buyers.user_id"])
    with pytest.raises(RuntimeError, match="buyers.user_id"):
        create_app(TestConfig)


def test_다른_일꾼이_먼저_끝낸_겹침은_넘어간다(monkeypatch):
    import app as app_module
    from sqlalchemy.exc import IntegrityError

    def clash(_database):
        raise IntegrityError("INSERT", {}, Exception("already exists"))

    monkeypatch.setattr(app_module, "migrate_buyer_columns", clash)
    assert create_app(TestConfig) is not None            # 열이 다 있으니 겹침일 뿐입니다


def test_JSON_요청이면_api_가_아닌_경로의_500_도_JSON(app, monkeypatch):
    from app.services import document_start_service

    app.config["PROPAGATE_EXCEPTIONS"] = False
    app.config["TESTING"] = False
    client = app.test_client()
    _signup(client, "j@example.com")
    monkeypatch.setattr(document_start_service, "create", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    response = client.post("/documents/start", json={"project_name": "p"})
    assert response.status_code == 500 and response.get_json()["error_code"] == "SERVER_ERROR"


# ── 견적번호 경합 ────────────────────────────────────────────────────────────────────
def test_견적번호가_겹치면_번호를_다시_받아_저장한다(app, create_shipment, monkeypatch):
    first = create_shipment()
    from app.repositories import shipment_repository

    real = shipment_repository.next_shipment_id
    calls = {"n": 0}

    def clash_once(year):
        calls["n"] += 1
        return first.shipment_id if calls["n"] == 1 else real(year)

    monkeypatch.setattr(shipment_repository, "next_shipment_id", clash_once)
    second = create_shipment()
    assert second.shipment_id != first.shipment_id and calls["n"] >= 2
    assert Shipment.query.count() == 2


# ── 마스터 대시보드 ──────────────────────────────────────────────────────────────────
@pytest.fixture()
def master(app):
    client = app.test_client()
    user = User.query.filter_by(email=app.config["MASTER_EMAIL"]).one()
    with client.session_transaction() as session:
        session["user_id"] = user.id
    return client


def _with_status(create_shipment, status, **overrides):
    shipment = create_shipment(**overrides)
    shipment.status = status
    db.session.commit()
    return shipment


def test_KPI_카드는_묶음_전체를_거른다(master, create_shipment):
    moving = [_with_status(create_shipment, "departed"), _with_status(create_shipment, "in_transit")]
    _with_status(create_shipment, "quoted")
    html = master.get("/dashboard").get_data(as_text=True)
    assert "status=group%3Amoving" in html or "status=group:moving" in html
    listed = master.get("/api/dashboard?status=group:moving").get_json()["data"]["shipments"]
    assert {row["shipment_id"] for row in listed} == {s.shipment_id for s in moving}


def test_카드_숫자와_눌렀을_때_목록_수가_같다(master, create_shipment):
    for status in ("departed", "in_transit", "in_transit", "delivered", "closed", "arrived"):
        _with_status(create_shipment, status)
    data = master.get("/api/dashboard").get_json()["data"]
    for card in data["cards"]:
        key = card["key"]
        rows = master.get(f"/api/dashboard?status=group:{key}").get_json()["data"]["shipments"]
        assert len(rows) == card["count"], key


def test_알_수_없는_묶음은_거르지_않는다(master, create_shipment):
    _with_status(create_shipment, "quoted")
    rows = master.get("/api/dashboard?status=group:nope").get_json()["data"]["shipments"]
    assert len(rows) == 1


def test_상태_거르기_상자에_묶음이_있고_고른_값이_유지된다(master, create_shipment):
    _with_status(create_shipment, "departed")
    html = master.get("/dashboard?status=group:moving").get_data(as_text=True)
    assert 'value="group:moving" selected' in html


def test_사용자_수는_마스터를_뺀_가입_회원이다(master, app):
    _signup(app.test_client(), "member1@example.com")
    data = master.get("/api/dashboard").get_json()["data"]
    assert data["stats"]["users"] == 1


def test_이번_달_수는_한국_시각_달_기준이다(app, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from app import timeutil
    from app.services import dashboard_service

    class Fixed(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 1, 0, 30, tzinfo=timezone(timedelta(hours=9))).astimezone(tz)

    monkeypatch.setattr(timeutil, "datetime", Fixed)
    start = dashboard_service._month_start_utc()
    assert start == datetime(2026, 10, 31, 15, 0)          # 11월 1일 00:00 KST = 10월 31일 15:00 UTC


def test_CSV_는_저장하지_않고_charset_이_한_번이다(master, create_shipment):
    create_shipment()
    response = master.get("/dashboard/admin/export.csv")
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Content-Type"].count("charset") == 1


def test_CSV_셀은_탭과_줄바꿈_수식도_막는다():
    from app.services.dashboard_service import _cell

    for value in ("=1+1", "+1", "-1", "@x", "\t=1", "\r=1", "\n=1"):
        assert _cell(value).startswith("'"), value
    assert _cell("정상 값") == "정상 값" and _cell(None) == ""


def test_목록_질의_수는_건수에_비례하지_않는다(master, create_shipment, app):
    for _ in range(12):
        create_shipment()
    counter = {"n": 0}

    @event.listens_for(db.engine, "before_cursor_execute")
    def count(*args):
        counter["n"] += 1

    try:
        counter["n"] = 0
        master.get("/dashboard")
        small = counter["n"]
        for _ in range(12):
            create_shipment()
        counter["n"] = 0
        master.get("/dashboard")
        big = counter["n"]
    finally:
        event.remove(db.engine, "before_cursor_execute", count)
    assert big <= small + 4, (small, big)          # 건수가 두 배가 되어도 질의 수는 거의 같습니다
    assert big < 40
