"""필수·이익 4+6개와 독소 8개 — **걸리면 안 되는 것부터** 봅니다.

2026-10-02 에 조항을 49 -> 67개로 늘렸습니다(필수 14 · 이익 14 · 독소 39).

필수·이익의 오탐은 독소와 **다른 방식으로** 해롭습니다
    독소 오탐: 멀쩡한 조항을 지우라고 합니다
    필수 오탐: **없는데 있다**고 해서, 그 조항 없이 계약하게 만듭니다
  둘 다 나쁩니다. 그래서 '아무 조항도 아닌 글'에서 안 걸리는지 함께 봅니다.

늘리면서 또 걸린 것
    한국어 낱말 순서  "11월 15일**까지** 개설한다" 처럼 기한이 앞에 오는 꼴을
                     놓쳤습니다. 낱말 순서로 놓친 것이 **이번이 세 번째**입니다.
    조사가 끼어듦     "비밀**을** 유지한다" 가 공백만 허용하는 규칙에 안 걸렸습니다.
    주어 위치         "The Seller shall use ... and **shall bear all costs**" 에서
                     주어가 앞에 있어 "seller shall bear" 가 붙어 나오지 않습니다.
    대금 수령 후      "released to the Buyer only **after full payment**" 는
                     좋은 꼴인데 서류 선인도로 짚었습니다.
"""

from __future__ import annotations

import pytest

from app.processors import contract_clauses

H = "SALES CONTRACT\n물품매매계약서\n\n"

NEW_MUST = {"packing", "confidential", "quantity_tol", "amendment"}
NEW_GAIN = {"suspend_delivery", "no_set_off", "claim_period", "lc_deadline",
            "buyer_design_ip", "exit_buyback"}
NEW_TOXIC = {"docs_before_payment", "lc_soft_clause", "payment_retention",
             "buyer_nominated_cost", "one_way_nda", "non_compete_wide",
             "assignment_one_way", "cert_test_cost"}
NEW = NEW_MUST | NEW_GAIN | NEW_TOXIC

NOTHING = [
    ("오퍼시트",
     "OFFER SHEET\nItem: 3-fold umbrella\nQuantity: 1,200 PCS\n"
     "Price: USD 2.40/PC\nPayment: T/T 30 days"),
    ("상업송장",
     "COMMERCIAL INVOICE\nInvoice No. FW-2026-0041\nHS Code: 6601.91\n"
     "Total: USD 2,880.00"),
    ("일반 안내문",
     "제1조 본 계약은 당사자 간의 신의성실에 따라 이행한다. "
     "본 계약의 목적은 양질의 제품을 안정적으로 공급하는 데 있다."),
]

SAFE = [
    ("서류는 은행을 거친다",
     "제6조 선적서류는 신용장 조건에 따라 매입은행을 통하여 제시한다."),
    ("대금 수령 후 서류 인도",
     "Article 6 The original Bill of Lading shall be released to the Buyer only "
     "after full payment has been received."),
    ("제3기관 검사증명서",
     "Article 7 The L/C shall require an inspection certificate issued by SGS."),
    ("유보가 없다",
     "제5조 매수인은 송장 금액 전액을 유보 없이 지급한다."),
    ("은행 보증서로 대신",
     "Article 5 In lieu of retention, the Seller shall provide a performance bond "
     "issued by a first class bank."),
    ("지정하되 비용은 바이어",
     "제7조 포워더는 매수인이 지정하며, 그 비용은 매수인이 부담한다."),
    ("비밀유지가 양쪽 모두",
     "Article 18 Each party shall keep confidential all information received from "
     "the other party."),
    ("비밀유지가 쌍방 (국문)",
     "제18조 양 당사자는 상대방으로부터 받은 정보의 비밀을 유지한다."),
    ("경업금지가 좁다",
     "제19조 매도인은 계약 기간 중 매수인의 판매 지역에서 매수인 모델과 동일한 "
     "제품을 제3자에게 공급하지 아니한다."),
    ("양도가 양쪽 다 제한",
     "Article 20 Neither party may assign this Contract without the prior written "
     "consent of the other party."),
    ("인증비는 바이어가",
     "제21조 수입국 인증에 드는 비용은 매수인이 부담한다."),
    # **쌍방 비밀유지를 두 문장으로 나눠 쓴 꼴.** 실무에서 흔합니다.
    # 가드가 `[^.]` 였을 때는 첫 문장에서 끊겨 **쌍방인데 일방이라고** 짚었습니다.
    ("쌍방 비밀유지 — 두 문장으로 나뉨",
     "Article 18 The Seller shall keep confidential all information received from "
     "the Buyer. The Buyer shall likewise keep confidential all information "
     "received from the Seller."),
    ("쌍방 비밀유지 — 국문 두 문장",
     "제18조 매도인은 비밀을 유지한다. 매수인도 동일하게 기밀을 유지한다."),
    ("쌍방 비밀유지 — 한 문장 안",
     "Article 18 The Seller shall keep confidential information from the Buyer, "
     "and each party shall protect the other's data."),
]

