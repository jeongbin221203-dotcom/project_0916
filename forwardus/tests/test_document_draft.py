"""이름 붙여 저장해 둔 서류 초안 — Shipment 없이 남고, 나중에 승격됩니다.

여기서 지키려는 것.

1. 스케줄을 아직 안 골랐어도, 서류부터 먼저 썼어도 견적명이 저장됩니다.
   (검토 창에서 이름을 적는 순간 Shipment 없이 남아야 합니다)
2. 대시보드 목록에 사람이 지은 이름으로 섭니다.
3. 나중에 Shipment를 만들면 그 초안과 이름이 그대로 넘어갑니다.
4. 남의 초안은 열 수도 고칠 수도 없습니다.
"""

from __future__ import annotations

import re

import pytest

from app.services import document_draft_service as drafts
from app.services import planning_service
from app.validators import ValidationError

from tests.test_document_start import FILLED, ITEMS

DRAFT = {"origin_code": "KRPUS", "destination_code": "MXZLO", "buyer_name": "ABC Beauty Inc.",
         "requested_departure_date": "2026-11-05",
         "items": [{"product_description": "LIPSTICK", "quantity": "100"}]}
DOCUMENTS = [{"kind": "commercial_invoice", "title": "상업송장 (Commercial Invoice)",
              "data": {"consignee": "ABC Beauty Inc.", "buyer": "SAME AS CONSIGNEE",
                       "items": [{"description": "LIPSTICK", "quantity": "100"}]}}]


def _row(draft_id):
    """SQLAlchemy 2.0 방식으로 한 줄 읽기. Query.get()은 legacy입니다."""

    from app.extensions import db
    from app.models import DocumentDraft

    return db.session.get(DocumentDraft, draft_id)


def _member(app, email="kim@example.com"):
    browser = app.test_client()
    browser.post("/auth/signup", data={"email": email, "password": "secret123",
                                       "password_confirm": "secret123"})
    return browser


def _save(browser, **overrides):
    body = {"quote_title": "2026-10 멕시코 화장품 1차 수출 건",
            "draft": DRAFT, "documents": DOCUMENTS, "source": "chat"}
    body.update(overrides)
    response = browser.post("/documents/draft/save", json=body)
    assert response.status_code == 200, response.get_json()
    return response.get_json()["data"]


# --- 1. Shipment 없이 저장 -----------------------------------------------------------

def test_스케줄을_안_골랐어도_견적명이_저장된다(app):
    """이것이 이 표를 따로 둔 이유입니다.

    TradeDocument는 shipment_pk가 필수라 Shipment 없이는 저장할 수 없고,
    WorkDraft는 회원마다 한 벌이라 여러 건을 목록으로 둘 수 없습니다.
    """

    saved = _save(_member(app))

    assert saved["quote_title"] == "2026-10 멕시코 화장품 1차 수출 건"
    record = _row(saved["id"])
    assert record.shipment_pk is None          # 확정된 건이 아닙니다.
    assert record.is_promoted is False
    assert record.documents[0]["kind"] == "commercial_invoice"
    # 승격에 쓸 초안도 같이 남습니다.
    assert record.draft["destination_code"] == "MXZLO"


def test_이름을_안_적으면_지어_넣는다(app):
    """이름 없는 줄이 목록에 쌓이면 무엇이 무엇인지 알 수 없습니다."""

    saved = _save(_member(app), quote_title="")

    # 서류 작성 화면·챗봇과 같은 규칙입니다. (processors/document_defaults)
    assert re.fullmatch(r"멕시코_LIPSTICK_20261105", saved["quote_title"]), saved["quote_title"]


def test_같은_초안을_다시_저장하면_줄이_늘지_않는다(app):
    from app.models import DocumentDraft

    browser = _member(app)
    first = _save(browser)
    second = _save(browser, id=first["id"], quote_title="이름을 고쳤습니다")

    assert second["id"] == first["id"]
    assert DocumentDraft.query.count() == 1
    assert _row(first["id"]).quote_title == "이름을 고쳤습니다"


