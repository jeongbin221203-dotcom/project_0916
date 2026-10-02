"""필수·이익 조항을 **실무에서 쓰는 문구**로 전수 확인합니다.

왜 이 파일이 있나
  liability_cap 이 흔한 문구 여섯 가지 중 다섯을 놓치고 있었습니다. 그런데 그건
  공격해 보다 **우연히** 나왔습니다. 나머지 27개에 같은 결함이 없다고 말할
  근거가 없어서, 조항마다 실무 문구를 네 개씩 넣어 전부 훑었습니다.

  처음 돌렸더니 **112개 중 35개(31%)를 놓쳤습니다.**

필수·이익의 미탐이 왜 나쁜가
  독소 미탐: 위험한 조항을 못 찾습니다 — 나쁘지만 **원래 모르던 상태**입니다
  필수 미탐: **이미 넣은 사람에게 "넣으세요"** 라고 합니다. 틀린 말을 적극적으로
             하는 것이고, 한 번 그러면 다음부터 진짜 경고도 흘려듣습니다

놓친 꼴은 셋이었습니다
  낱말을 안 쓰고 뜻만 적음  "events beyond its control" (force majeure 라는 말 없이)
                           "Ownership remains with the Seller until payment"
  국문 실무 용어            적하보험 · 부보 · 전신환 · 검수 · 분할선적 · 치공구
  숫자를 글자로            "within fourteen days" (14 가 아니라)

그리고 **제 시험 문장이 틀린 것도 있었습니다.** agency_protection 은 대리점
관계가 **있을 때** 뜨는 조항인데 "대리점이 아니다"를 넣고 못 찾는다고 적었습니다.
시험이 틀렸는지 제품이 틀렸는지부터 가려야 합니다.
"""

from __future__ import annotations

import pytest

from app.processors import contract_clauses

H = "SALES CONTRACT\n"

