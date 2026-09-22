"""오퍼시트를 올려 서류 초안을 만드는 길.

지키는 것
  1. 확실한 것만 초안에 들어간다 (계산이 맞는 숫자, 목록에 있는 코드, 원문에 있는 글자)
  2. 사진에서 읽은 글자는 사람이 확인하기 전에는 초안에 들어가지 않는다
  3. 은행 정보와 바이어 주소·연락처는 서버 어디에도 남지 않는다
  4. 글자 파일의 계좌번호는 AI(OpenAI)에게 보내기 전에 가린다
  5. 원본 파일은 디스크에 쓰지 않는다

AI는 흉내 냅니다. 실제 OpenAI를 부르는 확인은 따로 합니다.
"""

from __future__ import annotations

import io
import json
from unittest.mock import patch

import pytest
from werkzeug.datastructures import FileStorage

from app.services import ServiceError, draft_store
from app.services import offer_sheet_service as offer
from app.validators import ValidationError

ACCOUNT = "100-200-300400"
SWIFT = "SHBKKRSE"
BUYER_ADDRESS = "1200 Wilshire Blvd, Los Angeles, CA 90017, USA"

ROWS = [
    ["OFFER SHEET"],
    ["Offer No.", "OS-2026-0917", "Date", "2026-09-22"],
    ["Messrs.", "ABC Beauty Inc."],
    ["", BUYER_ADDRESS],
    ["Seller", "Forward Cosmetics Co., Ltd."],
    ["", "123 Teheran-ro, Gangnam-gu, Seoul, Korea"],
    ["No.", "Description", "Q'ty", "Unit", "Unit Price", "Amount"],
    [1, "Hair Shampoo 500ml", 2000, "PCS", "USD 3.20", "USD 6,400.00"],
    [2, "Toothpaste 120g", 5000, "PCS", "USD 0.85", "USD 4,250.00"],
    ["", "", "", "", "TOTAL", "USD 10,650.00"],
    ["Price Term", "FOB Busan, Korea"],
    ["Destination", "Los Angeles, USA"],
    ["Shipment", "Within 30 days after receipt of L/C"],
    ["Payment", "Irrevocable L/C at sight"],
    ["Packing", "Export standard carton: shampoo 20 PCS/CTN, toothpaste 100 PCS/CTN"],
    ["Validity", "Until 2026-10-15"],
    ["Bank", f"Shinhan Bank, SWIFT {SWIFT}, A/C {ACCOUNT}"],
    ["Signed by", "Kim Minsu, Export Manager"],
]


def _xlsx() -> bytes:
    from openpyxl import Workbook

    book = Workbook()
    for row in ROWS:
        book.active.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def _png() -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (400, 300), "white").save(buffer, "PNG")
    return buffer.getvalue()


def _file(data: bytes, name: str) -> FileStorage:
    return FileStorage(stream=io.BytesIO(data), filename=name)


def _answer(**changes) -> dict:
    """AI가 돌려주는 모양. 글자 파일이면 가린 번호 표시를 그대로 옮겨 적습니다."""

    answer = {
        "document_type": "offer sheet", "offer_no": "OS-2026-0917", "offer_date": "2026-09-22",
        "validity_date": "2026-10-15", "seller_name": "Forward Cosmetics Co., Ltd.",
        "seller_address": "123 Teheran-ro, Gangnam-gu, Seoul, Korea",
        "buyer_name": "ABC Beauty Inc.", "buyer_address": BUYER_ADDRESS, "buyer_contact": "",
        "incoterms": "FOB", "incoterms_place": "Busan, Korea", "origin_place": "Busan, Korea",
        "destination_place": "Los Angeles, USA", "currency": "USD", "total_amount": "10650.00",
        "payment_terms": "Irrevocable L/C at sight",
        "shipment_time": "Within 30 days after receipt of L/C",
        "packing": "Export standard carton: shampoo 20 PCS/CTN, toothpaste 100 PCS/CTN",
        "bank_info": "Shinhan Bank, SWIFT [SWIFT_1], A/C [ACCOUNT_1]",
        "signed_by": "Kim Minsu, Export Manager",
        "items": [
            {"description": "Hair Shampoo 500ml", "hs_code": "", "quantity": "2000",
             "quantity_unit": "PCS", "unit_price": "3.20", "amount": "6400.00",
             "pieces_per_package": "20", "package_content_unit": "PCS", "package_type": "carton"},
            {"description": "Toothpaste 120g", "hs_code": "", "quantity": "5000",
             "quantity_unit": "PCS", "unit_price": "0.85", "amount": "4250.00",
             "pieces_per_package": "100", "package_content_unit": "PCS", "package_type": "carton"},
        ],
        "uncertain_fields": [],
    }
    answer.update(changes)
    return answer


