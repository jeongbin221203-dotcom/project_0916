"""대화로 서류 초안 만들기.

여기서 지키려는 것은 **선박도 스케줄도 없이 서류가 나오는가**입니다.
그리고 안 정해진 칸을 빈칸으로 두지 않고 "미정"이라 적는가입니다.
비어 있는 것과 아직 안 정해진 것은 다릅니다.
"""

from __future__ import annotations

import base64

import pytest

from app.processors import document_form
from app.services import agent_service, draft_document_service as drafts
from app.validators import ValidationError

ITEMS = [{"product_description": "치약", "hs_code": "3305100000",
          "package_type": "carton", "quantity": 500, "length_cm": 40,
          "width_cm": 30, "height_cm": 25, "weight_per_package_kg": 12,
          "net_weight_kg": 4000, "amount": 25000}]

DRAFT = {
    "exporter_name": "Forward Cosmetics Co., Ltd.", "exporter_address": "Seoul, Korea",
    "buyer_name": "ABC Beauty Inc.", "buyer_address": "Los Angeles, CA",
    "origin_code": "KRPUS", "destination_code": "USLAX",
    "incoterms": "FOB", "currency": "USD", "items": ITEMS,
}


# --- 스케줄 없이 서류가 나오는가 ---------------------------------------------------

@pytest.mark.parametrize("kind", sorted(drafts.FORMS))
def test_스케줄이_없어도_서류가_그려진다(app, kind):
    """선박·출항일이 없어도 나와야 합니다. 그게 이 기능의 전부입니다."""

    out = drafts.render(kind, DRAFT)

    assert out["title"]
    assert out["data"]["items"], "품목 줄이 있어야 합니다"
    assert out["columns"]


@pytest.mark.parametrize("kind", sorted(drafts.FORMS))
def test_안_정해진_칸은_미정이라고_적는다(app, kind):
    """비워 두면 "안 적었나" 싶고, 지어내면 거짓말이 됩니다."""

    out = drafts.render(kind, DRAFT)

    for name in out["undecided"]:
        assert out["data"][name].startswith("미정")
    # 서식마다 스케줄에서 오는 칸이 하나는 있습니다.
    assert out["undecided"], kind


def test_아무것도_저장하지_않는다(app):
    """초안은 확정이 아닙니다. DB에 남기면 안 됩니다."""

    from app.models.document import TradeDocument
    from app.models.shipment import Shipment

    before = (Shipment.query.count(), TradeDocument.query.count())
    drafts.render("packing_list_std", DRAFT)
    assert (Shipment.query.count(), TradeDocument.query.count()) == before


def test_품목이_없으면_거절한다(app):
    with pytest.raises(ValidationError):
        drafts.render("packing_list_std", {**DRAFT, "items": []})


def test_없는_서식은_거절한다(app):
    from app.services import ServiceError

    with pytest.raises(ServiceError):
        drafts.render("없는서식", DRAFT)


def test_번호를_지어내지_않는다(app):
    """적지 않은 송장 번호가 서류에 찍히면 나중에 그걸 진짜로 믿습니다."""

    out = drafts.render("packing_list_std", DRAFT)
    assert out["data"]["invoice_no"] == ""

    given = drafts.render("packing_list_std", {**DRAFT, "invoice_no": "INV-2026-11"})
    assert given["data"]["invoice_no"] == "INV-2026-11"


def test_부피와_중량은_우리가_계산한다(app):
    """화면이 보낸 값을 믿지 않습니다. 40x30x25cm 500개면 15 CBM입니다."""

    out = drafts.render("packing_list_std", DRAFT)
    row = out["data"]["items"][0]

    assert "15.000 CBM" in row["measurement"]
    assert "6,000.00 KG" in row["total_weight"]     # 12kg x 500


# --- 그림과 PDF -------------------------------------------------------------------

def test_그림과_PDF가_나온다(app):
    uri = drafts.preview("packing_list_std", DRAFT)
    assert uri.startswith("data:image/png;base64,")
    png = base64.b64decode(uri.split(",", 1)[1])
    assert png[:8] == b"\x89PNG\r\n\x1a\n"

    pdf = drafts.pdf_bytes("packing_list_std", DRAFT)
    assert pdf[:5] == b"%PDF-"


