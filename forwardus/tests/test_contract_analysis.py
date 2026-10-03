"""필수·이익조항을 '있다'고 보기 전에 한 번 더 — 있음 / 적혀 있으나 부족 / 없음.

왜 이 파일이 있나 (2026-10-02)
  독소조항에는 부정·방향 가드를 달아 왔는데, 필수·이익조항은 **낱말만** 봤습니다.
  확인해 보니 언급만 있는 문장 11개 중 10개, 반대 뜻 문장 13개 중 13개를
  '있다'고 했습니다.

      "Incoterms to be agreed later"        → 가격조건 있음
      "There shall be no price adjustment"  → 가격조정 있음
      "All moulds shall vest in the Buyer"  → 금형 보호 있음
      "PAYMENT: BY T/T BEFORE SHIPMENT"     → 선적조건 있음 (실물 오퍼 시트)

  '있다'고 하면 사용자는 안심하고 넘어갑니다. 그래서 셋째 판정 'weak'(적혀
  있으나 제 구실을 못 함)을 두고, 까닭과 **근거 문장**을 함께 냅니다.

  거꾸로 정상 조항이 weak 으로 떨어지면 이미 쓴 사람에게 고치라고 합니다.
  그래서 정상 조항도 같은 수만큼 지킵니다.
"""

from __future__ import annotations

import pytest

from app.processors import contract_clauses
from app.services import contract_clause_service

H = "SALES CONTRACT\n"

NOT_PRESENT = [
    ("shipment", "Payment: by T/T before shipment."),
    ("shipment", "Payment by T/T 30% deposit before shipment."),
    ("inspection", "Any claim shall be made within 10 days after inspection."),
    ("payment", "Payment terms to be advised."),
    ("incoterms", "Incoterms to be agreed later."),
    ("arbitration", "The parties may discuss arbitration later, TBD."),
    ("governing_law", "Governing law: to be agreed."),
    ("force_majeure", "Force majeure: to be agreed."),
    ("lc_deadline", "The Seller shall open a letter of credit in favor of its supplier."),
    ("lc_deadline", "The Buyer shall establish a letter of credit for USD 45,000 in favor of "
                    "the Seller before shipment."),
    ("ip", "All moulds, tooling and drawings shall vest in the Buyer."),
    ("liability_cap", "The Seller's total liability shall be unlimited."),
    ("late_interest", "No interest shall be payable on overdue amounts."),
    ("price_adjust", "There shall be no price adjustment during the term."),
    ("price_adjust", "Prices are fixed and shall not be adjusted for any reason."),
    ("min_order", "There is no minimum order quantity."),
    ("title", "Title passes to the Buyer upon shipment and no retention of title applies."),
    ("quantity_tol", "No more or less tolerance is allowed."),
    ("confidential", "The Seller shall keep confidential all information; the Buyer has no "
                     "confidentiality obligation."),
    ("arbitration", "No arbitration; disputes go to the courts of New York."),
    ("force_majeure", "The Seller shall not be excused by force majeure."),
    ("price_adjust", "가격 조정은 없다."),
    ("governing_law", "준거법은 추후 협의한다."),
]

PRESENT = [
    ("force_majeure", "The Seller shall not be liable for any delay caused by force majeure."),
    ("force_majeure", "Neither party shall be liable for failure caused by force majeure."),
    ("shipment", "Partial shipments are not allowed. Latest date of shipment: 30 June 2027."),
    ("shipment", "No partial shipment or transhipment is allowed."),
    ("shipment", "Shipment within 60 days after receipt of the L/C."),
    ("shipment", "제5조 선적은 2027년 3월 15일까지 한다."),
    ("inspection", "Inspection shall be carried out by SGS before shipment and shall be final."),
    ("inspection", "제6조 선적 전 검사는 공인 검사기관이 한다."),
    ("lc_deadline", "The Buyer shall open the L/C within 15 days after the contract date."),
    ("lc_deadline", "The Buyer shall establish an irrevocable L/C no later than 30 June 2027."),
    ("price_adjust", "Prices shall be adjusted if raw material costs rise by more than 5%."),
    ("late_interest", "Interest at 1% per month shall accrue on overdue amounts."),
    ("ip", "All moulds and drawings shall remain the property of the Seller."),
    ("liability_cap", "The Seller's total liability shall not exceed the invoice value."),
    ("title", "Title shall remain with the Seller until full payment (retention of title)."),
    ("quantity_tol", "5% more or less in quantity shall be allowed at the Seller's option."),
    ("confidential", "Each party shall keep confidential all information received."),
    ("confidential", "제18조 양 당사자는 상대방의 기밀을 누설하지 아니한다."),
    ("no_set_off", "제24조 매수인은 어떠한 공제도 하지 못한다."),
    ("arbitration", "Any dispute shall be settled by arbitration in Seoul under the KCAB rules."),
    ("payment", "Payment: T/T 30% in advance, balance before shipment."),
    ("export_licence", "Delivery is subject to the Seller obtaining any export licence; no "
                       "export licence is required for these goods."),
    ("suspend_delivery", "Shipment shall not be required until the corresponding credit is "
                         "operative."),
    ("price_adjust", "가격은 원자재 가격 변동 시 조정한다."),
]


def _status(key: str, line: str) -> str:
    row = contract_clauses.analyze(H + line)["clauses"].get(key)
    return row["status"] if row else "absent"


@pytest.mark.parametrize("key,line", NOT_PRESENT, ids=[f"{k}:{s[:28]}" for k, s in NOT_PRESENT])
def test_미정_부정_불리한_문장은_있음이_아니다(key, line):
    assert _status(key, line) != "present"


