"""오퍼시트 다시 확인에서 나온 것들.

실제 OpenAI로 한글 견적서·스캔 PDF·워드 표를 넣어 보고 찾은 문제입니다.
  A. 한글 견적서의 입금계좌·SWIFT가 가려지지 않고 AI로 갔습니다
  B. 단위 "개"를 몰라 단가를 버렸습니다
  C. "USD 4.50"처럼 통화가 붙은 숫자를 읽지 못했습니다
  D. "미국 로스앤젤레스"처럼 나라가 앞에 붙은 항구를 못 찾았습니다
  E. "2026년 10월 15일"을 원문에서 못 찾아 쓸데없이 확인을 받았습니다
"""

from __future__ import annotations

import pytest

from app.services import offer_sheet_service as offer
from app.validators.cargo_validator import price_unit_of

KR_ACCOUNT = "110-123-456789"


# --- A. 번호 가리기 ----------------------------------------------------------------

@pytest.mark.parametrize("text, hidden", [
    # 엑셀은 칸 사이를 " | "로 잇습니다.
    (f"입금계좌 | 신한은행 {KR_ACCOUNT} (예금주: 포워드코스메틱)", KR_ACCOUNT),
    ("SWIFT | SHBKKRSE", "SHBKKRSE"),
    # 이름표와 번호 사이에 은행 이름이 끼는 일이 흔합니다.
    (f"계좌번호: 국민은행 {KR_ACCOUNT}", KR_ACCOUNT),
    (f"Account: Shinhan Bank {KR_ACCOUNT}", KR_ACCOUNT),
    # 번호가 이름표 아래 줄에 따로 있는 경우
    (f"Beneficiary Account\n{KR_ACCOUNT}", KR_ACCOUNT),
    ("Bank: Shinhan Bank\nSWIFT CODE\nSHBKKRSE", "SHBKKRSE"),
    # 줄 이름표 없이 은행 줄에 있는 긴 번호
    (f"Shinhan Bank Gangnam Branch {KR_ACCOUNT}", KR_ACCOUNT),
])
def test_은행_번호는_모양이_달라도_가린다(text, hidden):
    clean, secrets = offer.redact(text)

    assert hidden not in clean
    assert hidden in secrets.values()


@pytest.mark.parametrize("text", [
    "Offer No.: OS-2026-0917  Date: 2026-09-22",
    "Validity: Until 2026-10-15",
    "TOTAL | USD 10,650.00",
    "1 | Hair Shampoo 500ml | 2000 | PCS | 3.20 | 6400.00",
    "Exporter / Beneficiary / Seller | Forward Cosmetics Co., Ltd.",
    "123 Teheran-ro, Gangnam-gu, Seoul",
])
def test_은행과_상관없는_번호와_글자는_그대로_둔다(text):
    """오퍼 번호·날짜·금액을 가리면 AI가 그 값을 못 읽습니다."""

    assert offer.redact(text)[0] == text


def test_가린_표시가_은행_칸이_아닌_곳에_들어오면_비운다(app):
    """AI가 [ACCOUNT_1]을 비고란 등에 옮겨 적으면, 되돌리지도 저장하지도 않습니다."""

    raw = _raw(remarks_packing="Pay to [ACCOUNT_1]")
    result = offer.verify(raw, mode="text", source_text="Pay to [ACCOUNT_1]",
                          secrets={"[ACCOUNT_1]": KR_ACCOUNT})

    row = next(row for row in result["fields"] if row["key"] == "remarks")
    # 번호 자리는 [계좌번호]로 남겨 어디에 있었는지는 보이게 하고, 초안에는 넣지 않습니다.
    assert row["value"] == "Pay to [계좌번호]" and row["status"] == "check"
    assert KR_ACCOUNT not in repr(result) and "remarks" not in result["draft"]


# --- B. 한글 단위 ------------------------------------------------------------------

@pytest.mark.parametrize("written, expected", [
    ("개", "PCS"), ("세트", "SET"), ("켤레", "PR"), ("다스", "DZ"), ("박스", "BOX"),
    ("병", "BTL"), ("장", "SHEET"), ("롤", "ROLL"), ("킬로그램", "KG"), ("kg", "KG"),
    ("톤", "MT"), ("리터", "L"), ("미터", "M"),
])
def test_한글_단위를_알아본다(written, expected):
    assert price_unit_of(written) == expected


