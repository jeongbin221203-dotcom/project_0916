"""마스터는 모든 Shipment를, 일반 회원은 자기 Shipment만 봅니다."""

from __future__ import annotations

import pytest

from app.models import Shipment, User


def _member(app, email: str):
    """회원가입한 뒤 로그인된 브라우저를 돌려줍니다."""

    browser = app.test_client()
    response = browser.post("/auth/signup", data={
        "email": email, "password": "secret123", "password_confirm": "secret123"})
    assert response.status_code == 302
    return browser


def _owned_by(create_shipment, email: str) -> Shipment:
    shipment = create_shipment()
    shipment.user_id = User.query.filter_by(email=email).one().id
    from app.extensions import db
    db.session.commit()
    return shipment


SHIPMENT_PAGES = ["/shipments/{id}", "/documents/{id}", "/tracking/{id}", "/assistant/{id}"]


def test_master_account_is_created(app):
    master = User.query.filter_by(email="forwardus@gmail.com").one()
    assert master.is_master and master.check_password("1234")


def test_master_can_log_in(app):
    browser = app.test_client()
    response = browser.post("/auth/login", data={"email": "forwardus@gmail.com",
                                                 "password": "1234"})
    assert response.status_code == 302
    html = browser.get("/shipments").get_data(as_text=True)
    assert "마스터" in html and "모든 사용자의 Shipment" in html


def test_new_member_is_not_master(app):
    _member(app, "a@example.com")
    assert User.query.filter_by(email="a@example.com").one().is_master is False


def test_shipment_created_through_api_belongs_to_creator(app, shipment_payload):
    from app.services import planning_service

    browser = _member(app, "a@example.com")
    payload = dict(shipment_payload)
    payload["schedule_id"] = planning_service.search_schedules(payload)["items"][0]["schedule_id"]
    response = browser.post("/planning/api/shipments", json=payload)
    assert response.status_code == 201
    shipment_id = response.get_json()["data"]["shipment_id"]
    owner = User.query.filter_by(email="a@example.com").one()
    assert Shipment.query.filter_by(shipment_id=shipment_id).one().user_id == owner.id


def test_member_sees_only_own_shipments(app, create_shipment):
    alice = _member(app, "alice@example.com")
    bob = _member(app, "bob@example.com")
    mine = _owned_by(create_shipment, "alice@example.com")
    theirs = _owned_by(create_shipment, "bob@example.com")
    legacy = create_shipment()  # 작성자 없음 → 마스터만

    listing = alice.get("/shipments").get_data(as_text=True)
    assert mine.shipment_id in listing
    assert theirs.shipment_id not in listing and legacy.shipment_id not in listing

    dashboard = alice.get("/dashboard").get_data(as_text=True)
    assert mine.shipment_id in dashboard and theirs.shipment_id not in dashboard

    home = alice.get("/").get_data(as_text=True)
    assert theirs.shipment_id not in home

    for page in SHIPMENT_PAGES:
        assert alice.get(page.format(id=mine.shipment_id)).status_code == 200, page
        # 남의 것은 있는지조차 알리지 않습니다.
        assert alice.get(page.format(id=theirs.shipment_id)).status_code == 404, page
        assert alice.get(page.format(id=legacy.shipment_id)).status_code == 404, page
    assert bob.get(f"/shipments/{mine.shipment_id}").status_code == 404


def test_member_cannot_change_others_shipment(app, create_shipment):
    alice = _member(app, "alice@example.com")
    _member(app, "bob@example.com")
    theirs = _owned_by(create_shipment, "bob@example.com")

    assert alice.post(f"/shipments/{theirs.shipment_id}/status",
                      data={"action": "cancel"}).status_code == 404
    assert alice.post(f"/assistant/{theirs.shipment_id}/api/ask",
                      json={"question": "비용?"}).status_code == 404
    assert Shipment.query.filter_by(shipment_id=theirs.shipment_id).one().status == "quoted"


def test_master_sees_everyone(client, app, create_shipment):
    _member(app, "alice@example.com")
    alices = _owned_by(create_shipment, "alice@example.com")
    legacy = create_shipment()

    listing = client.get("/shipments").get_data(as_text=True)
    assert alices.shipment_id in listing and legacy.shipment_id in listing
    assert "alice@example.com" in listing and "(작성자 없음)" in listing
    assert "전체 Dashboard" in client.get("/dashboard").get_data(as_text=True)
    for page in SHIPMENT_PAGES:
        assert client.get(page.format(id=alices.shipment_id)).status_code == 200, page


@pytest.mark.parametrize("path", ["/shipments", "/planning/new", "/documents/new", "/dashboard"])
def test_logged_out_is_sent_to_login(anon_client, path):
    response = anon_client.get(path)
    assert response.status_code == 302
    assert response.headers["Location"].startswith("/auth/login")


def test_logged_out_cannot_open_or_create(anon_client, create_shipment, shipment_payload):
    legacy = create_shipment()
    assert anon_client.get(f"/shipments/{legacy.shipment_id}").status_code == 302
    assert anon_client.post("/planning/api/shipments", json=shipment_payload).status_code == 401
    assert anon_client.post("/documents/start", json={}).status_code == 401
    assert anon_client.post(f"/assistant/{legacy.shipment_id}/api/ask",
                            json={"question": "?"}).status_code == 401
    # 로그인 전 시작 화면에는 최근 Shipment가 보이지 않습니다.
    assert legacy.shipment_id not in anon_client.get("/").get_data(as_text=True)
