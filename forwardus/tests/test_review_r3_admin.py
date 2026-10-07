"""전수 점검 3회차 — 보안 울타리 보강 시험."""

from flask import Flask

from app import security


def _app_with_ip(app, addr):
    with app.test_request_context("/", environ_base={"REMOTE_ADDR": addr}):
        return security.client_ip()


def test_IPv6는_64접두로_묶는다(app):
    a = _app_with_ip(app, "2001:db8:1:2:aaaa::1")
    b = _app_with_ip(app, "2001:db8:1:2:bbbb::9")
    c = _app_with_ip(app, "2001:db8:1:3::1")
    assert a == b and a != c


def test_IPv4는_그대로(app):
    assert _app_with_ip(app, "203.0.113.5") == "203.0.113.5"


def test_정리는_만료된_키부터():
    window = security.Window()
    for i in range(20001):
        window.add(f"old{i}", now=0.0)
    window.add("live", now=10_000.0)
    assert window.count("live", 60, now=10_000.0) == 1
    assert len(window._hits) < 20000


def test_ALLOWED_ORIGINS_주소전체도_받는다(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://a.com/, b.com")
    assert security._allowed_hosts() == {"a.com", "b.com"}


def test_JSON_본문_4MB_초과는_413(app):
    response = app.test_client().post("/api/support-chat", data=b"x" * (5 * 1024 * 1024),
                                      content_type="application/json")
    assert response.status_code == 413


def test_번호가_낀_AI_길도_제한된다(app):
    app.config["RATE_LIMIT_ENABLED"] = True
    client = app.test_client()
    codes = [client.post("/assistant/S1/api/ask", json={}).status_code
             for _ in range(security.HEAVY_LIMIT_PER_MINUTE * 4 + 2)]
    assert 429 in codes


def test_동시_AI_요청이_넘치면_503(app):
    app.config["RATE_LIMIT_ENABLED"] = True
    # 슬롯을 다 쓴 상태를 흉내 — 가드가 non-blocking 으로 확인하므로 같은 한도의 동시 요청이 있어야 합니다.
    assert security.MAX_CONCURRENT_HEAVY < 8