# --- C. 통화가 붙은 숫자 ----------------------------------------------------------

@pytest.mark.parametrize("written, expected", [
    ("USD 4.50", 4.5), ("US$4.50", 4.5), ("$ 5,400.00", 5400.0), ("5,400.00 USD", 5400.0),
    ("₩3,200", 3200.0), ("EUR 1,234.56", 1234.56), ("4.50", 4.5),
])
def test_통화가_붙은_숫자를_읽는다(written, expected):
    assert offer._number(written) == expected


@pytest.mark.parametrize("written", ["3,20", "1.234,56", "about 4.5", "-3", ""])
def test_애매한_숫자는_읽지_않는다(written):
    """3,20은 3.20인지 320인지 모릅니다. 짐작하지 않고 사람에게 묻습니다."""

    assert offer._number(written) is None


# --- D. 나라가 붙은 항구 ------------------------------------------------------------

@pytest.mark.parametrize("written, code", [
    ("미국 로스앤젤레스", "USLAX"), ("Los Angeles USA", "USLAX"), ("Los Angeles, USA", "USLAX"),
])
def test_나라가_붙은_항구를_찾는다(app, written, code):
    from app.services import intake_service

    with app.app_context():
        place = intake_service._place(written, "SEA", "destination", [])

    assert place and place["code"] == code


# --- E. 날짜 원문 대조 -------------------------------------------------------------

@pytest.mark.parametrize("source", [
    "유효기간 2026년 10월 15일", "Validity: Oct. 15, 2026", "valid until 15 October 2026",
    "Validity 2026.10.15", "Validity 2026/10/15",
])
def test_날짜는_모양이_달라도_원문에서_찾는다(app, source):
    raw = _raw(validity_date="2026-10-15")
    with app.app_context():
        result = offer.verify(raw, mode="text", source_text=source, secrets={})

    row = next(row for row in result["fields"] if row["key"] == "validity_date")
    assert row["status"] == "ok"


def test_다른_날짜는_원문에_있다고_보지_않는다(app):
    raw = _raw(validity_date="2026-10-15")
    with app.app_context():
        result = offer.verify(raw, mode="text", source_text="Validity 2026년 11월 15일", secrets={})

    row = next(row for row in result["fields"] if row["key"] == "validity_date")
    assert row["status"] == "check"


def _raw(remarks_packing: str = "", **changes) -> dict:
    raw = {key: "" for key in offer.SCHEMA["properties"]}
    raw.update(items=[], uncertain_fields=[], seller_name="Forward", packing=remarks_packing)
    raw.update(changes)
    return raw


# --- 코드 검토에서 나온 것 ---------------------------------------------------------

def _item(**changes) -> dict:
    item = {"description": "Hair Shampoo 500ml", "hs_code": "", "quantity": "2000",
            "quantity_unit": "PCS", "unit_price": "3.20", "amount": "6400.00",
            "pieces_per_package": "20", "package_content_unit": "PCS", "package_type": "carton"}
    item.update(changes)
    return item


SOURCE = "Hair Shampoo 500ml Forward Buyer Co"


def _verify(app, **changes):
    raw = _raw(buyer_name="Buyer Co", total_amount="6400.00", items=[_item()])
    raw.update(changes)
    with app.app_context():
        return offer.verify(raw, mode="text", source_text=SOURCE + " " + str(changes), secrets={})


def test_결제_조건에_섞인_계좌번호는_저장하지도_보여주지도_않는다(app):
    """"T/T to Shinhan Bank A/C 100-200-300400"이 초안(=서버 저장)에 들어가던 일."""

    result = _verify(app, payment_terms=f"T/T in advance to Shinhan Bank A/C No. {KR_ACCOUNT}")

    row = next(row for row in result["fields"] if row["key"] == "payment_terms")
    assert KR_ACCOUNT not in row["value"] and row["status"] == "check"
    assert KR_ACCOUNT not in repr(result["draft"])


def test_사진에서_읽은_결제_조건의_계좌번호도_지운다(app):
    """사진은 가릴 수 없어 번호가 그대로 옵니다. 돌아온 뒤에라도 지웁니다."""

    raw = _raw(payment_terms=f"T/T to Shinhan Bank A/C {KR_ACCOUNT}", items=[])
    with app.app_context():
        result = offer.verify(raw, mode="image", source_text="", secrets={})

    row = next(row for row in result["fields"] if row["key"] == "payment_terms")
    assert KR_ACCOUNT not in row["value"]


