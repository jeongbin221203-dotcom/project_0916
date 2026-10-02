"""영문·국문 병기 계약서 · 뒤집는 조항 · 계약서가 아닌 실무 문서 · 실제 창구.

왜 이 파일이 있나 (2026-10-02)
  한국 수출자의 계약서는 대부분 **영문과 국문을 나란히** 적습니다. 같은 보호
  조항을 두 언어로 한 번씩 적으니, 한쪽 언어에만 있던 빈틈이 드러납니다.
  실제로 좋은 조항만 있는 병기 계약서에서 독소 셋을 짚었습니다.

      buyer_set_off  "The Buyer **shall not** set off any claim"   (영문 부정)
      evergreen      "shall **not** be automatically renewed"      (영문 부정)
      foreign_forum  "**서울중앙지방법원**을 전속관할로 한다"        (한국 법원이 앞)

  병기 때문이 아니라 **각 언어의 빈틈**이었습니다. 앞의 둘은 예문에 부정말이 든
  탓에 통짜 부정 가드를 떼었던 조항이고, 셋째는 한국어 낱말 순서로 놓친
  **일곱 번째** 사례입니다.

함께 보는 것
  뒤집는 조항     제11조에서 책임 한도를 걸고 제28조에서 "제11조에도 불구하고"로
                  푸는 꼴. 한도가 '있다'고만 말하면 사용자는 안심합니다.
  실무 문서       메일·송장·신용장 원문·견적·기사. 여기서 독소가 뜨면 사용자가
                  올리는 아무 서류마다 경고가 뜹니다.
  실제 창구       화면이 쓰는 /contract/review 로 글과 파일 둘 다.
"""

from __future__ import annotations

import io

import pytest

from app import create_app
from app.extensions import db
from app.processors import contract_clauses
from config import TestConfig

TOXIC = {row["key"] for row in contract_clauses.CLAUSES if row["category"] == "toxic"}

# 좋은 조항만 있는 병기 계약서. 같은 뜻을 두 언어로 한 번씩.
BILINGUAL_SAFE = """SALES CONTRACT / 물품매매계약서

Article 12 (Set-off) The Buyer shall not set off any claim against the price. | 제12조 (상계) 매수인은 어떠한 채권으로도 대금과 상계할 수 없다.
Article 16 (Jurisdiction) The courts of Seoul shall have exclusive jurisdiction. | 제16조 (관할) 서울중앙지방법원을 전속관할로 한다.
Article 3 (Term) This Contract shall not be automatically renewed. | 제3조 (기간) 본 계약은 자동으로 연장되지 아니한다.
Article 9 (Tooling) All moulds shall remain the property of the Seller. | 제9조 (금형) 금형의 소유권은 매도인에게 있다.
Article 11 (Liability) The Seller's liability shall not exceed the invoice value. | 제11조 (책임) 매도인의 책임은 송장 금액을 초과하지 아니한다.
"""

BILINGUAL_TOXIC = [
    ("buyer_set_off",
     "Article 12 The Buyer may set off any claim it may have against the Seller. | "
     "제12조 매수인은 매도인에 대한 어떠한 채권으로도 대금과 상계할 수 있다."),
    ("evergreen",
     "Article 3 This Contract renews for successive annual terms. | "
     "제3조 본 계약은 해지 통보가 없는 한 자동으로 연장된다."),
    ("ip_assignment",
     "Article 9 All moulds and tooling shall vest in the Buyer. | "
     "제9조 금형과 치공구는 매수인에게 귀속한다."),
    ("docs_before_payment",
     "Article 6 The Seller shall send the original Bill of Lading directly to the "
     "Buyer. | 제6조 매도인은 선하증권 원본을 매수인에게 직접 송부한다."),
    # 한국 법원이 아닌 곳은 그대로 짚어야 합니다 — 좁힌 가드가 넘치면 안 됩니다.
    ("foreign_forum",
     "Article 16 The courts of New York shall have exclusive jurisdiction. | "
     "제16조 뉴욕주 법원을 전속관할로 한다."),
]

# 한쪽 언어만 — 어느 쪽 빈틈인지 가려 둡니다.
ONE_LANGUAGE_SAFE = [
    ("영문 — 상계를 못 한다", "Article 12 The Buyer shall not set off any claim "
     "against the price."),
    ("영문 — 상계 없음", "Article 12 There shall be no set-off against the price."),
    ("영문 — 자동연장 안 됨", "Article 3 This Contract shall not be automatically "
     "renewed."),
    ("국문 — 한국 법원이 앞", "제16조 서울중앙지방법원을 전속관할로 한다."),
    ("국문 — 중재원이 앞", "제16조 대한상사중재원의 중재를 전속으로 한다."),
]

OVERRIDES = [
    ("영문", """SALES CONTRACT
Article 11 The Seller's liability shall not exceed the invoice value.
Article 28 Notwithstanding Article 11, the Seller shall indemnify the Buyer for any
and all losses, damages and expenses of whatever nature, without limitation.
"""),
    ("국문", """물품매매계약서
제11조 매도인의 손해배상책임은 송장 금액을 초과하지 아니한다.
제28조 제11조에도 불구하고 매도인은 매수인에게 발생한 모든 손해를 제한 없이 배상한다.
"""),
]

