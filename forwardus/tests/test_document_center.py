"""서류 센터의 "제출 전 점검" 칸.

왜 이 칸이 있나
  관세사에게 넘기기 전에 봐야 하는 것이 세 군데로 흩어져 있었습니다.
    적은 내용이 다 찼는지  →  [관세사 전달용 신고자료] 화면
    증빙을 올렸는지        →  [수출요건 확인] 화면
    서류끼리 값이 맞는지    →  서류 센터
  셋을 다 봐야 "보내도 되는가"를 알 수 있는데 화면을 두 번 떠났다 와야 했고,
  그 사이에 하나를 빠뜨리면 통관에서 되돌아옵니다.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.extensions import db


def _panel(html: str) -> str:
    """점검 칸만 잘라 옵니다. (다른 칸의 글자와 섞이지 않게)"""

    start = html.index('id="validation"')
    return html[start:html.index("</section>", start)]


@pytest.fixture()
def shipment(create_shipment):
    return create_shipment()


def test_셋을_한_칸에_모아_보여_준다(client, shipment):
    panel = _panel(client.get(f"/documents/{shipment.shipment_id}").get_data(as_text=True))

    assert "제출 전 점검" in panel
    assert "올린 증빙 서류" in panel          # ③은 문제가 없어도 늘 보여 줍니다
    # 관세사 전달용 화면으로 가는 길도 남겨 둡니다. 여기서 다 보여 주지는 않습니다.
    assert f"/documents/{shipment.shipment_id}/customs-filing" in panel


def test_빈_칸이_있으면_채워야_할_것으로_모은다(client, shipment):
    """적은 내용의 빈 칸과 서류의 빈 필수칸을 한 묶음으로 셉니다.

    사람에게는 둘 다 "아직 안 적은 것"입니다. 나눠 놓으면 두 번 세게 됩니다.
    """

    for cargo in shipment.cargos:
        cargo.net_weight_kg = None
    db.session.commit()

    panel = _panel(client.get(f"/documents/{shipment.shipment_id}").get_data(as_text=True))
    assert "채워야 할 것" in panel


def test_아무_문제가_없으면_한_줄로_끝낸다(client, shipment, monkeypatch):
    """고칠 것이 없는데 표를 펼쳐 두면, 매번 훑고도 아무것도 안 하게 됩니다."""

    from app.routes import document as route
    from app.services import customs_filing_service

    real = customs_filing_service.filing_sheet
    monkeypatch.setattr(route.customs_filing_service, "filing_sheet",
                        lambda s: {**real(s), "missing": []})
    monkeypatch.setattr(route.document_service, "check_documents",
                        lambda s: {"status": "passed", "findings": [],
                                   "checked_documents": ["Commercial Invoice"],
                                   "checked_fields": ["Quantity"]})

    panel = _panel(client.get(f"/documents/{shipment.shipment_id}").get_data(as_text=True))
    assert "관세사에게 넘기셔도 됩니다" in panel
    assert "<table" not in panel               # 표는 그리지 않습니다


def test_비어_있음을_기준값과_다름으로_적지_않는다(client, shipment, monkeypatch):
    """"기준값과 다르다"와 "아예 비어 있다"는 고치는 방법이 다릅니다.

    예전에는 kind가 cross가 아니면 전부 "기준값"으로 찍어서, 빈 칸까지
    "기준값과 다름"으로 나왔습니다.
    """

    from app.routes import document as route

    monkeypatch.setattr(route.document_service, "check_documents", lambda s: {
        "status": "warning", "checked_documents": [], "checked_fields": [],
        "findings": [{"status": "warning", "kind": "missing", "field": "net_weight_kg",
                      "field_label": "Net Weight", "document": "packing_list",
                      "document_label": "Packing List", "expected": None, "actual": None,
                      "message": "Packing List에 Net Weight가 비어 있습니다."}]})

    panel = _panel(client.get(f"/documents/{shipment.shipment_id}").get_data(as_text=True))
    # 빈 칸은 ①로 가고, ②(서로 다른 값)에는 들어가지 않습니다.
    assert "채워야 할 것" in panel
    assert "서로 다른 값" not in panel


def test_제대로_적힌_값은_접어_둔다(client, shipment):
    """전부 펼치면 패킹리스트만 20줄입니다. 고칠 한 줄이 그 사이에 묻힙니다."""

    panel = _panel(client.get(f"/documents/{shipment.shipment_id}").get_data(as_text=True))
    assert "check_filled" in panel and "제대로 적힌 값 보기" in panel
    # details는 open 없이 두어야 접힌 채로 뜹니다.
    assert '<details class="check_filled">' in panel


def test_이_칸을_그리느라_관세청을_부르지_않는다(client, shipment):
    """requirements_for()는 HS부호마다 관세청을 때립니다.

    서류 센터는 자주 여는 화면이라, 여기서 부르면 열 때마다 기관을 부릅니다.
    올린 서류 목록은 filing_sheet의 papers로 충분합니다.
    """

    from app.services import requirement_service

    with patch.object(requirement_service, "requirements_for",
                      side_effect=AssertionError("서류 센터가 관세청을 불렀습니다")):
        assert client.get(f"/documents/{shipment.shipment_id}").status_code == 200


def test_업로드_카드는_한_벌만_둔다():
    """같은 카드가 두 화면에 복사돼 있었습니다. 한쪽만 고치면 화면마다 달라집니다."""

    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "app" / "templates" / "document"
    assert (root / "_upload_card.html").exists()
    for name in ("center.html", "requirements.html"):
        text = (root / name).read_text(encoding="utf-8")
        assert 'include "document/_upload_card.html"' in text, name
        # 카드 본문이 남아 있으면 안 됩니다.
        assert "upload_summary" not in text, name