@pytest.fixture()
def ai():
    """AI를 흉내 냅니다. 무엇을 받았는지(messages) 기록해 둡니다."""

    class Fake:
        answer = _answer()
        sent: list = []

        def __call__(self, messages, schema, **kwargs):
            self.sent.append(messages)
            return {"success": True, "source": "api", "data": json.loads(json.dumps(self.answer))}

    fake = Fake()
    with patch.object(offer.ai_client, "available", return_value=True), \
         patch.object(offer.ai_client, "structured_chat", side_effect=fake):
        yield fake


def _sent_text(fake) -> str:
    return json.dumps(fake.sent, ensure_ascii=False)


# --- 1. 확실한 것만 --------------------------------------------------------------

def test_글자_파일은_확인된_값으로_초안을_만든다(app, ai):
    with app.app_context():
        result = offer.read_offer(_file(_xlsx(), "offer.xlsx"))

    draft = result["draft"]
    assert draft["exporter_name"] == "Forward Cosmetics Co., Ltd."
    assert draft["buyer_name"] == "ABC Beauty Inc."           # 회사명은 저장합니다
    assert draft["incoterms"] == "FOB" and draft["currency"] == "USD"
    # "Busan"은 부산항·부산신항·감천부두 중 어디인지 서류만으로 모릅니다.
    # 부산항(KRPUS)을 먼저 골라 두되, 사람이 확인하기 전에는 초안에 넣지 않습니다.
    origin = next(row for row in result["fields"] if row["key"] == "origin_code")
    assert (origin["value"], origin["status"]) == ("KRPUS", "check")
    assert "origin_code" not in draft
    assert draft["destination_code"] == "USLAX"               # 하나뿐이라 확실합니다
    assert draft["shipment_time"] == "Within 30 days after receipt of L/C"
    first = draft["items"][0]
    # 단가는 오퍼시트에 적힌 그대로, 낱개 기준입니다.
    assert (first["unit_quantity"], first["price_unit"], first["unit_price"], first["amount"]) \
        == (2000, "PCS", 3.2, 6400)
    assert first["quantity"] == 100                            # 2,000 ÷ 20
    assert result["totals"]["match"] is True


def test_원산지를_출발항으로_잘못_옮겨도_가격_조건의_장소로_찾는다(app, ai):
    """실제로 있었던 일입니다. "Origin: Republic of Korea"가 출발항 칸에 들어왔습니다.

    FOB Busan의 Busan은 출발지입니다. 적힌 출발항이 항구가 아니면 그쪽을 봅니다.
    """

    ai.answer = _answer(origin_place="Republic of Korea")
    with app.app_context():
        result = offer.read_offer(_file(_xlsx(), "offer.xlsx"))

    origin = next(row for row in result["fields"] if row["key"] == "origin_code")
    assert origin["value"] == "KRPUS"


def test_CIF의_장소는_도착지로_본다(app, ai):
    ai.answer = _answer(incoterms="CIF", incoterms_place="Los Angeles, USA",
                        origin_place="", destination_place="")
    with app.app_context():
        result = offer.read_offer(_file(_xlsx(), "offer.xlsx"))

    rows = {row["key"]: row for row in result["fields"]}
    assert rows["destination_code"]["value"] == "USLAX"
    assert rows["origin_code"]["status"] == "missing"          # 출발지는 적혀 있지 않습니다


def test_원문에_없는_글자는_확인을_받는다(app, ai):
    """AI가 지어낸 이름은 원문 대조에서 걸립니다."""

    ai.answer = _answer(seller_name="Forward Global Trading Co.")
    with app.app_context():
        result = offer.read_offer(_file(_xlsx(), "offer.xlsx"))

    row = next(row for row in result["fields"] if row["key"] == "exporter_name")
    assert row["status"] == "check"
    assert "exporter_name" not in result["draft"]