def test_글꼴에_없는_번호는_네모로_찍지_않는다():
    """맑은 고딕에는 동그라미 숫자가 ⑮까지만 있습니다."""

    assert document_form.no(1, "Seller").startswith("①")
    assert document_form.no(15, "x").startswith("⑮")
    assert document_form.no(16, "Signed by") == "(16) Signed by"


# --- 대화 흐름 --------------------------------------------------------------------

def test_패킹리스트만_말하면_그_서식을_잡는다():
    assert agent_service.detect_kind("패킹리스트만 만들어줘") == "packing_list_std"
    assert agent_service.detect_kind("포장명세서 작성해줘") == "packing_list_std"
    assert agent_service.detect_kind("상업송장만 작성해줘") == "commercial_invoice"
    assert agent_service.detect_kind("견적송장 하나 주세요") == "proforma_invoice"
    assert agent_service.detect_kind("안녕하세요") is None


def test_서류를_고르면_그_서식의_칸만_묻는다(app):
    """포장명세서를 달라는데 단가·금액을 물으면 안 됩니다."""

    out = agent_service.turn({"message": "패킹리스트만 만들어줘", "draft": {}})

    assert out["stage"] == "ask"
    assert out["draft"]["kind"] == "packing_list_std"
    asked = {row["field"] for row in out["fields"]}
    assert "exporter_name" in asked and "buyer_name" in asked
    # 상업송장에만 있는 칸은 묻지 않습니다.
    assert "payment_terms" not in asked
    assert "lc_no" not in asked


def test_상업송장은_거래_조건까지_묻는다(app):
    out = agent_service.turn({"message": "상업송장만 작성해줘", "draft": {}})

    asked = {row["field"] for row in out["fields"]}
    assert "incoterms" in asked
    assert "payment_terms" in asked


def test_무엇을_만들지_모르면_고르게_한다(app):
    out = agent_service.turn({"message": "안녕하세요", "draft": {}})

    assert out["stage"] == "pick"
    assert "포장명세서" in out["reply"]


def test_그냥_만들어달라고_하면_있는_것만으로_그린다(app):
    """빈칸은 빈칸으로 두고 일단 보여 줍니다. 다 채울 때까지 못 보면 답답합니다."""

    started = {**DRAFT, "kind": "packing_list_std"}
    out = agent_service.turn({"message": "그냥 만들어줘", "draft": started})

    assert out["stage"] == "made"
    assert out["undecided"], "스케줄에서 오는 칸은 미정으로 남아야 합니다"


def test_품목이_없으면_그리지_않고_되묻는다(app):
    started = {"kind": "packing_list_std", "exporter_name": "A"}
    out = agent_service.turn({"message": "그냥 만들어줘", "draft": started})

    assert out["stage"] == "ask"
    assert "품목" in out["reply"]


def test_빈_말은_지금_것으로_그리라는_뜻이다():
    assert agent_service.wants_to_finish("") is True
    assert agent_service.wants_to_finish("   ") is True
    assert agent_service.wants_to_finish("그냥 만들어줘") is True
    assert agent_service.wants_to_finish("없어요") is True
    assert agent_service.wants_to_finish("보내는 곳은 ABC입니다") is False


def test_다_만들면_운송_계획을_안내한다(app):
    out = agent_service.turn({"message": "그냥 만들어줘",
                              "draft": {**DRAFT, "kind": "packing_list_std"}})

    assert "운송 계획" in out["reply"]
    assert "PDF" in out["reply"]


# --- 라우트 ----------------------------------------------------------------------

def test_창구가_칸_목록과_초안을_돌려준다(app, client):
    first = client.post("/api/agent", json={"message": "패킹리스트 만들어줘",
                                            "draft": {}}).get_json()["data"]
    assert first["stage"] == "ask"

    draft = {**first["draft"], **DRAFT}
    second = client.post("/api/agent", json={"message": "그냥 만들어줘",
                                             "draft": draft}).get_json()["data"]
    assert second["stage"] == "made"
    assert second["preview"].startswith("data:image/png;base64,")
    assert second["file_url"].endswith(".pdf")