def test_이름만_고칠_수_있다(app):
    """검토 창에서 이름 칸을 벗어날 때 부르는 창구입니다."""

    browser = _member(app)
    saved = _save(browser)

    response = browser.patch(f"/documents/draft/{saved['id']}/title",
                             json={"quote_title": "ABC사 의류 수출 건"})

    assert response.get_json()["data"]["quote_title"] == "ABC사 의류 수출 건"
    # 서류 값은 그대로 남습니다. 이름만 고치러 온 요청입니다.
    assert _row(saved["id"]).documents[0]["kind"] == "commercial_invoice"


def test_빈_이름으로는_고칠_수_없다(app):
    browser = _member(app)
    saved = _save(browser)

    response = browser.patch(f"/documents/draft/{saved['id']}/title", json={"quote_title": "  "})

    assert response.status_code == 400


def test_계좌번호는_저장하지_않는다(app):
    """초안에 계좌가 섞여 들어와도 서버에 남기지 않습니다. (bank_redaction)"""

    saved = _save(_member(app), documents=[{
        "kind": "commercial_invoice", "title": "상업송장",
        "data": {"remarks": "송금 계좌 1002-345-678901 KEB하나은행"}}])

    assert "1002-345-678901" not in _row(saved["id"]).documents[0]["data"]["remarks"]


# --- 2. 대시보드 노출 -----------------------------------------------------------------

def test_대시보드에_사람이_지은_이름으로_선다(app):
    browser = _member(app)
    _save(browser)

    html = browser.get("/dashboard").get_data(as_text=True)

    assert "작성 중인 서류" in html
    assert "2026-10 멕시코 화장품 1차 수출 건" in html
    assert "KRPUS → MXZLO" in html               # 어디로 가는 건인지도 같이 봅니다.


def test_스케줄이_없으면_Route는_비워_둔다(app):
    """항구를 아직 안 골랐으면 지어내지 않습니다."""

    browser = _member(app)
    _save(browser, draft={"buyer_name": "ABC Beauty Inc.", "items": []})

    rows = browser.get("/dashboard").get_data(as_text=True)
    assert "작성 중인 서류" in rows


# --- 3. 승격 ---------------------------------------------------------------------------

@pytest.fixture()
def promoted(app):
    """초안을 만들고 스케줄을 골라 Shipment까지 만든 상태."""

    browser = _member(app)
    saved = _save(browser, quote_title="ABC사 의류 수출 건",
                  draft={**{key: value for key, value in FILLED.items() if key != "items"},
                         "items": ITEMS})
    found = planning_service.search_schedules({**FILLED, "project_name": "조회",
                                               "cargo": {"items": ITEMS}})
    response = browser.post("/documents/start", json={
        **FILLED, "schedule_id": found["items"][0]["schedule_id"], "draft_id": saved["id"]})
    assert response.status_code == 200, response.get_json()
    return browser, saved, response.get_json()["data"]


def test_확정하면_초안의_견적명이_그대로_넘어간다(app, promoted):
    """화면이 이름을 따로 안 보내도 초안에 적어 둔 이름을 씁니다."""

    from app.models import Shipment

    browser, saved, result = promoted

    assert result["project_name"] == "ABC사 의류 수출 건"
    shipment = Shipment.query.filter_by(shipment_id=result["shipment_id"]).one()
    assert shipment.project_name == "ABC사 의류 수출 건"
    record = _row(saved["id"])
    assert record.is_promoted and record.shipment_pk == shipment.id


def test_확정한_건은_작성_중_목록에서_빠진다(app, promoted):
    browser, _saved, result = promoted

    html = browser.get("/dashboard").get_data(as_text=True)

    assert "작성 중인 서류" not in html          # 더는 작성 중이 아닙니다.
    assert "ABC사 의류 수출 건" in html          # Shipments 표에 견적명으로 섭니다.


