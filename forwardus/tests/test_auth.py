"""로그인 · 회원가입."""

from __future__ import annotations

import pytest

from app import create_app
from app.extensions import db
from app.models import User
from config import TestConfig


@pytest.fixture()
def client():
    app = create_app(TestConfig)
    with app.app_context():
        yield app.test_client()
        db.session.remove()
        db.drop_all()


def _signup(client, **overrides):
    data = {"email": "kim@example.com", "name": "김무역",
            "password": "secret123", "password_confirm": "secret123"}
    data.update(overrides)
    return client.post("/auth/signup", data=data)


def _nav(client, path="/"):
    import re

    html = client.get(path).get_data(as_text=True)
    return re.search(r'<nav class="main_nav".*?</nav>', html, re.S).group(0)


def test_nav_shows_login_and_signup_without_dashboard(client):
    nav = _nav(client)
    assert "/auth/login" in nav and "/auth/signup" in nav
    # Dashboard는 위쪽 메뉴에서 빠지고 이름 메뉴로 옮겨졌습니다.
    assert "/dashboard" not in nav and "data-user-menu" not in nav


def test_user_menu_has_my_dashboard(client):
    _signup(client)
    nav = _nav(client)
    assert "김무역님" in nav and "data-user-menu-toggle" in nav
    panel = nav.split("data-user-menu-panel", 1)[1]
    assert 'href="/dashboard"' in panel and "내 Dashboard" in panel
    assert "/auth/logout" in panel
    # 이름 메뉴 밖에는 Dashboard 링크가 없습니다.
    assert nav.count('href="/dashboard"') == 1


def test_dashboard_requires_login(client):
    response = client.get("/dashboard")
    assert response.status_code == 302
    assert response.headers["Location"] == "/auth/login?next=/dashboard"
    _signup(client)
    assert client.get("/dashboard").status_code == 200


def test_signup_logs_in_and_hashes_password(client):
    response = _signup(client)
    assert response.status_code == 302
    user = User.query.filter_by(email="kim@example.com").one()
    assert user.password_hash != "secret123"
    html = client.get("/dashboard").get_data(as_text=True)
    assert "김무역님" in html and "로그아웃" in html and "<h1>내 Dashboard</h1>" in html


@pytest.mark.parametrize("overrides", [
    {"email": "not-an-email"},
    {"password": "short", "password_confirm": "short"},
    {"password_confirm": "different1"},
])
def test_signup_rejects_bad_input(client, overrides):
    assert _signup(client, **overrides).status_code == 400
    assert User.query.filter_by(is_master=False).count() == 0


def test_signup_rejects_duplicate_email(client):
    _signup(client)
    client.post("/auth/logout")
    assert _signup(client, email="KIM@example.com").status_code == 400


def test_login_logout(client):
    _signup(client)
    client.post("/auth/logout")
    assert client.post("/auth/login", data={"email": "kim@example.com",
                                            "password": "wrong-pass"}).status_code == 401
    response = client.post("/auth/login", data={"email": "kim@example.com",
                                                "password": "secret123", "next": "/shipments"})
    assert response.status_code == 302 and response.headers["Location"] == "/shipments"
    client.post("/auth/logout")
    assert "/auth/logout" not in client.get("/").get_data(as_text=True)
    assert client.get("/dashboard").status_code == 302


@pytest.mark.parametrize("target", ["https://evil.example", "//evil.example", "/\\evil.example"])
def test_login_ignores_external_next(client, target):
    _signup(client)
    client.post("/auth/logout")
    response = client.post("/auth/login", data={"email": "kim@example.com",
                                                "password": "secret123", "next": target})
    assert response.headers["Location"] == "/dashboard"
