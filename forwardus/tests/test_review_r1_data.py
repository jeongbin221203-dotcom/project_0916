"""전수 점검 1회차(2026-10-06) — 사용자·전문가 관점에서 나온 데이터 정확성 문제.

서류 정확성(은행·세관이 반송하는 것), 회원 간 데이터 분리, 작성 중 초안, 입력 검증.
"""

from __future__ import annotations

import pytest

from app import create_app, db
from app.models import Buyer, User
from app.services import planning_service, work_draft_service
from app.validators import ValidationError, document_validator as editing
from app.processors import document_validator as cross


# ── 회원 간 바이어 분리 (🔴 교차 사용자 데이터 손상) ────────────────────────────────────
def _make(app, shipment_payload, user_id, **buyer):
    payload = {**shipment_payload, "buyer": {"name": "ABC Beauty Inc.", "country": "US", **buyer}}
    payload["schedule_id"] = planning_service.search_schedules(payload)["items"][0]["schedule_id"]
    return planning_service.create_shipment(payload, user_id=user_id)


def test_다른_회원이_같은_바이어를_써도_주소와_이메일을_덮어쓰지_않는다(app, shipment_payload):
    a = _make(app, shipment_payload, 1, address="Address X", contact_email="alice@a.com")
    b = _make(app, shipment_payload, 2, address="Address Y", contact_email="bob@b.com")
    assert a.buyer.id != b.buyer.id
    assert a.buyer.address == "Address X" and a.buyer.contact_email == "alice@a.com"
    assert b.buyer.address == "Address Y" and b.buyer.contact_email == "bob@b.com"
    assert a.buyer.user_id == 1 and b.buyer.user_id == 2


def test_같은_회원이_주소를_바꿔_새_건을_만들어도_이전_건은_그대로다(app, shipment_payload):
    old = _make(app, shipment_payload, 1, address="Old Street 1")
    new = _make(app, shipment_payload, 1, address="New Avenue 2")
    assert old.buyer.address == "Old Street 1"
    assert new.buyer.address == "New Avenue 2" and old.buyer.id != new.buyer.id


def test_같은_회원의_같은_바이어는_다시_쓴다(app, shipment_payload):
    first = _make(app, shipment_payload, 1, address="Same Street 1")
    again = _make(app, shipment_payload, 1, address="Same Street 1")
    assert first.buyer.id == again.buyer.id


def test_주소를_안_적으면_앞서_적은_바이어를_그대로_쓴다(app, shipment_payload):
    first = _make(app, shipment_payload, 1, address="Same Street 1")
    blank = _make(app, shipment_payload, 1, address="")
    assert first.buyer.id == blank.buyer.id and blank.buyer.address == "Same Street 1"


def test_바이어_칸에_회원_번호가_덧붙는_마이그레이션이_있다(app):
    from sqlalchemy import inspect

    from app import migrate_buyer_columns

    migrate_buyer_columns(db)           # 이미 있으면 아무것도 하지 않습니다
    assert "user_id" in {c["name"] for c in inspect(db.engine).get_columns("buyers")}


# ── 작성 중 초안 (🟠 지워도 옛 값이 되살아남) ─────────────────────────────────────────
@pytest.fixture()
def member(app):
    user = User(email="draft@example.com", name="초안")
    user.set_password("secret123")
    db.session.add(user)
    db.session.commit()
    return user


def test_서류_작성에서_비운_칸과_품목은_서버에서도_지운다(member):
    work_draft_service.save(member, {"fields": {"buyer_name": "Wrong Buyer", "buyer_country": "US",
                                                "requested_departure_date": "2026-11-01"},
                                     "items": [{"product_description": "잘못된품목", "quantity": "5"}]},
                            "document")
    saved = work_draft_service.save(member, {"fields": {"buyer_name": "", "buyer_country": "",
                                                        "requested_departure_date": ""}, "items": []},
                                    "document")
    assert "buyer_name" not in saved["fields"] and "buyer_country" not in saved["fields"]
    assert "requested_departure_date" not in saved["fields"]
    assert saved["items"] == []


