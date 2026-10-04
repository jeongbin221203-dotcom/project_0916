"""사용성 점검 3회차(2026-10-04) — 실서버·Edge 로 써 보며 나온 것.

섞인 PDF(글자 6쪽 + 스캔 2쪽)의 스캔 쪽을 말없이 버린 것이 가장 컸습니다. 나머지는 같은
말을 두 번 하거나, 알릴 말을 화면 밖에 두거나, 키보드가 창 밖으로 새는 것입니다.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from app import create_app, db
from app.processors import contract_clauses
from app.services import contract_clause_service as service
from config import TestConfig

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


def _scan_page(doc, lines: str) -> None:
    from PIL import Image, ImageDraw, ImageFont

    try:
        font = ImageFont.truetype("arial.ttf", 34)
    except OSError:
        pytest.skip("시험용 글꼴이 없는 환경")
    image = Image.new("RGB", (1700, 600), "white")
    ImageDraw.Draw(image).text((60, 80), lines, fill="black", font=font, spacing=18)
    png = io.BytesIO()
    image.save(png, format="PNG")
    page = doc.new_page()
    page.insert_image(page.rect, stream=png.getvalue())


def test_글자_쪽과_스캔_쪽이_섞인_PDF_는_스캔_쪽도_읽는다():
    from app.processors import bank_redaction, ocr

    if not (ocr.available() and bank_redaction.ocr_available()):
        pytest.skip("OCR 이 설치되지 않은 환경")
    import pymupdf

    doc = pymupdf.open()
    for n in range(1, 4):
        doc.new_page().insert_text((50, 72), f"SALES CONTRACT page {n}\nThe Seller shall deliver the Goods "
                                             f"as described in Annex {n} of this Contract.", fontsize=10)
    _scan_page(doc, "The courts of Shanghai shall have\nexclusive jurisdiction.")
    text, notes = service.read_contract("mixed.pdf", doc.tobytes())
    assert "page 3" in text and "exclusive" in text.lower()
    assert any("4쪽은 스캔" in note for note in notes)


def test_사진은_스캔본이라고_하지_않는다():
    source = (Path(service.__file__)).read_text(encoding="utf-8")
    assert '"스캔본" if name.endswith(".pdf") else "사진"' in source


def _chat(question):
    app = create_app(TestConfig)
    with app.app_context():
        db.create_all()
        try:
            return app.test_client().post("/api/support-chat", json={"question": question}).get_json()
        finally:
            db.session.remove(); db.drop_all()


def test_입력칸이_자르고_공백을_지운_계약서도_판정하지_않는다():
    long = "SALES CONTRACT\n" + ("1. The Seller shall deliver the goods as agreed in Annex 1. " * 40)
    answer = _chat(long[:2000].strip()[:1998])
    assert answer["source"] == "contract"


def test_상담_창의_우리_쪽_줄은_이름표_꼴이다():
    doc = ('본 계약은 주식회사 대한정밀(이하 "을", 매도인)과 VINA TRADING JSC(이하 "갑", 매수인) 사이에 '
           "체결한다. 갑은 언제든지 서면 통지로 이 계약을 해지할 수 있다.")
    text = service.as_text(service.review("수출 계약서\n" + doc, "FOB") | {"summary": ""})
    assert "우리 쪽(매도인·수출자): **을" in text
    assert "을 **을" not in text


def test_근거_끝에_다음_조_번호를_붙이지_않는다():
    doc = ("SALES CONTRACT\n12. GOVERNING LAW This Contract shall be governed by the laws of the State of "
           "California, U.S.A. 13. NOTICES All notices shall be in writing.")
    row = contract_clauses.analyze(doc)["clauses"]["governing_law"]
    assert not row["evidence"].rstrip("…").endswith("13")


def test_독소로_짚은_관할_문장을_직접_확인에_다시_내지_않는다():
    doc = ("SALES CONTRACT\n13. DISPUTE RESOLUTION All disputes arising out of or in connection with this "
           "Contract shall be finally settled by the state and federal courts located in San Francisco, "
           "California, and each party waives any objection to such venue. The parties agree to trial by jury, "
           "and punitive damages may be awarded.")
    result = service.review(doc, "FOB", "US")
    assert "us_jury_punitive" in {row["key"] for row in result["toxic"]}
    assert not [c for c in result["check"] if "San Francisco" in c["sentence"]]


def test_선적_근거는_결제_문장이_아니라_선적_문장이다():
    doc = ("SALES CONTRACT\nPayment: 30% advance, and the balance by T/T within 10 days after shipment. "
           "Shipment shall be made from Busan to Oakland not later than 30 Nov. 2026.")
    row = contract_clauses.analyze(doc)["clauses"]["shipment"]
    assert row["evidence"].startswith("Shipment shall be made")


def test_FOB_점검표에는_DDP_수입자_조항에_도착국_배지를_달지_않는다():
    rows = service.checklist("FOB", country="VN")["toxic"]
    assert not next(row for row in rows if row["key"] == "ddp_no_ior")["for_country"]
    rows = service.checklist("DDP", country="VN")["toxic"]
    assert next(row for row in rows if row["key"] == "ddp_no_ior")["for_country"]


# ── 화면 (JS·CSS) — 글자로 확인합니다 ────────────────────────────────────────
def test_접힌_묶음_안은_Tab_가두기에서_뺀다():
    js = (STATIC / "js" / "contract_modal.js").read_text(encoding="utf-8")
    assert "!folded(el)" in js and 'details:not([open])' in js


def test_Esc_한_번에_상담_창까지_닫지_않는다():
    modal = (STATIC / "js" / "contract_modal.js").read_text(encoding="utf-8")
    chat = (STATIC / "js" / "support_chat.js").read_text(encoding="utf-8")
    assert 'event.key === "Escape") { event.preventDefault()' in modal
    assert "event.defaultPrevented" in chat


def test_차분한_고치는_법과_갑을_경고는_덮이지_않는다():
    css = (STATIC / "css" / "contract.css").read_text(encoding="utf-8")
    assert ".cc_fix.cc_fix_calm" in css and ".cc_side.cc_side_warn" in css


def test_결과_위에_요약을_두고_뺀_조항을_모두_이름으로_알린다():
    js = (STATIC / "js" / "contract_clauses.js").read_text(encoding="utf-8")
    assert 'class="cc_summary"' in js
    assert "이 계약에 해당하지 않아 뺐습니다" in js
    assert "에는 해당하지 않아 고른" in js           # 인코텀즈를 바꿔 빠진 것
    assert "setTimeout" in js and "clearTimeout(slowTimer)" in js
    assert "data-cc-pickmsg" in js


# ── 3회차 마무리 (2026-10-04, '수정하고 다시 확인') ─────────────────────────────
def test_같은_근거_문장은_두_번째부터_앞_조항을_가리킨다():
    doc = ("SALES CONTRACT\nIn case of delay in shipment, the Seller shall pay liquidated damages of 2% of "
           "the contract price per day of delay, without any maximum limit.")
    result = service.review(doc, "FOB")
    same = [row for row in result["toxic"] if row["same_as"]]
    firsts = [row for row in result["toxic"] if not row["same_as"]]
    assert len(result["toxic"]) >= 2 and same and firsts
    assert "조항과 같은 문장" in service.as_text(result | {"summary": ""})


def test_다른_근거_문장은_가리키지_않는다():
    doc = ("SALES CONTRACT\nThe Buyer may set off any amount claimed against any sum payable to the Seller. "
           "This warranty shall survive indefinitely.")
    assert not [row for row in service.review(doc, "FOB")["toxic"] if row["same_as"]]


def test_거래_조건으로_짚은_독소는_까닭을_적는다():
    result = service.review("SALES CONTRACT\nDelivery DDP Sao Paulo.", "DDP", "BR")
    text = service.as_text(result | {"summary": ""})
    assert "까닭: 인코텀즈 DDP" in text


def test_전체_쪽보다_적게_올리면_나머지를_올리라고_한다():
    assert "2쪽이라고" in service._missing_pages("SALES CONTRACT ... Page 1 of 2", 1)


@pytest.mark.parametrize("text,pages", [("Page 1 of 1", 1), ("Page 2 of 2", 2), ("Annex 1. Price list", 1),
                                        ("USD 1/3 of the price", 1)])
def test_쪽을_다_올렸거나_쪽_표시가_없으면_알리지_않는다(text, pages):
    assert service._missing_pages(text, pages) == ""


def test_우리가_공제하는_권리는_바이어_상계가_아니다():
    doc = ("SALES CONTRACT\nThe Seller shall refund the Deposit to the Buyer (subject to the Seller's right to "
           "deduct from the Deposit any then-outstanding amounts owed by the Buyer).")
    assert "buyer_set_off" not in contract_clauses.find_in(doc)


def test_화면은_도착국_이름을_확인시키고_받기_단추를_겹쳐_보이지_않는다():
    js = (STATIC / "js" / "contract_clauses.js").read_text(encoding="utf-8")
    assert "Intl.DisplayNames" in js and "알 수 없는 나라 코드" in js
    assert "IntersectionObserver" in js and "actionsInView" in js
    assert 'textarea[name=text]").value = ""' in js
    assert "조항과 같은 문장" in js
