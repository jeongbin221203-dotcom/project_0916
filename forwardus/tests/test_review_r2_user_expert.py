"""전수 점검 2회차(2026-10-07) — 사용자·전문가 관점.

채팅 수량·단위 인식, 위험물·특대 화물 경고, 수출요건 규칙, 추적 날짜, 서류 PDF 잘림, 화면(JS·CSS).
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from app import db
from app.processors import cargo_calculator, document_form, export_requirements
from app.services import chat_capture_service as chat, required_docs_service, tracking_service
from app.timeutil import today_kst
from app.validators import ValidationError
from app.validators import cargo_validator

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


# ── 채팅 수량·단위 — "박스당 20개입, 총 500박스" 가 수량 20 이 되던 것 ──────────────────────────
def _item(text):
    items = chat.read(text).get("items") or [{}]
    return items[0]


@pytest.mark.parametrize("text,quantity", [
    ("박스당 20개입, 총 500박스 40x30x25cm 12kg", "500"),
    ("개당 0.5kg 짜리 제품을 한 박스에 24개씩 500박스", "500"),
    ("컨테이너 1개에 가능한가요? 500박스 치약", "500"),
    ("3개월 안에 납품, 샘플 2개 먼저, 치약 500박스", "500"),
    ("치약 300개 한 박스 8kg", "300"),
    ("팔레트당 800kg, 1.2x1.0x1.5m 20팔레트", "20"),
])
def test_채팅은_포장_수를_수량으로_읽는다(text, quantity):
    assert _item(text).get("quantity") == quantity


def test_낱개_수량은_포장_수가_없을_때만():
    assert _item("치약 10000개 한 박스 8kg").get("quantity") == "10000"


@pytest.mark.parametrize("text", ["3개월 안에 납품", "5개국에 판매", "박스당 20개입"])
def test_개월_개국_개입은_수량이_아니다(text):
    assert _item(text).get("quantity") not in ("3", "5", "20")


@pytest.mark.parametrize("text,dims", [
    ("1.2x1.0x1.5m 20팔레트", ("120", "100", "150")),
    ("500mm x 400mm x 300mm 박스 100박스", ("50", "40", "30")),
    ("40cm x 30cm x 25cm 한 박스 12kg 500박스", ("40", "30", "25")),
    ("40x30x25cm 500박스 12kg", ("40", "30", "25")),
])
def test_채팅_치수_단위를_cm_로_바꾼다(text, dims):
    item = _item(text)
    assert (item["length_cm"], item["width_cm"], item["height_cm"]) == dims


@pytest.mark.parametrize("text,kg", [
    ("한 박스 12,5kg 짜리 500박스", "12.5"), ("한 박스 12kg 500박스", "12"),
    ("한 박스 0.5 MT 20박스", "500"), ("한 박스 100 lb 20박스", "45.359"),
])
def test_채팅_중량_단위와_소수점_쉼표(text, kg):
    assert _item(text).get("weight_per_package_kg") == kg


def test_품명에_짜리_컨테이너는_들어가지_않는다():
    item = _item("한 박스 0.5kg 500g짜리 10000개")
    assert item.get("product_description") not in ("짜리",)


# ── 위험물 정합성 — 막지 않고 알립니다 ───────────────────────────────────────────────────
@pytest.mark.parametrize("un,cls,pg,expect", [
    ("1263", "8", "I", "보통 3급"),                      # 페인트인데 8급
    ("3480", "9", "II", "포장등급이 없습니다"),             # 리튬 배터리에 PG
    ("9999", "3", "", "번호 범위"),
    ("1263", "3", "", "포장등급"),                        # 3급은 PG 필요
    ("1950", "2.1", "II", "보통 포장등급이 없습니다"),       # 가스에 PG
])
def test_위험물_번호_급_포장등급이_안_맞으면_알린다(un, cls, pg, expect):
    assert any(expect in note for note in cargo_validator.dg_consistency(un, cls, pg))


@pytest.mark.parametrize("un,cls,pg", [("1263", "3", "II"), ("1789", "8", "II"), ("1013", "2.2", ""),
                                       ("3480", "9", ""), ("2794", "8", "III")])
def test_맞는_위험물은_경고가_없다(un, cls, pg):
    assert cargo_validator.dg_consistency(un, cls, pg) == []


def test_위험물_경고는_저장을_막지_않는다():
    payload = {"is_dangerous": "true", "un_number": "UN1263", "dg_class": "8", "packing_group": "I",
               "proper_shipping_name": "PAINT"}
    result = cargo_validator.validate_dangerous_goods(payload, strict=True)
    assert result["un_number"] == "UN1263" and "보통 3급" in result["dg_warning"]


# ── 특대 화물 ───────────────────────────────────────────────────────────────────────────
def _dims(length, width, height):
    return {"length_cm": length, "width_cm": width, "height_cm": height}


def test_컨테이너에_안_들어가는_포장은_OOG_경고():
    note = " ".join(cargo_calculator.oversize_warnings(_dims(1500, 350, 320)))
    assert "OOG" in note and "어느 방향으로도" in note


def test_40GP_높이를_넘고_40HC_에는_들어가면_40HC_필요():
    note = " ".join(cargo_calculator.oversize_warnings(_dims(300, 120, 250)))
    assert "40HC" in note and "OOG" not in note


@pytest.mark.parametrize("dims", [(50, 40, 30), (300, 120, 200), (1100, 230, 200)])
def test_보통_크기는_경고가_없다(dims):
    assert cargo_calculator.oversize_warnings(_dims(*dims)) == []


def test_특대_경고가_줄별_계산과_경고_목록에_실린다():
    line = {"length_cm": 1500, "width_cm": 350, "height_cm": 320, "quantity": 1, "weight_per_package_kg": 12000,
            "package_type": "carton"}
    result = cargo_calculator.calculate_cargo_lines([line], strict=False)
    assert "OOG" in result["lines"][0]["oversize_warning"]
    assert any("OOG" in warning["message"] for warning in result["warnings"])


# ── 수출요건 ───────────────────────────────────────────────────────────────────────────
def _keys(hs):
    return [item["key"] for item in export_requirements.check(hs)]


@pytest.mark.parametrize("hs", ["0306170000", "0302320000", "1604140000", "1212212000", "1212291000"])
def test_수산물과_김은_수산물_규칙으로(hs):
    keys = _keys(hs)
    assert "fishery" in keys and "animal" not in keys and "plant" not in keys


@pytest.mark.parametrize("hs,key", [("3601000000", "explosive"), ("9303200000", "explosive"),
                                    ("2301100000", "feed"), ("2208900000", "alcohol"),
                                    ("6815110000", "strategic")])
def test_규칙이_없던_품목에_요건이_붙는다(hs, key):
    assert key in _keys(hs)


@pytest.mark.parametrize("hs,absent", [("1212991000", "fishery"), ("0201100000", "fishery"),
                                       ("1211200000", "fishery"), ("3304991000", "fishery")])
def test_다른_품목에는_수산물_규칙을_붙이지_않는다(hs, absent):
    assert absent not in _keys(hs)


def test_육류와_식물은_그대로_검역이다():
    assert "animal" in _keys("0201100000") and "plant" in _keys("1211200000")


def test_규칙표에_없으면_없다고_단정하지_않는다():
    text = export_requirements.summary("9999999999", [])
    assert "그렇다고 요건이 없다는 뜻은 아닙니다" in text and "통합공고" in text


# ── 중국 CCC ───────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("chapter", ["85", "87", "40", "95"])
def test_CCC_는_자동차_부품_타이어_어린이_제품에도_보인다(chapter):
    assert required_docs_service._cert_fits("중국 CCC 인증", {chapter})


def test_CCC_는_상관없는_품목에서는_걸러진다():
    assert not required_docs_service._cert_fits("중국 CCC 인증", {"03"})


def test_FCC_는_자동차_부품에_보이지_않는다():
    assert not required_docs_service._cert_fits("미국 FCC 인증", {"87"})


# ── 추적 ───────────────────────────────────────────────────────────────────────────────
def test_미래_날짜_이벤트는_기록하지_않는다(app, create_shipment):
    shipment = create_shipment()
    future = (today_kst() + timedelta(days=5)).isoformat()
    with pytest.raises(ValidationError, match="오늘보다 뒤"):
        tracking_service.add_manual_event(shipment, {"event_code": "booking_confirmed", "event_date": future})


def test_오늘과_지난_날짜_이벤트는_기록한다(app, create_shipment):
    shipment = create_shipment()
    for days in (0, 3):
        day = (today_kst() - timedelta(days=days)).isoformat()
        tracking_service.add_manual_event(shipment, {"event_code": "booking_confirmed", "event_date": day})


def test_터무니없는_ETA_는_기록하지_않는다(app, create_shipment):
    shipment = create_shipment()
    far = (shipment.etd + timedelta(days=tracking_service.MAX_TRANSIT_DAYS + 1)).isoformat()
    with pytest.raises(ValidationError, match="연도"):
        tracking_service.update_eta_manually(shipment, {"new_eta": far})


def test_정상_ETA_변경은_기록한다(app, create_shipment):
    shipment = create_shipment()
    later = (shipment.eta + timedelta(days=6)).isoformat()
    tracking_service.update_eta_manually(shipment, {"new_eta": later})
    assert shipment.eta.isoformat() == later


# ── 문구 · 오류 페이지 ─────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("label,josa_", [("수출자(Exporter)명", "을"), ("견적명", "을"), ("운송 모드", "를"),
                                          ("Buyer(Consignee)명", "을")])
def test_필수_입력_메시지는_앞말에_맞는_조사를_쓴다(label, josa_):
    from app.validators.shipment_validator import require_text

    with pytest.raises(ValidationError) as caught:
        require_text("", label)
    assert str(caught.value) == f"{label}{josa_} 입력해주세요."
    assert "을(를)" not in str(caught.value)


def test_405_는_우리_화면으로_나온다(app):
    client = app.test_client()
    html = client.get("/planning/api/cargo")
    assert html.status_code == 405 and html.get_json()["error_code"] == "METHOD_NOT_ALLOWED"


# ── 서류 PDF — 말없이 잘리지 않는다 ───────────────────────────────────────────────────────
def _drawing():
    from PIL import Image, ImageDraw

    image = Image.new("RGB", document_form.PAGE, "white")
    return image, ImageDraw.Draw(image)


def _fonts():
    return {"title": document_form._font(30, bold=True), "label": document_form._font(13),
            "body": document_form._font(16), "small": document_form._font(12)}


COLUMNS = [{"key": "description", "label": "Goods description"}, {"key": "quantity", "label": "Quantity"}]
LONG = ("Premium Organic Green Tea Bags 100pcs per box for export 2026 edition with extra long marketing "
        "text and certificate and more words")


def test_긴_품명은_행을_키워_보여_준다():
    _, draw = _drawing()
    short = document_form._table(draw, COLUMNS, [{"description": "Tea", "quantity": 1}], 100, 1100, _fonts())
    tall = document_form._table(draw, COLUMNS, [{"description": LONG * 2, "quantity": 1}], 100, 1100, _fonts())
    assert tall > short                                 # 2줄 이상이면 행이 높아집니다


def test_공간이_모자라면_줄이고_말줄임표를_붙인다():
    image, draw = _drawing()
    items = [{"description": LONG, "quantity": 1}] * 20
    bottom = document_form.PAGE[1] - 152 - 70
    # 실제 상업송장에서 표가 시작하는 위치(머리 칸 7줄 아래 ≈ 670px)에서 그립니다.
    end = document_form._table(draw, COLUMNS, items, 670, 1100, _fonts(), bottom=bottom)
    assert end <= bottom                                 # 20행도 바닥 칸 앞에서 끝납니다


def test_말줄임표는_폭_안에_들어간다():
    _, draw = _drawing()
    font = document_form._font(16)
    text = document_form._ellipsis(draw, "Premium Organic Green Tea Bags 100pcs per box", font, 160)
    assert text.endswith("…") and draw.textlength(text, font=font) <= 160


def test_문서를_그려도_예외가_없다():
    from app.services import draft_document_service as drafts

    data = {"exporter_name": "Hana", "consignee": "ABC", "incoterms": "FOB", "currency": "USD",
            "invoice_value": 6000, "items": [{"description": LONG, "quantity": 500, "unit_price": 10.0,
                                              "amount": 5000.0, "packages": "500 CTN", "shipping_marks": ""}]}
    page = document_form.draw_form("commercial_invoice", data, drafts.item_columns("commercial_invoice"))
    assert page.size == document_form.PAGE


# ── 화면 (JS·CSS) — 글자로 확인합니다 ────────────────────────────────────────────────────
def _read(*parts):
    return STATIC.joinpath(*parts).read_text(encoding="utf-8")


def test_파일을_올리는_순간에는_칸을_지우지_않는다():
    js = _read("js", "doc_form.js")
    start = js.index("onStart(file) {")
    on_start = js[start:js.index("onError()", start)]
    assert "clearForm()" not in on_start.split("//")[-1] and "showReading(file)" in on_start
    result = js[js.index("onResult(data) {"):]
    assert result.index("clearForm()") < result.index("FORWARDUS_DOC_FILL")      # 성공한 뒤에만 비웁니다


def test_견적_마법사는_덜_찬_추가_품목을_알린다():
    js = _read("js", "planning.js")
    assert "function incompleteCargoLines" in js and "incompleteCargoLines()" in js
    assert 'form.querySelectorAll("section[data-step]")' in js
    assert '"amount",' in js[js.index("const DRAFT_FIELDS"):js.index("function saveDraft")]


def test_위험물_상자는_휴대폰에서_span2_를_푼다():
    css = _read("css", "planning.css")
    assert ".dg_fields .field.span2 { grid-column: auto; }" in css


def test_자동완성은_키보드로_고른다():
    js = _read("js", "base.js")
    for needle in ('event.key === "ArrowDown"', 'event.key === "Enter"', "event.preventDefault();                       // 폼 제출 막기",
                   "closeUnlessFocused", 'list.addEventListener("focusout"'):
        assert needle in js, needle