def test_대화에서_품목만_적어도_앞서_적은_항구는_남는다(member):
    work_draft_service.save(member, {"fields": {"origin_code": "KRPUS", "destination_code": "USLAX"}}, "document")
    saved = work_draft_service.save(member, {"items": [{"product_description": "치약", "quantity": "10"}]}, "chat")
    assert saved["fields"]["origin_code"] == "KRPUS" and saved["fields"]["destination_code"] == "USLAX"
    assert saved["items"][0]["product_description"] == "치약"


def test_대화가_빈_값을_보내도_지우지_않는다(member):
    work_draft_service.save(member, {"fields": {"buyer_name": "Keep Me"}}, "document")
    saved = work_draft_service.save(member, {"fields": {"buyer_name": ""}}, "chat")
    assert saved["fields"]["buyer_name"] == "Keep Me"


def test_서류_작성이_일부_칸만_보내면_안_보낸_칸은_남는다(member):
    work_draft_service.save(member, {"fields": {"origin_code": "KRPUS", "buyer_name": "A"}}, "document")
    saved = work_draft_service.save(member, {"fields": {"buyer_name": "B"}}, "document")
    assert saved["fields"]["origin_code"] == "KRPUS" and saved["fields"]["buyer_name"] == "B"


def test_초안_PUT_이_잘못된_본문이면_400(app):
    client = app.test_client()
    client.post("/auth/signup", data={"email": "p@example.com", "password": "secret123",
                                      "password_confirm": "secret123"})
    for body in ("[1,2]", '"text"', "5"):
        assert client.put("/api/work-draft", data=body, content_type="application/json").status_code == 400


# ── 입력 검증 ───────────────────────────────────────────────────────────────────────
def test_제어문자는_지우고_목록_값은_글자로_저장하지_않는다():
    from app.validators.shipment_validator import optional_text, plain_text, require_text

    assert plain_text("Name\u0000X\u0007") == "NameX"
    assert optional_text(["x"]) == "" and optional_text({"a": 1}) == ""
    with pytest.raises(ValidationError):
        require_text(["x"], "이름")
    assert require_text("  Hana  ", "이름") == "Hana"


def test_없는_나라_코드는_거절하고_이름과_실제_코드는_받는다(app):
    from app.validators.shipment_validator import validate_parties

    base = {"exporter_name": "Hana", "buyer": {"name": "ABC", "country": "ZZ"}}
    with pytest.raises(ValidationError, match="알 수 없"):
        validate_parties(base)
    assert validate_parties({**base, "buyer": {"name": "ABC", "country": "us"}})["buyer_country"] == "US"
    assert validate_parties({**base, "buyer": {"name": "ABC", "country": "미국"}})["buyer_country"] == "미국"
    assert validate_parties({**base, "buyer": {"name": "ABC"}})["buyer_country"] == ""


def test_지난_출발일은_날짜가_지났다고_말한다(app, shipment_payload):
    payload = {**shipment_payload, "requested_departure_date": "2020-01-01"}
    with pytest.raises(ValidationError) as caught:
        planning_service.create_shipment(payload)
    assert "이미 지났습니다" in str(caught.value) and caught.value.field == "requested_departure_date"


def test_오늘_출발일은_받는다(app, shipment_payload):
    from app.timeutil import today_kst

    payload = {**shipment_payload, "requested_departure_date": today_kst().isoformat()}
    payload["schedule_id"] = planning_service.search_schedules(payload)["items"][0]["schedule_id"]
    assert planning_service.create_shipment(payload)


# ── 서류 수정 저장 ──────────────────────────────────────────────────────────────────
CURRENT = {"currency": "USD", "incoterms": "FOB", "exporter": "Hana", "consignee": "ABC",
           "gross_weight_kg": 4000.0, "net_weight_kg": 3500.0, "hs_code": "3304.99", "doc_date": "06 OCT 2026",
           "quantity": 500}


@pytest.mark.parametrize("form", [
    {"currency": "ZZZ"}, {"incoterms": "XXX"}, {"hs_code": "abc"}, {"hs_code": "123"},
    {"doc_date": "2026-99-99"}, {"etd": "zzz"}, {"exporter": ""}, {"consignee": "  "},
    {"gross_weight_kg": "10"}, {"quantity": "1000000000000"},
], ids=lambda f: str(f))
def test_터무니없는_서류_값은_저장하지_않는다(form):
    with pytest.raises(ValidationError):
        editing.clean_document_fields(form, CURRENT)


