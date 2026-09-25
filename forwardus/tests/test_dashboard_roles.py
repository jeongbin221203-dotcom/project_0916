"""Dashboard 권한 분기 · API 데이터 분리 · 전역 사이드바 · HS 창 스크롤.

마스터(role master)  전체 통합 Dashboard와 관리자 기능(상태 강제 변경 · 엑셀 내려받기)
일반 회원(role user) 내 Dashboard. 남의 Shipment는 화면에도 API에도 나오지 않습니다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.extensions import db
from app.models import Shipment, TradeDocument, User


def _member(app, email: str):
    browser = app.test_client()
    response = browser.post("/auth/signup", data={
        "email": email, "password": "secret123", "password_confirm": "secret123"})
    assert response.status_code == 302
    return browser


def _owned_by(create_shipment, email: str, **fields) -> Shipment:
    shipment = create_shipment()
    shipment.user_id = User.query.filter_by(email=email).one().id
    for key, value in fields.items():
        setattr(shipment, key, value)
    db.session.commit()
    return shipment


def _table(html: str) -> str:
    """Dashboard의 Shipments 표만. (사이드바의 최근 Shipment·검색칸에 적힌 값과 섞이지 않게)"""

    start = html.index("dash_table_head")
    return html[start:html.index("dash_analytics", start)]


def _active_rail(html: str) -> str:
    import re

    found = re.findall(r'<a class="rail_item active"[^>]*>', html, re.S)
    return found[0] if found else ""


@pytest.fixture()
def two_members(app, create_shipment):
    alice = _member(app, "alice@example.com")
    _member(app, "bob@example.com")
    mine = _owned_by(create_shipment, "alice@example.com", status="in_transit")
    theirs = _owned_by(create_shipment, "bob@example.com", project_name="=HYPERLINK(1)")
    return alice, mine, theirs


# --- 권한 ---------------------------------------------------------------------------

def test_권한_이름은_is_master에서_읽는다(app):
    master = User.query.filter_by(email=app.config["MASTER_EMAIL"]).one()
    member = User(email="m@example.com", name="", password_hash="x")
    assert master.role == "master" and master.is_admin
    assert member.role == "user" and not member.is_admin


# --- 화면 ---------------------------------------------------------------------------

def test_마스터는_전체_통합_Dashboard를_본다(client, two_members):
    _, mine, theirs = two_members
    html = client.get("/dashboard").get_data(as_text=True)

    assert "Master Integrated Dashboard" in html
    for label in ("전체 활성 화물", "운송 중", "통관 진행", "도착 완료", "전체 사용자",
                  "이번 달 견적", "이번 달 서류"):
        assert label in html, label
    assert mine.shipment_id in html and theirs.shipment_id in html
    assert "alice@example.com" in html and "bob@example.com" in html
    # 관리자 기능: 검색·필터, 상태 강제 변경, 엑셀 내려받기
    assert 'name="q"' in html and 'name="owner"' in html and 'name="status"' in html
    assert "/dashboard/admin/export.csv" in html
    assert f"/dashboard/admin/shipments/{mine.shipment_id}/status" in html


def test_마스터는_작성자로_거른다(client, two_members):
    _, mine, theirs = two_members
    table = _table(client.get("/dashboard?owner=bob@").get_data(as_text=True))
    assert theirs.shipment_id in table and mine.shipment_id not in table


def test_회원은_내_Dashboard만_본다(two_members):
    alice, mine, theirs = two_members
    html = alice.get("/dashboard").get_data(as_text=True)

    assert "Personal My Dashboard" in html
    for label in ("선적 대기", "운송 중", "통관 진행", "도착 완료",
                  "최근 작성한 서류", "최근 일정 · B/L 추적"):
        assert label in html, label
    assert mine.shipment_id in html and theirs.shipment_id not in html
    # 관리자 기능과 남의 이메일은 보이지 않습니다.
    assert "export.csv" not in html and "/dashboard/admin/" not in html
    assert "bob@example.com" not in html and 'name="owner"' not in html


def test_회원_Dashboard에_내_서류가_다운로드_링크와_함께_나온다(app, two_members):
    alice, mine, theirs = two_members
    db.session.add(TradeDocument(shipment_pk=mine.id, doc_type="commercial_invoice", data={}))
    db.session.add(TradeDocument(shipment_pk=theirs.id, doc_type="packing_list", data={}))
    db.session.commit()

    html = alice.get("/dashboard").get_data(as_text=True)
    assert f"/documents/{mine.shipment_id}/commercial_invoice?print=1" in html
    assert f"/documents/{theirs.shipment_id}/" not in html


def test_회원은_관리자_화면_기능에서_403(two_members):
    alice, mine, theirs = two_members
    assert alice.get("/dashboard/admin/export.csv").status_code == 403
    response = alice.post(f"/dashboard/admin/shipments/{theirs.shipment_id}/status",
                          data={"status": "cancelled"})
    assert response.status_code == 403
    assert Shipment.query.get(theirs.id).status != "cancelled"


def test_마스터는_상태를_바로_바꾼다(client, two_members):
    _, mine, _ = two_members
    response = client.post(f"/dashboard/admin/shipments/{mine.shipment_id}/status",
                           data={"status": "delivered", "back": "/dashboard?status=in_transit"})
    assert response.status_code == 302
    assert response.headers["Location"] == "/dashboard?status=in_transit"
    assert Shipment.query.get(mine.id).status == "delivered"
    # 되돌아갈 주소는 Dashboard 안으로만 받습니다.
    response = client.post(f"/dashboard/admin/shipments/{mine.shipment_id}/status",
                           data={"status": "closed", "back": "https://evil.example"})
    assert response.headers["Location"] == "/dashboard"


def test_마스터는_거른_목록을_엑셀로_받는다(client, two_members):
    _, mine, theirs = two_members
    response = client.get("/dashboard/admin/export.csv")
    body = response.data.decode("utf-8")

    assert response.status_code == 200 and "attachment" in response.headers["Content-Disposition"]
    assert body.startswith("﻿")                       # 엑셀에서 한글이 깨지지 않게
    assert mine.shipment_id in body and theirs.shipment_id in body
    assert "'=HYPERLINK(1)" in body                        # 수식으로 읽히지 않게
    only_bob = client.get("/dashboard/admin/export.csv?owner=bob@").data.decode("utf-8")
    assert theirs.shipment_id in only_bob and mine.shipment_id not in only_bob


# --- API ----------------------------------------------------------------------------

def test_API는_회원에게_자기_것만_준다(two_members):
    alice, mine, theirs = two_members
    for path in ("/api/shipments", "/api/dashboard"):
        body = alice.get(path).get_json()
        rows = body["data"] if path == "/api/shipments" else body["data"]["shipments"]
        ids = {row["shipment_id"] for row in rows}
        assert ids == {mine.shipment_id}, path
        assert all("owner" not in row for row in rows), path
    data = alice.get("/api/dashboard").get_json()["data"]
    assert data["role"] == "user" and data["scope"] == "mine" and "stats" not in data


def test_API는_마스터에게_전체를_준다(client, two_members):
    _, mine, theirs = two_members
    data = client.get("/api/dashboard").get_json()["data"]
    ids = {row["shipment_id"] for row in data["shipments"]}
    assert {mine.shipment_id, theirs.shipment_id} <= ids
    assert data["role"] == "master" and data["scope"] == "all"
    assert data["stats"]["users"] >= 3
    assert any(row["owner"] == "bob@example.com" for row in data["shipments"])


def test_관리자_API는_회원에게_403_로그인_전에는_401(client, anon_client, two_members):
    alice, mine, theirs = two_members
    assert alice.get("/api/admin/shipments").status_code == 403
    response = alice.post(f"/api/admin/shipments/{theirs.shipment_id}/status", json={"status": "closed"})
    assert response.status_code == 403 and response.get_json()["error_code"] == "FORBIDDEN"
    assert anon_client.get("/api/admin/shipments").status_code == 401
    assert anon_client.get("/api/shipments").status_code == 401

    assert client.get("/api/admin/shipments").status_code == 200
    response = client.post(f"/api/admin/shipments/{theirs.shipment_id}/status", json={"status": "closed"})
    assert response.status_code == 200 and response.get_json()["data"]["status"] == "closed"
    bad = client.post(f"/api/admin/shipments/{theirs.shipment_id}/status", json={"status": "flying"})
    assert bad.status_code == 400


# --- 전역 사이드바 -----------------------------------------------------------------------

@pytest.mark.parametrize("path, active", [
    ("/", "홈"), ("/planning/new", "운송 예상 견적"), ("/documents/new", "수출서류작성"),
    ("/dashboard", "Dashboard"), ("/lookup/", "관세청 조회"),
    ("/tracking/container", "컨테이너 조회")])
def test_사이드바는_어느_화면에나_같은_자리에_있다(client, path, active):
    html = client.get(path).get_data(as_text=True)

    assert html.count('id="home_rail"') == 1, path
    # 사이드바는 내용 칸(.app_stage) 바깥, 같은 틀(.app_shell) 안에 있습니다.
    assert html.index('class="app_shell"') < html.index('id="home_rail"') < html.index('class="app_stage"')
    assert "js/sidebar.js" in html and "css/shell.css" in html
    # 접힘/펼침은 그리기 전에 저장된 값으로 붙입니다. 화면을 옮겨도 그대로입니다.
    assert html.index("isSidebarExpanded") < html.index("<body")
    # 이 브라우저는 마스터입니다. Dashboard는 마스터에게만 보입니다. (아래 테스트에서 확인)
    for name in ("홈", "수출서류작성", "운송 예상 견적", "Dashboard", "컨테이너 조회",
                 "관세청 조회", "환율"):
        assert f'data-tip="{name}"' in html, (path, name)
    current = _active_rail(html)
    if active:
        assert f'data-tip="{active}"' in current and 'aria-current="page"' in current, path
    else:
        assert not current, path


def test_Dashboard는_마스터에게만_보인다(app, client, two_members):
    """이용자 화면에서는 감춥니다. 대신 홈 대화로 일을 끝냅니다.

    감추는 것은 길(사이드바·이름 메뉴)뿐이고, 주소는 그대로 살아 있습니다.
    (내 건만 보이는 것은 위의 권한 테스트가 지킵니다)
    """

    member, _, _ = two_members
    html = member.get("/").get_data(as_text=True)
    assert 'data-tip="Dashboard"' not in html
    assert 'href="/dashboard"' not in html
    assert member.get("/dashboard").status_code == 200

    master_html = client.get("/").get_data(as_text=True)
    assert 'data-tip="Dashboard"' in master_html
    assert "전체 Dashboard" in master_html


def test_환율_창은_어느_화면에서나_열린다(client):
    for path in ("/planning/new", "/dashboard"):
        html = client.get(path).get_data(as_text=True)
        assert "data-fx-modal" in html and "js/fx_center.js" in html and "FORWARDUS_FX" in html, path


# --- HS CODE 간편 검색 창 --------------------------------------------------------------

def test_HS_창은_화면_85퍼센트까지이고_결과_목록만_스크롤된다():
    css = (Path(__file__).parent.parent / "app/static/css/base.css").read_text(encoding="utf-8")
    box = css[css.index(".hs_modal_box {"):]
    assert "max-height: calc(85vh / var(--ui_scale, 1))" in box.split("}", 1)[0]
    body = css[css.index(".hs_modal_body {"):].split("}", 1)[0]
    assert "overflow: hidden" in body
    pinned = css[css.index(".hs_modal_body > .hs_input_row"):].split("}", 1)[0]
    assert "position: sticky" in pinned
    results = css[css.index(".hs_modal_body .ac_list {"):].split("}", 1)[0]
    assert "overflow-y: auto" in results and "scroll-behavior: smooth" in results
