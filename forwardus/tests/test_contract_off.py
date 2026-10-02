"""계약서 조항 점검을 꺼 두었을 때 — **화면에 흔적이 없어야 합니다.**

왜 끄나
  2026-09-27 사용자 결정으로 화면에서 내렸습니다. 코드는 그대로 둡니다.
  config.py 의 CONTRACT_CLAUSES_ON 한 줄(또는 .env 의 CONTRACT_CLAUSES_ON=1)로
  되살립니다.

여기서 보는 것
  "안 보이게" 가 아니라 **"없던 것처럼"** 인지를 봅니다. 둘은 다릅니다.
    안 보이게   CSS 로 가립니다 -> 글자는 그대로 있고 주소도 살아 있습니다
    없던 것처럼  글자도 주소도 없습니다
  단추만 감추고 /contract/* 를 열어 두면 주소를 아는 사람은 그대로 씁니다.
  그래서 길이 막혔는지까지 같이 봅니다.

그리고 되살아나는지도 봅니다. 끄기만 하고 켜지는지를 안 보면, 되살리는 날
무엇이 깨졌는지 알 수 없습니다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app import create_app
from app.extensions import db
from config import TestConfig

# 화면 어디에도 남으면 안 되는 자국들.
TRACES = [
    "계약서 조항",
    "data-contract-open",
    "data-contract-modal",
    "data-contract-panel",
    "data-contract-card",
    "FORWARDUS_CONTRACT",
    "contract_clauses.js",
    "contract_modal.js",
    "contract.css",
    "/contract/",
]


class OffConfig(TestConfig):
    CONTRACT_CLAUSES_ON = False


@pytest.fixture()
def off_app():
    flask_app = create_app(OffConfig)
    with flask_app.app_context():
        yield flask_app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def off_client(off_app):
    from app.models import User

    test_client = off_app.test_client()
    master = User.query.filter_by(email=off_app.config["MASTER_EMAIL"]).one()
    with test_client.session_transaction() as session:
        session["user_id"] = master.id
    return test_client


def _traces(html: str) -> list[str]:
    return [mark for mark in TRACES if mark in html]


def test_무역_상담_화면에_자국이_없다(off_client):
    html = off_client.get("/").get_data(as_text=True)
    assert html            # 화면이 뜨긴 해야 합니다
    assert not _traces(html), _traces(html)


@pytest.fixture()
def off_document(off_app, shipment_payload):
    """꺼 둔 앱 안에서 서류 한 장까지 만듭니다.

    conftest 의 create_shipment 는 켜져 있는 app 픽스처에 붙어 있어
    여기서는 못 씁니다. 같은 일을 off_app 안에서 합니다.
    """

    from app.services import document_service, planning_service

    schedules = planning_service.search_schedules(shipment_payload)
    payload = {**shipment_payload, "schedule_id": schedules["items"][0]["schedule_id"]}
    shipment = planning_service.create_shipment(payload)
    kind = document_service.generate_documents(shipment)[0].doc_type
    return shipment, kind


def test_서류_만들기_화면에_자국이_없다(off_client):
    html = off_client.get("/documents/new").get_data(as_text=True)
    assert not _traces(html), _traces(html)


def test_서류_수정_화면에_자국이_없다(off_client, off_document):
    """점검 칸이 실제로 붙어 있던 화면입니다. 여기가 진짜입니다."""

    shipment, kind = off_document
    response = off_client.get(f"/documents/{shipment.shipment_id}/{kind}")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert not _traces(html), _traces(html)


def test_길이_아예_없다(off_client, off_app):
    """단추만 감추고 길을 열어 두면 주소를 아는 사람은 그대로 씁니다."""

    for path in ("/contract/clauses", "/contract/review", "/contract/export"):
        assert off_client.get(path).status_code == 404, path
    endpoints = {rule.endpoint for rule in off_app.url_map.iter_rules()}
    assert not [name for name in endpoints if name.startswith("contract.")]


def test_다른_화면은_멀쩡하다(off_client):
    """감추다가 옆 것을 같이 부수지 않았는지 봅니다."""

    for path in ("/", "/documents/new", "/health"):
        assert off_client.get(path).status_code == 200, path
    html = off_client.get("/").get_data(as_text=True)
    assert "HS CODE 조회" in html          # 옆에 있던 단추는 그대로
    assert "FORWARDUS_SUPPORT" in html     # 같은 <script> 안에 있던 것도 그대로


def test_켜면_그대로_돌아온다(client):
    """TestConfig 는 켜져 있습니다. 끄기만 하고 켜지는지를 안 보면,
    되살리는 날 무엇이 깨졌는지 알 수 없습니다."""

    html = client.get("/").get_data(as_text=True)
    assert "계약서 조항" in html
    assert "data-contract-open" in html
    assert "FORWARDUS_CONTRACT" in html
    assert client.get("/contract/clauses").status_code == 200


def test_스위치는_한_곳이다():
    """되살리는 사람이 한 줄만 보면 되도록, 이름이 config 에 있어야 합니다."""

    assert hasattr(TestConfig, "CONTRACT_CLAUSES_ON")


def test_내보내는_기본값은_켜짐이다():
    """**코드에 적힌 기본값**이 켜짐이어야 합니다. (2026-10-02)

    왜 따로 보나
      이 파일의 다른 시험은 OffConfig 로 끄고, 켜진 모습은 TestConfig 로 봅니다.
      둘 다 값을 손으로 못 박기 때문에, 정작 사람에게 나가는 기본값을 아무도
      보지 않았습니다. 기본값을 0 으로 되돌려 봤더니 이 파일의 시험 22개가
      **전부 그대로 통과**했습니다. 기능이 조용히 사라져도 모릅니다.
      누가 되돌리거나 병합이 09-27 상태로 끌어가면 여기서 울립니다.

    왜 Config.CONTRACT_CLAUSES_ON 을 보지 않나
      config.py 는 뜰 때 .env 를 읽습니다. 그래서 그 값은 **이 컴퓨터의 .env** 를
      따릅니다. 끄고 싶은 사람은 안내대로 .env 에 CONTRACT_CLAUSES_ON=0 을 넣는데,
      그걸 실패로 적으면 **잘못한 것이 없는 사람에게 빨간불**이 뜹니다.
      오탐이 미탐보다 나쁩니다. 그래서 .env 가 건드리지 못하는 자리 — 코드에 적힌
      기본값 — 만 봅니다.
    """

    import config

    source = Path(config.__file__).read_text(encoding="utf-8")
    assert 'os.getenv("CONTRACT_CLAUSES_ON", "1")' in source, (
        "config.py 의 기본값이 켜짐이 아닙니다. "
        'os.getenv("CONTRACT_CLAUSES_ON", "1") 이어야 합니다. '
        "끄는 것은 코드가 아니라 .env 로 합니다."
    )