def test_확정한_초안은_다시_고칠_수_없다(app, promoted):
    """이름의 기준이 Shipment로 넘어갔습니다. 두 곳에서 따로 고치면 어긋납니다."""

    browser, saved, _result = promoted

    response = browser.patch(f"/documents/draft/{saved['id']}/title",
                             json={"quote_title": "되돌리기"})

    assert response.status_code == 400
    assert "확정" in response.get_json()["message"]


def test_화면이_이름을_보내면_그_이름이_이깁니다(app):
    """서류 작성 화면에서 견적명 칸을 따로 적은 경우입니다."""

    browser = _member(app)
    saved = _save(browser, quote_title="초안에 적어 둔 이름",
                  draft={**{key: value for key, value in FILLED.items() if key != "items"},
                         "items": ITEMS})
    found = planning_service.search_schedules({**FILLED, "project_name": "조회",
                                               "cargo": {"items": ITEMS}})
    result = browser.post("/documents/start", json={
        **FILLED, "schedule_id": found["items"][0]["schedule_id"], "draft_id": saved["id"],
        "project_name": "화면에서 다시 적은 이름"}).get_json()["data"]

    assert result["project_name"] == "화면에서 다시 적은 이름"


def test_없는_초안을_가리켜도_서류는_만들어진다(app):
    """초안이 지워졌다고 서류 만들기가 막히면 안 됩니다."""

    browser = _member(app)
    found = planning_service.search_schedules({**FILLED, "project_name": "조회",
                                               "cargo": {"items": ITEMS}})
    response = browser.post("/documents/start", json={
        **FILLED, "schedule_id": found["items"][0]["schedule_id"], "draft_id": 99999})

    assert response.status_code == 200


# --- 4. 남의 초안 -----------------------------------------------------------------------

def test_남의_초안은_열_수도_고칠_수도_없다(app):
    kim = _member(app, "kim@example.com")
    saved = _save(kim)
    lee = _member(app, "lee@example.com")

    # 있는지조차 알리지 않습니다. 없는 것과 똑같이 404입니다.
    assert lee.patch(f"/documents/draft/{saved['id']}/title",
                     json={"quote_title": "가로채기"}).status_code == 404
    assert lee.delete(f"/documents/draft/{saved['id']}").status_code == 404
    assert lee.post("/documents/draft/save",
                    json={"id": saved["id"], "quote_title": "덮어쓰기"}).status_code == 404
    assert _row(saved["id"]).quote_title.startswith("2026-10")
    assert "2026-10 멕시코" not in lee.get("/dashboard").get_data(as_text=True)


def test_로그인_전에는_저장할_수_없다(app, anon_client):
    response = anon_client.post("/documents/draft/save", json={"quote_title": "x"})
    assert response.status_code in (302, 401)


def test_지울_수_있다(app):
    from app.models import DocumentDraft

    browser = _member(app)
    saved = _save(browser)

    assert browser.delete(f"/documents/draft/{saved['id']}").status_code == 200
    assert DocumentDraft.query.count() == 0


# --- 5. 쌓이지 않게 ---------------------------------------------------------------------

def test_초안이_한도를_넘으면_오래된_것부터_지운다(app, monkeypatch):
    from app.models import DocumentDraft

    monkeypatch.setattr(drafts, "MAX_DRAFTS_PER_USER", 3)
    browser = _member(app)
    for number in range(5):
        _save(browser, quote_title=f"{number}번 건")

    titles = [row.quote_title for row in DocumentDraft.query.all()]
    assert len(titles) == 3
    assert "0번 건" not in titles and "4번 건" in titles


def test_초안에_넣을_수_있는_서류_수는_제한된다(app):
    many = [{"kind": f"kind_{n}", "title": f"{n}", "data": {}} for n in range(20)]
    saved = _save(_member(app), documents=many)

    assert len(_row(saved["id"]).documents) == drafts.MAX_DOCUMENTS


def test_서비스는_로그인하지_않은_사람을_거절한다(app):
    with pytest.raises(Exception):
        drafts.save(None, {"quote_title": "x"})
    with pytest.raises((ValidationError, Exception)):
        drafts.get(None, 1)