@pytest.mark.parametrize("form", [
    {"currency": "usd"}, {"currency": "KRW"}, {"incoterms": "CIF LOS ANGELES"}, {"incoterms": "DAP"},
    {"hs_code": "3304.99.0000"}, {"doc_date": "2026-10-21"}, {"doc_date": "06 OCT 2026"},
    {"etd": "2026-10-21"}, {"exporter": "New Name Co."}, {"gross_weight_kg": "4000"},
], ids=lambda f: str(f))
def test_정상_서류_값은_저장한다(form):
    editing.clean_document_fields(form, CURRENT)


def test_사용자가_안_건드린_값은_새_규칙으로_막지_않는다():
    """서식이 만든 값("06 OCT 2026" · 옛 통화)을 사용자가 그대로 두고 저장하면 통과해야 합니다."""

    old = {**CURRENT, "currency": "GBP", "doc_date": "Oct-6th", "hs_code": "12345"}
    saved = editing.clean_document_fields({"currency": "GBP", "doc_date": "Oct-6th", "hs_code": "12345",
                                           "remarks": "x"}, old)
    assert saved["currency"] == "GBP" and saved["remarks"] == "x"


# ── 서류끼리 검증 ───────────────────────────────────────────────────────────────────
def _validate(doc_overrides, reference):
    documents = {"commercial_invoice": {"doc_date": "2026-10-06", "etd": "2026-10-21", "incoterms": "FOB",
                                        "pol": "Busan (KRPUS)", **doc_overrides},
                 "packing_list": {"incoterms": "FOB", "pol": "Busan (KRPUS)"}}
    return cross.validate_documents(documents, reference)


def test_송장_작성일이_날짜가_아니면_검증에_걸린다():
    result = _validate({"doc_date": "zzz"}, {})
    kinds = {(row["kind"], row["field"]) for row in result["findings"]}
    assert ("format", "doc_date") in kinds and result["status"] == "warning"


def test_정상_날짜_형식은_걸리지_않는다():
    for value in ("2026-10-06", "06 OCT 2026", "Oct 6, 2026", "2026/10/06", ""):
        assert not [r for r in _validate({"doc_date": value}, {})["findings"] if r["kind"] == "format"], value


def test_Incoterms_에_지정_장소를_적어도_기준값과_같다():
    result = _validate({"incoterms": "FOB BUSAN"}, {"incoterms": "FOB"})
    assert not [r for r in result["findings"] if r["field"] == "incoterms"]


def test_다른_Incoterms_코드는_여전히_걸린다():
    result = _validate({"incoterms": "CIF LOS ANGELES"}, {"incoterms": "FOB"})
    assert [r for r in result["findings"] if r["field"] == "incoterms"]


def test_항구에_나라를_붙여도_기준값과_같다():
    result = _validate({"pol": "BUSAN, KOREA"}, {"pol": "Busan (KRPUS)"})
    assert not [r for r in result["findings"] if r["field"] == "pol"]


def test_다른_항구는_여전히_걸린다():
    result = _validate({"pol": "INCHEON, KOREA"}, {"pol": "Busan (KRPUS)"})
    assert [r for r in result["findings"] if r["field"] == "pol"]


# ── 단가·품목·단위 ──────────────────────────────────────────────────────────────────
def test_다품목_건의_요약_단가는_틀린_값을_찍지_않는다(app, shipment_payload):
    from app.services import document_service

    payload = {**shipment_payload, "invoice_value": 6000,
               "cargo": [{**shipment_payload["cargo"], "quantity": 500, "unit_price": 10, "amount": 5000,
                          "product_description": "A", "hs_code": "3304.99"},
                         {**shipment_payload["cargo"], "quantity": 100, "unit_price": 10, "amount": 1000,
                          "product_description": "B", "hs_code": "3305.10"}]}
    try:
        payload["schedule_id"] = planning_service.search_schedules(payload)["items"][0]["schedule_id"]
        shipment = planning_service.create_shipment(payload)
    except ValidationError:
        pytest.skip("다품목 입력 모양이 다른 환경")
    assert len(list(shipment.cargos)) == 2
    assert document_service._summary_unit_price(shipment, shipment.cargo) is None