CATCH = [
    # 필수
    ("포장·화인", "packing",
     "5. PACKING AND MARKING The Goods shall be packed in export standard "
     "seaworthy packing and each package shall bear the shipping marks in Annex 2."),
    ("포장·화인 (국문)", "packing",
     "제5조 (포장 및 화인) 물품은 수출 표준 포장으로 하며 화인은 별지에 따른다."),
    # 제목만 있고 다른 단서가 없는 꼴. 규칙이 하나라도 빠지면 여기서 울립니다.
    ("포장 — 제목만", "packing",
     "Article 5 PACKING AND MARKING shall be as agreed between the parties."),
    ("비밀유지", "confidential",
     "Article 18 Each party shall keep confidential all information disclosed by "
     "the other party."),
    ("비밀유지 (국문)", "confidential", "제18조 양 당사자는 비밀을 유지한다."),
    ("수량 과부족", "quantity_tol",
     "Article 2 A tolerance of five percent (5%) more or less in quantity shall "
     "be acceptable."),
    ("수량 과부족 (국문)", "quantity_tol", "제2조 수량의 과부족 5%를 허용한다."),
    ("서면 변경", "amendment",
     "Article 19 No amendment shall be effective unless made in writing and "
     "signed by both parties."),
    ("서면 변경 (국문)", "amendment",
     "제19조 본 계약의 변경은 서면 합의로만 효력이 있다."),
    # 이익
    ("선적 중단권", "suspend_delivery",
     "Article 5 If any payment is overdue by more than fifteen days, the Seller "
     "may suspend further shipments without liability."),
    ("선적 중단권 (국문)", "suspend_delivery",
     "제5조 대금이 연체되면 매도인은 선적을 중단할 수 있다."),
    ("상계 금지", "no_set_off",
     "Article 5 The Buyer shall pay all amounts in full without any set-off, "
     "deduction or withholding."),
    ("상계 금지 (국문)", "no_set_off", "제5조 매수인은 상계 없이 전액을 지급한다."),
    ("클레임 기한", "claim_period",
     "Article 8 Any claim shall be notified in writing within thirty (30) days "
     "after arrival at the port of destination."),
    ("클레임 기한 (국문)", "claim_period",
     "제8조 클레임은 도착 후 30일 이내에 서면으로 통지하여야 한다."),
    ("L/C 개설 기한", "lc_deadline",
     "Article 5 The Buyer shall open an irrevocable Letter of Credit by 15 "
     "November 2026."),
    ("L/C 개설 기한 (국문)", "lc_deadline",
     "제5조 신용장은 2026년 11월 15일까지 개설한다."),
    ("바이어 도면 보증", "buyer_design_ip",
     "Article 9 The Buyer warrants that the designs and trademarks supplied by it "
     "do not infringe any third party rights."),
    ("해지 시 재고 인수", "exit_buyback",
     "Article 17 Upon termination, the Buyer shall purchase all finished goods "
     "and work in progress at the contract price."),
    ("해지 시 재고 인수 (국문)", "exit_buyback",
     "제17조 해지 시 잔여 재고는 매수인이 인수한다."),
    # 독소
    ("서류 원본 선인도", "docs_before_payment",
     "Article 6 The Seller shall send the original Bill of Lading directly to the "
     "Buyer by courier immediately upon shipment."),
    ("서류 원본 선인도 (국문)", "docs_before_payment",
     "제6조 선하증권 원본은 매수인에게 직접 송부한다."),
    ("L/C 소프트 조항", "lc_soft_clause",
     "Article 7 Inspection certificate signed by the Buyer's representative, whose "
     "specimen signature is held by the issuing bank."),
    ("L/C 소프트 조항 (선박 지정)", "lc_soft_clause",
     "Article 7 Shipment to be effected only upon the Buyer's written nomination "
     "of the vessel."),
    ("대금 유보", "payment_retention",
     "Article 5 Ten percent (10%) of the invoice value shall be retained by the "
     "Buyer as a performance guarantee for twelve months."),
    ("대금 유보 (국문)", "payment_retention",
     "제5조 송장 금액의 10%를 하자보증금으로 12개월간 유보한다."),
    ("바이어 지정·우리 부담", "buyer_nominated_cost",
     "Article 7 The Seller shall use the forwarder nominated by the Buyer and "
     "shall bear all costs thereof."),
    ("바이어 지정·우리 부담 (국문)", "buyer_nominated_cost",
     "제7조 매수인이 지정한 포워더를 사용하며 그 비용은 매도인이 부담한다."),
    ("일방 비밀유지", "one_way_nda",
     "Article 18 The Seller shall keep confidential all information received from "
     "the Buyer and shall not disclose it to any third party."),
    ("일방 비밀유지 (국문)", "one_way_nda",
     "제18조 매도인은 매수인으로부터 받은 정보의 비밀을 유지한다."),
    ("넓은 경업금지", "non_compete_wide",
     "Article 19 The Seller shall not manufacture or sell any similar or competing "
     "products to any other party worldwide."),
    ("일방 양도", "assignment_one_way",
     "Article 20 The Buyer may assign this Contract to any third party without the "
     "Seller's consent. The Seller shall not assign this Contract."),
    ("인증·시험비 전가", "cert_test_cost",
     "Article 21 All costs of certification, testing and factory audits shall be "
     "borne by the Seller."),
    ("인증비 전가 (국문)", "cert_test_cost",
     "제21조 인증 및 시험 비용은 매도인이 부담한다."),
]