CASES = {
    # ── 필수 ───────────────────────────────────────────────────────────────
    "goods": [
        "1. DESCRIPTION OF GOODS: as per Annex 1.",
        "The commodity, specification and quantity are set out in Annex 1.",
        "제1조 (물품의 명세) 품명·규격·수량은 별지 1과 같다.",
        "제1조 품명 및 HS부호는 별지에 따른다.",
    ],
    "incoterms": [
        "2. PRICE: CIF Yokohama, Incoterms 2020.",
        "The trade term shall be FOB Busan (Incoterms 2020).",
        "제2조 (가격조건) 인코텀즈 2020 FOB 부산으로 한다.",
        "제2조 가격조건은 CIF 로테르담으로 한다.",
    ],
    "payment": [
        "3. PAYMENT: by irrevocable L/C at sight.",
        "Payment shall be made by T/T within 30 days of the B/L date.",
        "제3조 (결제조건) 대금은 일람불 신용장으로 지급한다.",
        "제3조 대금지급은 선적 후 30일 이내 전신환으로 한다.",
    ],
    "shipment": [
        "4. SHIPMENT: latest 30 November. Partial shipment allowed.",
        "Shipment shall be effected on or before 30 Nov 2026 from Busan.",
        "제4조 (선적조건) 선적기일은 2026년 11월 30일로 한다.",
        "제4조 분할선적을 허용하고 환적은 금지한다.",
    ],
    "inspection": [
        "5. INSPECTION at the port of loading by SGS.",
        "Quality and quantity shall be inspected before shipment.",
        "제5조 (검사) 품질 검사는 선적지에서 실시한다.",
        "제5조 검수는 도착 후 14일 이내에 한다.",
    ],
    "insurance": [
        "6. INSURANCE: ICC(A) for 110% of the invoice value.",
        "The Seller shall effect marine cargo insurance covering 110%.",
        "제6조 (보험) 적하보험은 송장 금액의 110%로 부보한다.",
        "제6조 해상보험은 매도인이 부보한다.",
        # '부보' 없이 '적하보험'만 적는 꼴. 이 문구가 없으면 적하보험 규칙을
        # 지우더라도 '부보' 규칙이 대신 잡아 **되돌림 확인이 잠잠해집니다.**
        "제6조 적하보험은 매도인이 가입한다.",
    ],
    "force_majeure": [
        "7. FORCE MAJEURE: acts of God, war, strike.",
        "Neither party shall be liable for delay caused by events beyond its control.",
        "제7조 (불가항력) 천재지변·전쟁·파업으로 인한 지연은 책임지지 아니한다.",
        "제7조 불가항력 사유가 발생한 경우 즉시 통지한다.",
    ],
    "governing_law": [
        "8. GOVERNING LAW: the laws of the Republic of Korea.",
        "This Contract shall be governed by and construed under Korean law.",
        "제8조 (준거법) 본 계약은 대한민국 법률에 따른다.",
        "제8조 본 계약의 해석은 한국법에 의한다.",
    ],
    "arbitration": [
        "9. ARBITRATION in Seoul under the KCAB rules.",
        "All disputes shall be finally settled by arbitration in Seoul.",
        "제9조 (중재) 분쟁은 대한상사중재원의 중재로 해결한다.",
        "제9조 모든 분쟁은 서울에서 중재로 최종 해결한다.",
    ],
    "title": [
        "10. RETENTION OF TITLE: title shall pass upon full payment.",
        "Ownership of the Goods remains with the Seller until payment in full.",
        "제10조 (소유권 유보) 소유권은 대금 완납 시 이전한다.",
        "제10조 물품의 소유권은 대금을 전부 받을 때까지 매도인에게 유보된다.",
    ],
    "packing": [
        "11. PACKING: export standard seaworthy packing.",
        "Each carton shall bear the shipping marks in Annex 2.",
        "제11조 (포장) 수출 표준 포장으로 한다.",
        "제11조 포장 및 화인은 별지에 따른다.",
    ],
    "confidential": [
        "12. CONFIDENTIALITY: each party shall keep confidential.",
        "Neither party shall disclose Confidential Information to third parties.",
        "제12조 (비밀유지) 양 당사자는 비밀을 유지한다.",
        "제12조 어느 당사자도 상대방의 기밀을 제3자에게 누설하지 아니한다.",
    ],
    "quantity_tol": [
        "13. QUANTITY: 5% more or less acceptable.",
        "A tolerance of plus or minus five percent in quantity shall apply.",
        "제13조 수량의 과부족 5%를 허용한다.",
        "제13조 ±5% 수량 과부족을 인정한다.",
    ],
    "amendment": [
        "14. AMENDMENT: in writing signed by both parties.",
        "No variation shall be effective unless in writing.",
        "제14조 (변경) 본 계약의 변경은 서면 합의로만 효력이 있다.",
        "제14조 통지는 서면으로 아래 주소로 발송한다.",
    ],
    # ── 이익 ───────────────────────────────────────────────────────────────
    "late_interest": [
        "15. Overdue amounts shall bear interest at 1.5% per month.",
        "Late payment shall incur interest at the rate of 6% per annum.",
        "제15조 연체 시 월 1.5%의 지연이자를 가산한다.",
        "제15조 지급이 지연되면 연 6%의 이자를 부담한다.",
    ],
    "price_adjust": [
        "16. The price may be adjusted if raw material costs change by more than 5%.",
        "Prices are subject to adjustment upon material cost fluctuation.",
        "제16조 원자재 가격이 5% 이상 변동하면 단가를 재협의한다.",
        "제16조 환율 변동 시 가격을 조정할 수 있다.",
    ],
    "liability_cap": [
        "17. The Seller's liability shall not exceed the invoice value.",
        "In no event shall total liability exceed the price paid.",
        "제17조 손해배상책임은 주문 금액을 초과하지 아니한다.",
        "제17조 책임의 한도는 송장 금액으로 한다.",
    ],
    "export_licence": [
        "18. This Contract is subject to the Seller obtaining an export licence.",
        "Performance is conditional upon export approval from the Korean authorities.",
        "제18조 본 계약은 수출허가 취득을 조건으로 한다.",
        "제18조 전략물자 수출허가를 받지 못하면 계약은 효력을 잃는다.",
    ],
    "ip": [
        "19. All tooling and moulds shall remain the property of the Seller.",
        "Drawings and technical data remain the exclusive property of the Seller.",
        "제19조 금형과 도면의 소유권은 매도인에게 있다.",
        "제19조 치공구의 소유권은 매도인에게 귀속한다.",
    ],
    "min_order": [
        "20. The minimum order quantity shall be 5,000 units.",
        "A cancellation fee of 20% applies to orders cancelled after production starts.",
        "제20조 최소 주문 수량은 5,000개로 한다.",
        "제20조 생산 착수 후 취소 시 20%의 취소 수수료를 부담한다.",
    ],
    # **제 시험 문장이 틀렸었습니다.** 이 조항은 대리점 관계가 **있을 때** 떠서
    # "그 나라 대리점 보호법을 확인하라"고 알려 주는 것입니다. 그런데 처음에는
    # "대리점이 아니다"라는 문장을 넣고 못 찾는다고 적었습니다. (2026-10-02)
    "agency_protection": [
        "21. The Buyer is appointed as the sole distributor in the Territory.",
        "The Agent shall have the exclusive right to sell the Products in Germany.",
        "제21조 매수인을 해당 지역의 독점 대리점으로 지정한다.",
        "제21조 총판 계약으로서 독점 판매권을 부여한다.",
    ],
    "cisg_silent": [
        "22. The CISG shall not apply to this Contract.",
        "The United Nations Convention on Contracts for the International Sale of "
        "Goods is expressly excluded.",
        "제22조 국제물품매매계약에 관한 국제연합 협약(CISG)의 적용을 배제한다.",
        "제22조 CISG 를 적용한다.",
    ],
    "suspend_delivery": [
        "23. The Seller may suspend shipment if payment is overdue by 15 days.",
        "The Seller may withhold further deliveries while amounts remain unpaid.",
        "제23조 대금이 연체되면 선적을 중단할 수 있다.",
        "제23조 미지급 금액이 있는 동안 출하를 보류할 수 있다.",
    ],
    "no_set_off": [
        "24. The Buyer shall pay without any set-off or deduction.",
        "All payments shall be made free of counterclaim or withholding.",
        "제24조 매수인은 상계 없이 전액을 지급한다.",
        "제24조 매수인은 어떠한 공제도 하지 못한다.",
    ],
    "claim_period": [
        "25. Claims shall be notified within 30 days after arrival.",
        "Any claim must be raised within fourteen days of discharge.",
        "제25조 클레임은 도착 후 30일 이내에 통지한다.",
        "제25조 하자 통지는 인도 후 14일 이내에 서면으로 한다.",
    ],
    "lc_deadline": [
        "26. The Buyer shall open the L/C by 15 November 2026.",
        "The Letter of Credit shall be established no later than 30 days before shipment.",
        "제26조 신용장은 2026년 11월 15일까지 개설한다.",
        "제26조 매수인은 선적 30일 전까지 신용장을 개설하여야 한다.",
    ],
    "buyer_design_ip": [
        "27. The Buyer warrants that its designs do not infringe third party rights.",
        "The Buyer shall indemnify the Seller against claims arising from the "
        "Buyer's specifications.",
        "제27조 매수인이 제공한 도면이 제3자의 권리를 침해하지 아니함을 보증한다.",
        "제27조 바이어 제공 상표로 인한 분쟁은 매수인이 면책한다.",
    ],
    "exit_buyback": [
        "28. Upon termination the Buyer shall purchase all remaining stock.",
        "The Buyer shall reimburse the unamortised tooling cost on termination.",
        "제28조 해지 시 잔여 재고는 매수인이 인수한다.",
        "제28조 해지 시 금형 미상각분을 정산한다.",
    ],
}

