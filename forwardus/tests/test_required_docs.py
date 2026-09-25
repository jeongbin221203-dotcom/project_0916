"""기타 필수 서류 — HS부호와 도착국으로 필요한 서류를 한 목록으로 모읍니다.

예전에는 원산지증명서만 챙기는 자리가 따로 있었습니다. 관세사에게 넘길 때 빠지면
안 되는 것은 그것만이 아니라서, 관세청 요건·우리 규칙·협정·도착국 인증을 한 자리에
모으고 파일을 올려 두게 했습니다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services import required_docs_service


@pytest.fixture()
def 미국행(app, create_shipment):
    """화장품(HS 3306)을 미국으로 보내는 건."""

    shipment = create_shipment()
    shipment.destination_country = "US"
    shipment.destination_name = "로스앤젤레스항"
    for cargo in shipment.cargos:
        cargo.hs_code = "3306100000"
        cargo.product_description = "치약"
    return shipment


def _키없음(monkeypatch):
    """AI 키가 없는 상태. 그래도 목록이 나와야 합니다."""

    monkeypatch.setattr(required_docs_service.ai_client, "available", lambda: False)


def test_AI가_없어도_목록이_나온다(미국행, monkeypatch):
    _키없음(monkeypatch)
    data = required_docs_service.collect(미국행)

    assert data["total"] > 0
    assert data["ai_available"] is False
    for row in data["documents"]:
        assert row["title"] and row["source"] in ("rule", "customs", "fta", "country", "ai")


def test_도착국_인증이_목록에_들어온다(미국행, monkeypatch):
    _키없음(monkeypatch)
    titles = [row["title"] for row in required_docs_service.collect(미국행)["documents"]]
    # 미국은 FCC·FDA가 우리 자료에 있습니다.
    assert any("FCC" in title or "FDA" in title for title in titles)


def test_화장품이면_식약처_요건이_들어온다(미국행, monkeypatch):
    _키없음(monkeypatch)
    rows = required_docs_service.collect(미국행)["documents"]
    assert any(row["source"] == "rule" for row in rows)


def test_AI는_이미_잡힌_것을_다시_내지_않는다(미국행, monkeypatch):
    """AI에게는 "이미 챙기는 것"을 알려 주고, 겹치는 답은 버립니다."""

    보낸것 = {}

    def 가짜(messages, **kwargs):
        보낸것["prompt"] = messages[0]["content"]
        return {"success": True, "source": "api", "data": json.dumps({"documents": [
            # 치약(HS 3306)이라 FDA는 이미 목록에 있습니다. 겹치므로 버려야 합니다.
            # (FCC로 시험하면 안 됩니다 — 화장품에는 안 걸려 목록에 없고, 그러면
            #  겹치는 것이 아니라 새 항목이 되어 이 테스트가 뜻을 잃습니다)
            {"title": "식품·화장품·의료기기 FDA 등록/신고", "agency": "FDA",
             "why": "겹치는 답", "confidence": "high"},
            {"title": "캘리포니아 Prop 65 경고 라벨", "agency": "주정부",
             "why": "캘리포니아 판매 시 필요합니다.", "confidence": "low"},
        ]}, ensure_ascii=False)}

    monkeypatch.setattr(required_docs_service.ai_client, "available", lambda: True)
    monkeypatch.setattr(required_docs_service.ai_client, "chat", 가짜)
    rows = required_docs_service.collect(미국행)["documents"]

    ai_rows = [row for row in rows if row["source"] == "ai"]
    assert [row["title"] for row in ai_rows] == ["캘리포니아 Prop 65 경고 라벨"]
    assert ai_rows[0]["confidence"] == "low"
    # 이미 챙기는 것을 프롬프트에 적어 보냅니다.
    assert "이미 챙기고 있는 것" in 보낸것["prompt"]


def test_AI가_이상한_답을_줘도_목록은_남는다(미국행, monkeypatch):
    monkeypatch.setattr(required_docs_service.ai_client, "available", lambda: True)
    monkeypatch.setattr(required_docs_service.ai_client, "chat",
                        lambda *a, **k: {"success": True, "source": "api", "data": "JSON이 아닙니다"})
    data = required_docs_service.collect(미국행)
    assert data["total"] > 0 and data["ai_used"] is False


def test_AI를_끄고_부를_수_있다(미국행, monkeypatch):
    def 부르면안됨(*args, **kwargs):
        raise AssertionError("use_ai=False인데 AI를 불렀습니다")

    monkeypatch.setattr(required_docs_service.ai_client, "available", lambda: True)
    monkeypatch.setattr(required_docs_service.ai_client, "chat", 부르면안됨)
    assert required_docs_service.collect(미국행, use_ai=False)["ai_used"] is False


def test_창구가_목록을_돌려준다(client, 미국행, monkeypatch):
    _키없음(monkeypatch)
    response = client.get(f"/documents/{미국행.shipment_id}/required-docs?ai=0")
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["documents"] and data["upload_url"] and data["filing_url"]
    assert data["destination"] == "로스앤젤레스항"


def test_올린_파일이_그_서류_줄에_붙는다(app, client, 미국행, monkeypatch):
    import io

    _키없음(monkeypatch)
    rows = required_docs_service.collect(미국행)["documents"]
    key = rows[0]["key"]

    client.post(f"/documents/{미국행.shipment_id}/requirements/upload", data={
        "requirement_key": key,
        "file": (io.BytesIO("치약 위생증명서".encode("utf-8")), "cert.txt"),
    }, content_type="multipart/form-data")

    after = {row["key"]: row for row in required_docs_service.collect(미국행)["documents"]}
    assert after[key]["uploaded"] is True
    assert after[key]["uploads"][0]["filename"] == "cert.txt"
    assert required_docs_service.collect(미국행)["ready"] >= 1


def test_화면_이름이_기타_필수_서류다(client):
    html = client.get("/documents/new").get_data(as_text=True)
    assert "기타 필수 서류" in html
    # 원산지증명서는 그 목록 안의 한 줄로 남습니다.
    assert "원산지증명서·인증서·검역증" in html


def test_올린_서류가_관세사_자료에_함께_들어간다(client, 미국행, monkeypatch):
    """관세사는 이 파일들을 신고할 때 첨부합니다. 목록에서 빠지면 안 됩니다."""

    import io

    from app.services import customs_filing_service

    _키없음(monkeypatch)
    client.post(f"/documents/{미국행.shipment_id}/requirements/upload", data={
        "requirement_key": "origin", "agreement": "한·미 FTA",
        "file": (io.BytesIO("원산지증명서".encode("utf-8")), "co.txt"),
    }, content_type="multipart/form-data")

    sheet = customs_filing_service.filing_sheet(미국행)
    assert [row["filename"] for row in sheet["papers"]] == ["co.txt"]
    assert "한·미 FTA" in customs_filing_service.as_text(sheet)
    assert "co.txt" in customs_filing_service.as_text(sheet)

    html = client.get(f"/documents/{미국행.shipment_id}/customs-filing").get_data(as_text=True)
    assert "함께 보내는 서류" in html and "co.txt" in html


def test_Shipment_화면에서_서류_작성으로_바로_간다(client, 미국행):
    """요약·서류·통관 어디에서나 이 건 값을 들고 서류 작성으로 넘어갈 수 있어야 합니다.

    예전에는 길이 없어서 사이드바로 나갔다가 값을 처음부터 다시 적어야 했습니다.
    """

    link = f"source=shipment:{미국행.shipment_id}"
    for path in (f"/shipments/{미국행.shipment_id}",
                 f"/documents/{미국행.shipment_id}",
                 f"/documents/{미국행.shipment_id}/customs-filing"):
        html = client.get(path, follow_redirects=True).get_data(as_text=True)
        assert "서류 작성" in html and link in html, path

    # 그 주소로 들어가면 화면이 열리고, 화면 코드가 ?source= 를 읽습니다.
    assert client.get(f"/documents/new?{link}").status_code == 200
    form_js = (Path(__file__).parent.parent / "app/static/js/doc_form.js").read_text(encoding="utf-8")
    assert 'URLSearchParams(location.search).get("source")' in form_js


class TestHS부호만으로_미리보기:
    """건을 만들기 전에도 HS부호만 적으면 필요한 서류가 보여야 합니다.

    인증은 몇 주에서 몇 달이 걸립니다. 건을 만들고 선적을 잡은 뒤에 알려 주면
    이미 늦습니다.
    """

    def test_HS부호만으로_목록이_나온다(self, app, monkeypatch):
        _키없음(monkeypatch)
        data = required_docs_service.preview(["3306100000"], "TR", "이스탄불항", ["치약"])
        assert data["total"] > 0
        titles = [row["title"] for row in data["documents"]]
        assert any("화장품" in title for title in titles)        # 우리 규칙표
        assert any("TAREKS" in title or "TSE" in title for title in titles)  # 도착국 인증

    def test_건을_만들기_전에도_협정_원산지증명서를_알려_준다(self, app, monkeypatch):
        """예전에는 미리보기에서 통째로 빠졌습니다. (2026-09-25 고침)

        협정세율은 관세청이 있어야 나오지만, **어떤 협정을 쓸 수 있고 증명서를
        어디서 어떤 서식으로 받는지**는 우리 표에 있습니다. 세율을 모른다고
        서류 안내까지 빼면, 가장 자주 필요한 서류가 목록에서 사라집니다.
        """

        _키없음(monkeypatch)
        data = required_docs_service.preview(["3306100000"], "TR")
        origin = [row for row in data["documents"] if row["source"] == "fta"]
        assert len(origin) == 1
        assert "원산지증명서" in origin[0]["title"]
        assert origin[0]["documents"]            # 함께 갖출 증빙까지 적혀 있어야 합니다

    def test_품목에_안_걸리는_도착국_인증은_빼준다(self, app, monkeypatch):
        """치약(HS 33)에 섬유 라벨·어린이제품·전기설비가 따라 나오면 안 됩니다.

        필요 없는 줄이 섞이면 정작 챙겨야 할 줄을 믿지 않게 됩니다.
        """

        _키없음(monkeypatch)
        titles = " ".join(row["title"] for row
                          in required_docs_service.preview(["3306100000"], "US")["documents"])
        assert "FDA" in titles                   # 화장품에 걸립니다
        for 남 in ("섬유", "어린이", "UL", "FCC"):
            assert 남 not in titles, 남

        # 반대로 휴대전화(HS 85)에는 전기 쪽이 나와야 합니다.
        phone = " ".join(row["title"] for row
                         in required_docs_service.preview(["8517120000"], "DE")["documents"])
        assert "RoHS" in phone or "배터리" in phone

    def test_HS부호를_모르면_거르지_않는다(self, app, monkeypatch):
        """무엇을 보내는지 모르는 채로 거르면 필요한 서류를 감추게 됩니다."""

        _키없음(monkeypatch)
        titles = " ".join(row["title"] for row
                          in required_docs_service.preview([""], "US", products=["뭔가"])["documents"])
        assert "FDA" in titles and "FCC" in titles

    def test_위험물이면_그_서류도_함께_나온다(self, app, monkeypatch):
        _키없음(monkeypatch)
        data = required_docs_service.preview(["8507600000"], "US", products=["리튬배터리"],
                                             dangerous=True)
        titles = " ".join(row["title"] for row in data["documents"])
        assert "위험물" in titles or "MSDS" in titles

    def test_창구가_HS부호로_답한다(self, client):
        response = client.get("/documents/api/required-docs?hs=3306100000&country=TR&ai=0")
        assert response.status_code == 200
        data = response.get_json()["data"]
        assert data["documents"] and data["hs_codes"] == ["3306100000"]

    def test_HS부호도_품명도_없으면_되묻는다(self, client):
        response = client.get("/documents/api/required-docs?ai=0")
        assert response.status_code == 400

    def test_화면이_HS부호를_적을_때_찾아본다(self):
        form = (Path(__file__).parent.parent / "app/static/js/doc_form.js").read_text(encoding="utf-8")
        assert "requiredDocsPreviewUrl" in form
        assert 'event.target.name === "item_hs_code"' in form


def test_채운_칸_숫자를_누르면_빠진_칸으로_간다():
    """숫자만 보여 주면 "하나가 비었다"만 알고 어느 칸인지는 모릅니다.

    17/18에서 그 하나를 찾으려고 화면을 훑게 됩니다. 눌러서 바로 가게 합니다.
    """

    form = (Path(__file__).parent.parent / "app/static/js/doc_form.js").read_text(encoding="utf-8")
    assert "function missingFields" in form and "function showMissing" in form
    # 점수와 같은 기준으로 세야 숫자가 맞습니다. (품목은 첫 줄만)
    assert "품목은 첫 줄만 셉니다" in form
    # 일정만 안 고른 경우도 짚어 줍니다.
    assert 'goToSection("schedule")' in form

    css = (Path(__file__).parent.parent / "app/static/css/home.css").read_text(encoding="utf-8")
    assert ".doc_score { cursor: pointer;" in css