NOT_CONTRACTS = [
    ("바이어 메일",
     "Dear Mr. Kim,\nThank you for your offer. We would like to order 1,200 pcs. "
     "Please send the original B/L by courier once you receive our T/T payment. "
     "We may cancel the order if the samples fail. Best regards, John"),
    ("상업송장",
     "COMMERCIAL INVOICE\nInvoice No. FW-0041  Date: 2026-10-02\nShipper: FORWARDUS\n"
     "Consignee: Buyer GmbH\nTerms: FOB Busan, Incoterms 2020\nPayment: T/T 30 days\n"
     "Description: 3-fold umbrella  HS 6601.91  1,200 PCS  USD 2,880.00"),
    ("신용장 원문",
     "46A DOCUMENTS REQUIRED: + FULL SET OF CLEAN ON BOARD OCEAN BILLS OF LADING "
     "MADE OUT TO ORDER + COMMERCIAL INVOICE IN 3 COPIES + PACKING LIST\n"
     "47A ADDITIONAL CONDITIONS: ALL DOCUMENTS MUST INDICATE L/C NO."),
    ("견적 회신",
     "QUOTATION\nValidity: 30 days\nPrice: USD 2.40/PC FOB Busan\nMOQ: 1,000 PCS\n"
     "Lead time: 45 days after deposit\nWarranty: 12 months"),
    ("뉴스 기사",
     "Seoul, Oct 2 - Korean exporters face higher tariffs as the US raised customs "
     "duties on steel. Analysts said suppliers may need to absorb part of the increase."),
    ("국문 업무 메일",
     "안녕하세요. 지난번 주문 건 관련하여 선적 전 검사 일정이 잡혔습니다. "
     "검사 비용은 저희가 부담하겠습니다. 대금은 선적 후 30일 이내 송금 예정입니다."),
]


def _toxic(text: str) -> set[str]:
    return contract_clauses.find_in(text) & TOXIC


def test_좋은_조항만_있는_병기_계약서는_독소가_없다():
    found = _toxic(BILINGUAL_SAFE)
    assert not found, f"병기 계약서에서 독소 {sorted(found)} 를 짚었습니다"


@pytest.mark.parametrize("key,line", BILINGUAL_TOXIC, ids=[r[0] for r in BILINGUAL_TOXIC])
def test_병기_계약서의_독소조항을_짚는다(key, line):
    assert key in _toxic("SALES CONTRACT\n" + line)


@pytest.mark.parametrize("label,line", ONE_LANGUAGE_SAFE,
                         ids=[r[0] for r in ONE_LANGUAGE_SAFE])
def test_한쪽_언어의_보호_조항도_독소가_아니다(label, line):
    found = _toxic("SALES CONTRACT\n" + line)
    assert not found, f"{label}: {sorted(found)}"


def test_제목과_본문이_나뉜_병기_단락():
    """마침표 없는 제목 줄 뒤에 본문이 오는 꼴. 제목의 SET-OFF 와 본문이 이어집니다."""

    doc = ("SALES CONTRACT\n\nARTICLE 12 SET-OFF\n"
           "The Buyer shall not set off any claim against the price\n\n"
           "제12조 상계\n매수인은 대금과 상계할 수 없다\n")
    assert not _toxic(doc)


@pytest.mark.parametrize("label,doc", OVERRIDES, ids=[r[0] for r in OVERRIDES])
def test_불구하고로_한도를_풀면_무제한을_짚는다(label, doc):
    """앞에서 한도를 걸고 뒤에서 푸는 꼴. 한도가 '있다'고만 말하면 안 됩니다."""

    assert "unlimited_damages" in contract_clauses.find_in(doc)


@pytest.mark.parametrize("label,doc", NOT_CONTRACTS, ids=[r[0] for r in NOT_CONTRACTS])
def test_계약서가_아닌_실무_문서에서_독소가_뜨지_않는다(label, doc):
    """여기서 뜨면 사용자가 올리는 아무 서류마다 경고가 뜹니다."""

    found = _toxic(doc)
    assert not found, f"{label}: {sorted(found)}"


@pytest.fixture()
def client():
    flask_app = create_app(TestConfig)
    with flask_app.app_context():
        db.create_all()
        yield flask_app.test_client()
        db.session.remove()
        db.drop_all()


DOC = ("SALES CONTRACT\n물품매매계약서\n\n"
       "Article 6 The Seller shall send the original Bill of Lading directly to the "
       "Buyer by courier immediately after shipment.\n"
       "Article 2 Delivery shall be DDP the Buyer's warehouse with the Seller "
       "responsible for import clearance and duties.\n")


def test_실제_창구에서_글과_파일이_같은_결과를_낸다(client):
    """화면은 글을 붙여 넣기도 하고 파일을 올리기도 합니다. 결과가 달라지면 안 됩니다."""

    by_text = client.post("/contract/review",
                          json={"text": DOC, "incoterms": "DDP", "country": "BR"})
    by_file = client.post("/contract/review",
                          data={"incoterms": "DDP", "country": "BR",
                                "file": (io.BytesIO(DOC.encode("utf-8")), "contract.txt")},
                          content_type="multipart/form-data")
    assert by_text.status_code == by_file.status_code == 200
    keys_text = {row["key"] for row in by_text.get_json()["data"]["toxic"]}
    keys_file = {row["key"] for row in by_file.get_json()["data"]["toxic"]}
    assert {"docs_before_payment", "ddp_no_ior"} <= keys_text
    assert keys_text == keys_file


def test_실행_파일은_받지_않는다(client):
    got = client.post("/contract/review",
                      data={"file": (io.BytesIO(b"x"), "contract.exe")},
                      content_type="multipart/form-data")
    assert got.status_code == 400