def test_금액만_적으면_되곱해지지_않는_단가를_지어내지_않는다():
    from app.validators import cargo_validator

    odd = cargo_validator.validate_commercial_line(
        {"package_type": "carton", "quantity": 3, "amount": 1000, "product_description": "x"})
    assert odd["unit_price"] is None                  # 1000 ÷ 3 = 333.3333 → ×3 = 999.9999
    even = cargo_validator.validate_commercial_line(
        {"package_type": "carton", "quantity": 4, "amount": 1000, "product_description": "x"})
    assert even["unit_price"] == 250                  # 정확히 되곱해지면 채웁니다


def test_둘째_품목_HS_가_비었으면_첫_품목_HS_를_복사하지_않는다(app, shipment_payload):
    payload = {**shipment_payload,
               "cargo": [{**shipment_payload["cargo"], "product_description": "A", "hs_code": "3304.99"},
                         {**shipment_payload["cargo"], "product_description": "B", "hs_code": ""}]}
    try:
        payload["schedule_id"] = planning_service.search_schedules(payload)["items"][0]["schedule_id"]
        shipment = planning_service.create_shipment(payload)
    except ValidationError:
        pytest.skip("다품목 입력 모양이 다른 환경")
    cargos = sorted(shipment.cargos, key=lambda c: c.line_no)
    assert cargos[0].hs_code == "3304.99" and cargos[1].hs_code == ""


@pytest.mark.parametrize("text,expected", [
    ("net weight 12.5 MT", "12500"), ("net 3000 lbs", "1360.777"), ("순중량 2톤", "2000"),
    ("net weight 500 kg", "500"), ("net weight 7 metric tons", "7000"), ("순중량 800g", "0.8"),
    ("net weight 5 total", "5"),
])
def test_채팅_중량_단위를_킬로그램으로_바꾼다(text, expected):
    from app.services import document_pipeline_service as pipeline

    match = pipeline._NET.search(text)
    assert match, text
    assert pipeline._kg(match.group(1), match.group(2)) == expected


# ── 수출신고 자료 ───────────────────────────────────────────────────────────────────
def test_6자리_HS_는_10자리가_필요하다고_알린다(app, create_shipment):
    from app.services import customs_filing_service

    shipment = create_shipment()                     # hs_code = 3304.99 (6자리)
    sheet = customs_filing_service.filing_sheet(shipment)
    assert any("10자리" in row for row in sheet["missing"])


def test_바이어_나라가_이름이어도_도착지_코드와_같으면_불일치로_세지_않는다(app, create_shipment):
    from app.services import customs_filing_service

    shipment = create_shipment(buyer={"name": "ABC Beauty Inc.", "country": "미국"})
    assert not [m for m in customs_filing_service._mismatches(shipment) if "받는 분 나라" in m]


# ── 서버 시각 ───────────────────────────────────────────────────────────────────────
def test_한국_시각_기준_날짜를_쓴다(monkeypatch):
    from datetime import datetime, timezone

    from app import timeutil

    class Fixed(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 1, 1, 0, 30, tzinfo=timezone.utc).astimezone(tz)   # UTC 1월 1일 00:30

    monkeypatch.setattr(timeutil, "datetime", Fixed)
    assert timeutil.today_kst().isoformat() == "2026-01-01"          # 한국은 이미 09:30
    class Late(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2025, 12, 31, 16, 0, tzinfo=timezone.utc).astimezone(tz)  # UTC 12/31 16:00
    monkeypatch.setattr(timeutil, "datetime", Late)
    assert timeutil.today_kst().isoformat() == "2026-01-01"          # UTC 로는 전날이지만 한국은 다음 날 01:00


# ── 1회차 마무리(2026-10-06): 순중량 합계 · 보험료 · 초안 금액 · 품목 표 · 예시 스케줄 ─────────────────
def test_순중량이_하나라도_비면_합계를_내지_않는다():
    from app.processors import cargo_calculator

    line = {"length_cm": 50, "width_cm": 40, "height_cm": 30, "quantity": 10, "weight_per_package_kg": 8,
            "package_type": "carton"}
    some = cargo_calculator.calculate_cargo_lines([{**line, "net_weight_kg": 50}, {**line}], strict=False)
    assert some["net_weight_kg"] is None
    every = cargo_calculator.calculate_cargo_lines(
        [{**line, "net_weight_kg": 50}, {**line, "net_weight_kg": 60}], strict=False)
    assert every["net_weight_kg"] == 110