def test_점이_천_단위인_숫자는_계산이_맞아도_믿지_않는다(app):
    """1.000 × 5 = 5.000이 계산은 맞지만 1개인지 1,000개인지 모릅니다."""

    result = _verify(app, items=[_item(quantity="1.000", unit_price="5", amount="5.000",
                                       pieces_per_package="")], total_amount="5.000")

    assert result["items"][0]["status"] == "missing"
    assert result["draft"]["items"] == []


def test_총액이_없으면_품목을_확인받는다(app):
    result = _verify(app, total_amount="")

    assert result["items"][0]["status"] == "check"
    assert result["draft"]["items"] == []


def test_상자_단가에_낱개_포장_정보를_적용하지_않는다(app):
    """100 CTN × 64.00에 20 PCS/CTN을 적용하면 5상자가 됩니다."""

    result = _verify(app, items=[_item(quantity="100", quantity_unit="CTN", unit_price="64.00",
                                       amount="6400.00")])

    line = result["items"][0]["line"]
    assert "units_per_package" not in line and "quantity" not in line


def test_AI가_품목_한_칸을_못_읽었다고_하면_확인받는다(app):
    result = _verify(app, uncertain_fields=["items[0].unit_price"])

    assert result["items"][0]["status"] == "check"


def test_바이어와_수출자_이름이_같으면_둘_다_확인받는다(app):
    result = _verify(app, buyer_name="Forward", seller_name="Forward")

    rows = {row["key"]: row for row in result["fields"]}
    assert rows["buyer_name"]["status"] == rows["exporter_name"]["status"] == "check"


def test_빈_품목_하나만_있으면_직접_입력하라고_한다(app):
    from app.services import ServiceError

    empty = {key: "" for key in _item()}
    raw = _raw(seller_name="", items=[empty])
    with app.app_context(), pytest.raises(ServiceError):
        offer.verify(raw, mode="text", source_text="", secrets={})


def test_음수는_없다가_아니라_못_읽었다고_한다(app):
    result = _verify(app, items=[_item(quantity="-5")])

    assert any("읽지 못했습니다" in problem for problem in result["items"][0]["problems"])


def test_확인한_품목은_검증기가_읽은_값으로_저장한다(app):
    from app.services import draft_store

    with app.app_context():
        token = draft_store.save({"draft": {}, "fields": [], "items": [], "source": {}})
        result = offer.confirm(token, {}, [{"product_description": "Shampoo",
                                            "unit_quantity": "2,000", "price_unit": "pcs",
                                            "unit_price": "3.20"}])

    line = result["draft"]["items"][0]
    assert (line["unit_quantity"], line["price_unit"], line["amount"]) == (2000.0, "PCS", 6400.0)


def test_PDF에는_바이어_연락처가_찍힌다(app):
    from app.services import draft_document_service as drafts

    merged = drafts.with_private({"exporter_name": "Forward", "buyer_name": "Buyer Co",
                                  "items": [{"product_description": "Shampoo", "unit_quantity": 1,
                                             "price_unit": "PCS", "unit_price": 1, "amount": 1}]},
                                 {"buyer_address": "1 Main St", "buyer_contact": "john@buyer.example"})
    with app.app_context():
        for kind in ("proforma_invoice", "commercial_invoice", "packing_list_std"):
            data = drafts.render(kind, merged)["data"]
            assert "john@buyer.example" in repr(data), kind


@pytest.mark.parametrize("text", [
    f"Bank: Shinhan Bank, A/C No. {KR_ACCOUNT}\nValidity: 2026-10-31",
    f"A/C {KR_ACCOUNT}\nValid until 31.10.2026",
])
def test_은행_줄_아래의_날짜는_가리지_않는다(text):
    """유효기간까지 가려서 AI가 못 읽은 일이 있었습니다."""

    clean, secrets = offer.redact(text)

    assert KR_ACCOUNT not in clean
    assert "2026-10-31" in clean or "31.10.2026" in clean
    assert len(secrets) == 1


def test_EA와_PCS는_상자_수를_셀_때_같은_낱개로_본다(app):
    result = _verify(app, items=[_item(quantity_unit="EA", package_content_unit="PCS")])

    line = result["items"][0]["line"]
    assert line["price_unit"] == "EA"            # 서류에는 적힌 대로
    assert line["quantity"] == 100               # 2,000 ÷ 20