def test_PDF를_파일로_받는다(app, client):
    response = client.post("/documents/draft/packing_list_std.pdf",
                           json={"draft": DRAFT})

    assert response.status_code == 200
    assert response.mimetype == "application/pdf"
    assert "attachment" in response.headers["Content-Disposition"]
    assert response.data[:5] == b"%PDF-"


def test_품목_없이_PDF를_부르면_거절한다(app, client):
    response = client.post("/documents/draft/packing_list_std.pdf",
                           json={"draft": {"exporter_name": "A"}})

    assert response.status_code == 400


# --- 표를 눌러 넣은 틀 --------------------------------------------------------------

def test_칸_이름_값_꼴은_AI_없이_읽는다():
    """화면에서 표를 누르면 이 꼴로 들어갑니다. 모양이 정해졌으니 규칙으로 읽습니다."""

    typed = ("Shipper / Exporter: Forward Cosmetics Co., Ltd.\n"
             "Consignee: ABC Beauty Inc.\n"
             "Port of Loading (From): KRPUS\n"
             "Terms of Delivery: FOB")

    got = agent_service.parse_filled("commercial_invoice", typed)

    assert got["exporter_name"] == "Forward Cosmetics Co., Ltd."
    assert got["buyer_name"] == "ABC Beauty Inc."
    assert got["origin_code"] == "KRPUS"
    assert got["incoterms"] == "FOB"


def test_우리말_칸_이름으로_적어도_읽는다():
    got = agent_service.parse_filled("commercial_invoice", "보내는 회사 이름: 홍길동무역")

    assert got["exporter_name"] == "홍길동무역"


def test_그_서식에_없는_칸은_받지_않는다():
    """포장명세서에 거래 조건을 적어 보내도 무시합니다. 그 서식에 없는 칸입니다."""

    got = agent_service.parse_filled("packing_list_std",
                                     "Terms of Delivery: FOB\nConsignee: ABC")

    assert "incoterms" not in got
    assert got["buyer_name"] == "ABC"


def test_값이_비면_넣지_않는다():
    """틀만 넣고 안 적은 줄입니다. 빈 값으로 덮어쓰면 안 됩니다."""

    got = agent_service.parse_filled("commercial_invoice",
                                     "Consignee:   \nShipper / Exporter: ABC")

    assert "buyer_name" not in got
    assert got["exporter_name"] == "ABC"


def test_AI_키가_없어도_틀은_읽힌다(app):
    """시험 설정에는 AI 키가 없습니다. 그래도 여기까지는 동작해야 합니다."""

    from app.services import intake_service

    assert intake_service.available() is False

    out = agent_service.turn({
        "message": "Shipper / Exporter: ABC Corp\nConsignee: XYZ Inc",
        "draft": {"kind": "packing_list_std"}})

    assert out["draft"]["exporter_name"] == "ABC Corp"
    assert out["draft"]["buyer_name"] == "XYZ Inc"


def test_칸_목록이_세_열로_나온다(app):
    """구분 · 영문 칸 이름 · 기재 내용."""

    rows = agent_service.ask_list("commercial_invoice", {"exporter_name": "ABC"})

    for row in rows:
        assert row["group"] and row["ko"] and row["en"]
    # 이미 적은 것은 값까지 들고 옵니다.
    exporter = next(r for r in rows if r["field"] == "exporter_name")
    assert exporter["value"] == "ABC"
    assert exporter["en"] == "Shipper / Exporter"
    # 운송 계획에서 정해지는 칸은 그렇다고 표시합니다.
    origin = next(r for r in rows if r["field"] == "origin_code")
    assert origin["from_planning"] is True


def test_영문으로_적으라고_안내한다(app):
    out = agent_service.turn({"message": "상업송장만 작성해줘", "draft": {}})

    assert "영문" in out["reply"]