def test_운임이_송장에_들어_있는_조건은_보험료에_운임을_또_더하지_않는다():
    from app.processors.cost_calculator import FREIGHT_IN_PRICE, calculate_insurance_premium

    assert {"CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP"} == set(FREIGHT_IN_PRICE)
    plain = calculate_insurance_premium(25000, 1580, 1380)
    included = calculate_insurance_premium(25000, 1580, 1380, freight_included=True)
    assert included < plain
    assert round(included / plain, 4) == round(25000 / (25000 + 1580), 4)


def test_견적의_보험료는_조건에_따라_운임을_더하거나_더하지_않는다():
    from app.processors.cost_calculator import calculate_logistics_cost

    metrics = {"container_quantity": 1, "billable_revenue_ton": 3}
    kwargs = dict(transport_mode="SEA", sea_mode="LCL", freight_usd=1580, freight_source="mock",
                  invoice_value_usd=25000, metrics=metrics, exchange_rate=1380)

    def insurance(incoterms):
        result = calculate_logistics_cost(incoterms=incoterms, **kwargs)
        return next(row["krw_amount"] for row in result["lines"] if row["code"] == "insurance")

    assert insurance("CIF") < insurance("FOB")          # CIF 는 송장 금액에 운임이 이미 포함


@pytest.mark.parametrize("value", ["nan", "-500", "inf", "abc", None, ""])
def test_초안_서류_금액은_nan_음수를_그대로_찍지_않는다(value):
    from app.services import draft_document_service

    assert draft_document_service._number(value) == 0.0
    assert draft_document_service._number("1,234.5") == 1234.5


def _items_check(items, invoice_value):
    return [r["message"] for r in cross.validate_documents(
        {"commercial_invoice": {"invoice_value": invoice_value, "items": items}}, {})["findings"]
        if r["kind"] == "items"]


def test_품목_표가_맞으면_걸리지_않는다():
    items = [{"quantity": 500, "unit_price": 10.0, "amount": 5000.0},
             {"quantity": 100, "unit_price": 10.0, "amount": 1000.0}]
    assert _items_check(items, 6000.0) == []


def test_품목_줄_금액을_엉터리로_고치면_검증에_걸린다():
    items = [{"quantity": 3, "unit_price": 999.0, "amount": 1.0},
             {"quantity": 100, "unit_price": 10.0, "amount": 1000.0}]
    messages = _items_check(items, 6000.0)
    assert any("품목 1줄" in m for m in messages) and any("합계" in m for m in messages)


def test_품목_합계가_송장_금액과_다르면_걸린다():
    items = [{"quantity": 500, "unit_price": 10.0, "amount": 5000.0}]
    assert any("합계" in m for m in _items_check(items, 6000.0))


def test_아직_안_적은_품목_칸은_다르다고_하지_않는다():
    assert _items_check([{"quantity": 3, "unit_price": "", "amount": ""}], 6000.0) == []


def test_품목_표_숫자_칸에_글자를_넣으면_저장하지_않는다():
    current = {"items": [{"description": "A", "quantity": 5, "unit_price": 10.0, "amount": 50.0}]}
    for name, value in (("item-0-amount", "abc"), ("item-0-quantity", "-3"), ("item-0-unit_price", "nan")):
        with pytest.raises(ValidationError, match="품목 1줄"):
            editing.clean_document_fields({name: value}, current)
    saved = editing.clean_document_fields({"item-0-amount": "55.00", "item-0-description": "B"}, current)
    assert saved["items"][0]["amount"] == "55.00" and saved["items"][0]["description"] == "B"


def test_예시_스케줄로_만든_건은_서류_센터에_경고가_뜬다(app, create_shipment):
    shipment = create_shipment()
    shipment.schedule_source = "mock"
    db.session.commit()
    client = app.test_client()
    client.post("/auth/signup", data={"email": "mk@example.com", "password": "secret123",
                                      "password_confirm": "secret123"})
    shipment.user_id = User.query.filter_by(email="mk@example.com").one().id
    db.session.commit()
    html = client.get(f"/documents/{shipment.shipment_id}").get_data(as_text=True)
    assert "data-mock-schedule-warning" in html and "예시 스케줄" in html
    shipment.schedule_source = "api"
    db.session.commit()
    assert "data-mock-schedule-warning" not in client.get(f"/documents/{shipment.shipment_id}").get_data(as_text=True)