@pytest.mark.parametrize("key,line", PRESENT, ids=[f"{k}:{s[:28]}" for k, s in PRESENT])
def test_정상_조항은_그대로_있음이다(key, line):
    assert _status(key, line) == "present"


def test_weak_에는_까닭과_근거가_붙는다():
    row = contract_clauses.analyze(H + "Incoterms to be agreed later.")["clauses"]["incoterms"]
    assert row["status"] == "weak" and "추후" in row["reason"]
    assert "Incoterms to be agreed later" in row["evidence"]


# ── 실물 보세가공 계약서 (PDF 에서 읽힌 글을 줄인 것) ───────────────────────
BONDED = (
    "BONDED PROCESSING TRADE CONTRACT\nThis contract is made by and between the following "
    "parties concerned:\nHarborline Fiber Trading Inc., hereinafter referred to as Party A,\n"
    "having its head office at\nSan Francisco, U.S.A., and\nHaneul Weaving Co., Ltd., "
    "hereinafter referred to as Party B,\nhaving its head office at\nSeoul, Republic of "
    "Korea.\nWhereas it is the mutual intent of the parties to do business.\n"
    "Article 1 Party A shall supply to Party B 10,000 kilograms of rayon yarn at USD 2.80 per "
    "kilogram. Party B shall process the yarn and supply to Party A 9,000 meters of rayon "
    "fabric.\n"
    "Article 2 Party B guarantees that the finished rayon fabric shall conform to the samples "
    "approved by Party A. Any material nonconformity shall be notified in writing within ten "
    "business days after inspection.\n"
    "Article 3 Party B shall establish an irrevocable sight letter of credit for USD 28,000 in "
    "favor of Party A before shipment of the yarn. Party A shall establish an irrevocable sight "
    "letter of credit for USD 45,000 in favor of Party B before shipment of the fabric. "
    "Documentary conditions shall be agreed in writing, and shipment shall not be required "
    "until the corresponding credit is operative.\n"
    "Article 4 The yarn shall be shipped by 15 November 2026. Partial shipments shall be "
    "subject to the written agreement of both parties.\n"
    "Article 6 Subject to Article 9, a party in breach of this contract shall compensate the "
    "other party for direct loss proved to have resulted from such breach.\n"
    "Article 9 Subject to Articles 11 and 13, Party B shall indemnify Party A for all losses, "
    "costs, claims, and liabilities arising out of or related to the yarn, processing, "
    "storage, transport, or finished fabric, including losses caused in whole or in part by "
    "Party A's own instructions or negligence, without monetary limit. Party A shall have no "
    "corresponding indemnity obligation to Party B.\n"
    "Article 15 Retention of Title. For each shipment, ownership remains with its seller until "
    "that seller receives the full price. Until then, the buyer shall keep the goods "
    "identifiable and shall not resell, pledge, mix or process them without the seller's "
    "written consent.\n")


def _bonded():
    return contract_clauses.analyze(BONDED)


@pytest.mark.parametrize("key", ["unlimited_damages", "own_negligence_indemnity",
                                 "consigned_material_lock"])
def test_실물_보세가공_독소_셋(key):
    assert _bonded()["clauses"][key]["status"] == "present"


@pytest.mark.parametrize("key", ["inspection", "liability_cap", "lc_deadline"])
def test_실물_보세가공_적혀_있으나_부족(key):
    """검사 시기 없음 · 제6조 한도가 제9조에 밀림 · 상대 신용장 기한 없음."""

    assert _bonded()["clauses"][key]["status"] == "weak"


def test_실물_보세가공_선적_보류권은_있다():
    """제3조 '신용장이 유효해질 때까지 선적 의무 없음' — 넣으라고 하면 안 됩니다."""

    assert _bonded()["clauses"]["suspend_delivery"]["status"] == "present"


def test_가공계약_조항은_가공계약에서만_본다():
    assert {"consigned_material_lock", "material_yield"} <= _bonded()["context"]
    plain = H + ("Title shall remain with the Seller until paid; the Buyer shall not resell "
                 "or process the goods without the Seller's written consent.")
    found = contract_clauses.analyze(plain)
    assert "consigned_material_lock" not in found["clauses"]
    assert not found["context"]


def test_판정_결과에_보완_묶음과_근거가_나온다():
    result = contract_clause_service.review(BONDED, "CIF", "US")
    weak = {row["key"] for row in result["weak"]}
    assert {"inspection", "liability_cap", "lc_deadline"} <= weak
    assert not weak & {row["key"] for row in result["missing"]}
    assert all(row["evidence"] for row in result["toxic"])
    text = contract_clause_service.as_text(result)
    assert "제 구실을 못 하는 조항" in text and "근거:" in text
    # 가공계약 이익조항은 점검표에 나오고, 보통 점검표에는 안 나옵니다.
    assert "material_yield" in {row["key"] for row in result["gain"]}
    plain = contract_clause_service.checklist("CIF")
    assert "material_yield" not in {row["key"] for row in plain["gain"]}


def test_오퍼_시트_선적은_시기가_없어_부족이다():
    sheet = ("Offer Sheet\nItem Name : Nylon 95% / spandex 5% fabric\n"
             "PACKING: EXPORT STANDARD PACKED\nPAYMENT : BY T/T BEFORE SHIPMENT\n"
             "DELIVERY : SHANG HAI, PORT CY\n")
    row = contract_clauses.analyze(sheet)["clauses"]["shipment"]
    assert row["status"] == "weak" and "시기" in row["reason"]