def test_수량_곱하기_단가가_틀리면_품목을_넣지_않는다(app, ai):
    items = _answer()["items"]
    items[0]["amount"] = "6500.00"
    ai.answer = _answer(items=items, total_amount="10750.00")
    with app.app_context():
        result = offer.read_offer(_file(_xlsx(), "offer.xlsx"))

    bad = result["items"][0]
    assert bad["status"] == "missing"
    assert any("6,400.00" in problem for problem in bad["problems"])
    assert [line["product_description"] for line in result["draft"]["items"]] == ["Toothpaste 120g"]


def test_모르는_단위면_단가를_받지_않는다(app, ai):
    items = _answer()["items"]
    items[0]["quantity_unit"] = "BAGGIES"
    ai.answer = _answer(items=items)
    with app.app_context():
        result = offer.read_offer(_file(_xlsx(), "offer.xlsx"))

    assert result["items"][0]["status"] == "missing"


def test_총액이_품목_합과_다르면_모든_줄을_확인받는다(app, ai):
    """합이 안 맞으면 어느 줄이 빠졌는지 모릅니다."""

    ai.answer = _answer(total_amount="12000.00")
    with app.app_context():
        result = offer.read_offer(_file(_xlsx(), "offer.xlsx"))

    assert result["totals"]["match"] is False
    assert all(item["status"] == "check" for item in result["items"])
    assert result["draft"]["items"] == []


def test_나누어떨어지지_않는_포장은_포장명세서로_넘긴다(app, ai):
    """단가는 받되, 상자 수는 짐작하지 않습니다."""

    items = _answer()["items"]
    items[0].update(quantity="2010", amount="6432.00")
    ai.answer = _answer(items=items, total_amount="10682.00")
    with app.app_context():
        result = offer.read_offer(_file(_xlsx(), "offer.xlsx"))

    line = result["draft"]["items"][0]
    assert line["unit_price"] == 3.2 and "quantity" not in line
    assert any("포장명세서" in note for note in result["notes"])


# --- 2. 사진 ---------------------------------------------------------------------

def test_사진에서_읽은_글자는_모두_확인을_받는다(app, ai):
    ai.answer = _answer(bank_info=f"Shinhan Bank, SWIFT {SWIFT}, A/C {ACCOUNT}")
    with app.app_context():
        result = offer.read_offer(_file(_png(), "scan.png"))

    assert result["source"]["mode"] == "image"
    text_rows = [row for row in result["fields"]
                 if row["key"] in ("po_no", "exporter_name", "buyer_name", "payment_terms")]
    assert all(row["status"] == "check" for row in text_rows)
    # 숫자는 계산이 맞아도 품명은 대조할 원문이 없어 확인을 받습니다.
    assert all(item["status"] == "check" for item in result["items"])
    assert result["draft"]["items"] == []
    # 사진은 번호를 지운 그림을 보냈고, 그 그림을 이용자에게도 보여 줍니다.
    assert result["source"]["sent_images"][0].startswith("data:image/png")
    # 지운 번호는 되살리지 않습니다. 은행 정보는 이용자가 직접 적습니다.
    bank = next(row for row in result["fields"] if row["key"] == "bank_info")
    assert bank["status"] == "missing" and "bank_info" not in result["private"]


def test_OCR이_없으면_사진을_받지_않는다(app, ai, monkeypatch):
    """번호를 지우지 못한 사진을 보내느니 받지 않습니다."""

    from app.processors import bank_redaction

    monkeypatch.setattr(bank_redaction, "ocr_available", lambda: False)
    with app.app_context(), pytest.raises(ServiceError) as caught:
        offer.read_offer(_file(_png(), "scan.png"))

    assert "엑셀" in str(caught.value)
    assert ai.sent == []                                    # AI에는 아무것도 가지 않았습니다


def test_가격_조건은_장소와_함께_저장하고_서류에_찍는다(app, ai):
    with app.app_context():
        result = offer.read_offer(_file(_xlsx(), "offer.xlsx"))
        from app.services import draft_document_service as drafts
        data = drafts.render("proforma_invoice", result["draft"])["data"]

    assert result["draft"]["incoterms"] == "FOB"
    assert result["draft"]["incoterms_place"] == "Busan, Korea"
    assert data["incoterms"] == "FOB Busan, Korea"


def test_AI가_확실하지_않다고_한_칸은_직접_입력하게_한다(app, ai):
    ai.answer = _answer(offer_no="", uncertain_fields=["offer_no"])
    with app.app_context():
        result = offer.read_offer(_file(_xlsx(), "offer.xlsx"))

    row = next(row for row in result["fields"] if row["key"] == "po_no")
    assert row["status"] == "missing" and "직접 입력" in row["note"]