@pytest.mark.parametrize("label,body", NOTHING, ids=[row[0] for row in NOTHING])
def test_아무_조항도_아닌_글에서는_걸리지_않는다(label, body):
    """오퍼시트·송장·일반 안내문. 필수조항이 '있다'고 하면 그 조항 없이 계약합니다."""

    hits = contract_clauses.find_in(H + body) & NEW
    assert not hits, f"{label}: 오탐 {sorted(hits)}"


@pytest.mark.parametrize("label,body", SAFE, ids=[row[0] for row in SAFE])
def test_좋은_꼴은_독소로_짚지_않는다(label, body):
    """새 독소조항의 '제대로 고친 모습'. 짚으면 고친 조항을 다시 지우게 됩니다."""

    hits = contract_clauses.find_in(H + body) & NEW_TOXIC
    assert not hits, f"{label}: 오탐 {sorted(hits)}"


@pytest.mark.parametrize("label,want,body", CATCH, ids=[row[0] for row in CATCH])
def test_조항을_찾는다(label, want, body):
    hits = contract_clauses.find_in(H + body)
    assert want in hits, f"{label}: {want} 를 놓쳤습니다. 짚은 것 {sorted(hits & NEW)}"


def test_묶음별_개수():
    """늘린 뒤의 수를 적어 둡니다. 줄어들면 누가 지운 것입니다."""

    import collections

    counts = collections.Counter(row["category"] for row in contract_clauses.CLAUSES)
    assert counts["must"] >= 14, counts
    assert counts["gain"] >= 14, counts
    assert counts["toxic"] >= 39, counts
    assert len(contract_clauses.CLAUSES) >= 67


def test_모든_조항에_필요한_칸이_있다():
    """빈 칸이 있으면 화면에 빈 줄이 뜹니다. 넣을 때 빠뜨리기 쉬운 자리입니다."""

    for row in contract_clauses.CLAUSES:
        for field in ("key", "title", "category", "why", "risk", "text_ko", "detect"):
            assert row.get(field), f"{row.get('key')}: {field} 가 비어 있습니다"
        assert row["category"] in contract_clauses.CATEGORIES, row["key"]
        # 독소조항은 **고치는 법**이 있어야 합니다. 지우라고만 하면 쓸모가 없습니다.
        if row["category"] == "toxic":
            assert row["fix"], f"{row['key']}: 독소조항인데 fix 가 비어 있습니다"


def test_열쇠가_겹치지_않는다():
    keys = [row["key"] for row in contract_clauses.CLAUSES]
    assert len(keys) == len(set(keys)), "겹치는 열쇠가 있습니다"