CASE_LIST = [(key, body) for key, bodies in CASES.items() for body in bodies]


@pytest.mark.parametrize("key,body", CASE_LIST,
                         ids=[f"{k}-{i}" for k, bodies in CASES.items()
                              for i in range(len(bodies))])
def test_실무_문구를_찾는다(key, body):
    """못 찾으면 이미 넣은 사람에게 '넣으세요'라고 하게 됩니다."""

    found = contract_clauses.find_in(H + body)
    assert key in found, f"{key} 를 놓쳤습니다: {body[:70]}"


def test_문구를_조항마다_넷씩_둔다():
    """조항 하나에 문구가 하나뿐이면, 그 하나가 우연히 맞아도 모릅니다.

    실제로 그랬습니다 — 부정 가드를 어디에 붙일지 조항당 예문 **하나**로
    판단했다가 여섯 개를 잘못 골랐습니다.
    """

    thin = {key: len(bodies) for key, bodies in CASES.items() if len(bodies) < 3}
    assert not thin, f"문구가 모자란 조항: {thin}"


def test_필수_이익을_빠짐없이_본다():
    """새 조항을 넣고 여기에 문구를 안 적으면, 그 조항은 아무도 안 봅니다."""

    covered = set(CASES)
    actual = {row["key"] for row in contract_clauses.CLAUSES
              if row["category"] in ("must", "gain")}
    assert actual <= covered, f"문구가 없는 조항: {sorted(actual - covered)}"