def test_아무것도_못_읽으면_직접_입력하라고_한다(app, ai):
    empty = {key: ([] if isinstance(value, list) else "") for key, value in _answer().items()}
    ai.answer = empty
    with app.app_context(), pytest.raises(ServiceError) as caught:
        offer.read_offer(_file(_xlsx(), "offer.xlsx"))

    assert "직접 입력" in str(caught.value)


def test_AI_키가_없으면_직접_입력하라고_한다(app):
    with app.app_context(), patch.object(offer.ai_client, "available", return_value=False), \
            pytest.raises(ServiceError) as caught:
        offer.read_offer(_file(_xlsx(), "offer.xlsx"))

    assert "직접 입력" in str(caught.value)


def test_예전_엑셀은_새_형식으로_저장해_달라고_한다(app):
    with pytest.raises(ValidationError) as caught:
        offer.accept(_file(b"old", "offer.xls"))

    assert ".xlsx" in str(caught.value)


# --- 3·4. 은행·바이어 정보 ---------------------------------------------------------

def test_계좌번호와_SWIFT는_AI에게_보내기_전에_가린다(app, ai):
    with app.app_context():
        result = offer.read_offer(_file(_xlsx(), "offer.xlsx"))

    sent = _sent_text(ai)
    assert ACCOUNT not in sent and SWIFT not in sent
    assert "[ACCOUNT_1]" in sent
    # 돌아온 뒤에는 제자리에 되돌려 이용자에게 줍니다. (PDF에 들어가야 하니까요)
    assert ACCOUNT in result["private"]["bank_info"]
    assert SWIFT in result["private"]["bank_info"]


def test_은행과_바이어_주소는_서버에_남지_않는다(app, ai, _isolated_offer_drafts):
    with app.app_context():
        result = offer.read_offer(_file(_xlsx(), "offer.xlsx"))

    stored = "".join(path.read_text(encoding="utf-8")
                     for path in _isolated_offer_drafts.glob("*.json"))
    assert stored                                   # 저장은 했고
    assert ACCOUNT not in stored and SWIFT not in stored
    assert "Wilshire" not in stored
    assert "ABC Beauty Inc." in stored              # 회사명은 남깁니다
    assert "bank_info" not in result["draft"] and "buyer_address" not in result["draft"]


def test_원본_파일은_디스크에_쓰지_않는다(app, ai, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    before = set(tmp_path.rglob("*"))
    with app.app_context():
        offer.read_offer(_file(_xlsx(), "offer.xlsx"))

    written = {path for path in set(tmp_path.rglob("*")) - before if path.is_file()}
    # 생기는 것은 읽은 값을 둔 json뿐입니다. 올린 파일(xlsx)은 없습니다.
    assert not any(path.suffix == ".xlsx" for path in written)


def test_사람이_보낸_은행_정보도_저장하지_않는다(app, ai, _isolated_offer_drafts):
    with app.app_context():
        token = offer.read_offer(_file(_xlsx(), "offer.xlsx"))["token"]
        result = offer.confirm(token, {"bank_info": f"A/C {ACCOUNT}", "lc_no": "x"})

    stored = "".join(path.read_text(encoding="utf-8")
                     for path in _isolated_offer_drafts.glob("*.json"))
    assert ACCOUNT not in stored
    assert "bank_info" not in result["draft"]


@pytest.mark.parametrize("text, hidden", [
    ("A/C No. 100-200-300400", "100-200-300400"),
    ("Account Number: 1002003004005", "1002003004005"),
    ("SWIFT CODE: SHBKKRSE", "SHBKKRSE"),
    ("BIC: CZNBKRSEXXX", "CZNBKRSEXXX"),
    ("IBAN DE89370400440532013000", "DE89370400440532013000"),
    ("계좌번호: 110-123-456789", "110-123-456789"),
])
def test_이름표가_붙은_번호를_가린다(text, hidden):
    clean, secrets = offer.redact(text)

    assert hidden not in clean
    assert hidden in secrets.values()


def test_번호가_아닌_글자는_가리지_않는다():
    text = "PROFORMA INVOICE Total 10,650.00 Tel 02-1234-5678"
    assert offer.redact(text)[0] == text


def test_미리보기는_은행과_바이어를_전부_덮는다(app):
    from app.processors import document_form
    from app.services import draft_document_service as drafts

    data = {"bank_info": f"A/C {ACCOUNT}", "consignee": "ABC Beauty Inc.",
            "consignee_address": BUYER_ADDRESS, "exporter": "Forward", "lc_no": "", "items": []}
    shown = drafts._mark_for_preview(data, masked=True, hints=True)

    for name in ("bank_info", "consignee", "consignee_address"):
        assert shown[name] == document_form.MASKED            # 끝자리도 안 보입니다
    assert shown["exporter"] == "Forward"
    assert shown["lc_no"].endswith(drafts.DOCUMENT_HINT)      # 빈 칸은 어디서 채우는지


def test_PDF에는_원래_값이_들어간다(app):
    """가리는 것은 화면뿐입니다. 결제 계좌가 PDF에서 빠지면 서류가 쓸모없습니다."""

    from app.services import draft_document_service as drafts

    draft = {"exporter_name": "Forward", "buyer_name": "ABC Beauty Inc.",
             "bank_info": f"A/C {ACCOUNT}", "currency": "USD",
             "items": [{"product_description": "Shampoo", "unit_quantity": 2000,
                        "price_unit": "PCS", "unit_price": 3.2, "amount": 6400}]}
    with app.app_context():
        data = drafts.render("proforma_invoice", draft)["data"]

    assert data["bank_info"] == f"A/C {ACCOUNT}"


# --- 화면 창구 --------------------------------------------------------------------

def test_올리면_세_장을_가린_채로_그려_준다(app, client, ai):
    response = client.post("/api/offer-sheet", data={"file": (io.BytesIO(_xlsx()), "offer.xlsx")},
                           content_type="multipart/form-data")

    body = response.get_json()
    assert body["success"] is True
    kinds = [row["kind"] for row in body["data"]["documents"]]
    assert kinds == ["proforma_invoice", "commercial_invoice", "packing_list_std"]
    assert all(row.get("preview", "").startswith("data:image/png") for row in body["data"]["documents"])
    # 은행 정보는 브라우저에만 돌려줍니다.
    assert ACCOUNT in body["data"]["private"]["bank_info"]


def test_운송_계획_화면이_이어_쓸_값을_꺼낸다(app, client, ai):
    client.post("/api/offer-sheet", data={"file": (io.BytesIO(_xlsx()), "offer.xlsx")},
                content_type="multipart/form-data")

    body = client.get("/api/offer-draft").get_json()
    assert body["success"] is True
    assert body["data"]["draft"]["buyer_name"] == "ABC Beauty Inc."
    assert ACCOUNT not in json.dumps(body)


def test_확인하면_사람이_적은_값으로_다시_그린다(app, client, ai):
    token = client.post("/api/offer-sheet", data={"file": (io.BytesIO(_png()), "scan.png")},
                        content_type="multipart/form-data").get_json()["data"]["token"]

    body = client.post("/api/offer-sheet/confirm", json={
        "token": token,
        "values": {"exporter_name": "Forward Cosmetics Co., Ltd.", "incoterms": "FOB"},
        "items": [{"product_description": "Hair Shampoo 500ml", "unit_quantity": 2000,
                   "price_unit": "PCS", "unit_price": 3.2, "amount": 6400}],
        "private": {"bank_info": f"A/C {ACCOUNT}"},
    }).get_json()

    assert body["success"] is True
    assert body["data"]["draft"]["exporter_name"] == "Forward Cosmetics Co., Ltd."
    assert body["data"]["documents"][0]["preview"].startswith("data:image/png")


def test_확인할_때도_금액이_틀리면_받지_않는다(app, client, ai):
    token = client.post("/api/offer-sheet", data={"file": (io.BytesIO(_png()), "scan.png")},
                        content_type="multipart/form-data").get_json()["data"]["token"]

    body = client.post("/api/offer-sheet/confirm", json={
        "token": token,
        "items": [{"product_description": "Hair Shampoo", "unit_quantity": 2000,
                   "price_unit": "PCS", "unit_price": 3.2, "amount": 6500}]}).get_json()

    assert body["data"]["draft"]["items"] == []
    assert any("맞지 않습니다" in note for note in body["data"]["notes"])


def test_이상한_표는_파일을_열지_않는다(app):
    with app.app_context():
        assert draft_store.load("../../config") is None
        assert draft_store.load("") is None
