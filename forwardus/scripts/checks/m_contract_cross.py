"""좋은 조항이 독소조항으로 오인되는가 — 이게 제일 위험합니다.

없는 독소조항을 있다고 하면, 이용자는 바이어에게 "이 문구를 빼 달라"고 하고
바이어는 "그런 문구 없다"고 합니다. 신뢰가 한 번에 무너집니다.
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")
from app.processors import contract_clauses as C

TOXIC = {row["key"] for row in C.CLAUSES if row["category"] == "toxic"}
bad = []

# ① 우리가 권하는 모범 조항(must·gain)을 넣었을 때 독소조항이 걸리면 안 됩니다
for row in C.CLAUSES:
    if row["category"] == "toxic":
        continue
    hit = C.find_in(row["text_en"]) & TOXIC
    if hit:
        bad.append(f"모범 조항 [{row['key']}] 영문 → 독소 {sorted(hit)}")

# ② 우리가 쓴 한국어 모범 문구
KO_GOOD = {
 "goods": "제1조 (물품의 명세) 물품의 품명, HS부호, 규격 및 수량은 별지 1과 같다.",
 "incoterms": "제2조 (가격조건) 가격조건은 INCOTERMS 2020 에 따른 FOB 부산항으로 한다.",
 "payment": "제3조 (결제조건) 매수인은 선적 30일 전까지 취소불능 신용장을 개설한다.",
 "shipment": "제4조 (선적조건) 분할선적은 허용하고 환적은 허용하지 아니한다.",
 "inspection": "제5조 (검사) 선적지 검사를 최종으로 하며, 도착 후 14일 내 미통보 시 인수한 것으로 본다.",
 "insurance": "제6조 (보험) 적하보험은 송장금액의 110%로 ICC(A) 조건으로 부보한다.",
 "force_majeure": "제7조 (불가항력) 불가항력 사유 발생 시 지체 없이 통보하며 책임을 지지 아니한다.",
 "governing_law": "제8조 (준거법) 본 계약의 준거법은 대한민국 법으로 한다.",
 "arbitration": "제9조 (중재) 분쟁은 대한상사중재원 중재규칙에 따라 서울에서 해결한다.",
 "title": "제10조 (소유권 유보) 소유권은 대금 완납 시 이전하고, 위험은 인코텀즈에 따른다.",
 "late_interest": "제11조 (지연이자) 지급 지체 시 연 12%의 지연이자를 일할 계산한다.",
 "price_adjust": "제12조 (가격 조정) 환율이 5% 이상 변동하면 가격 조정을 협의한다.",
 "liability_cap": "제13조 (책임 한도) 총 손해배상 한도는 송장금액을 초과하지 아니하며, 간접손해는 배상하지 아니한다.",
 "export_licence": "제14조 (수출허가) 수출 허가를 받지 못한 경우 매도인은 의무를 면한다.",
 "ip": "제15조 (금형) 금형과 도면의 소유권은 매도인에게 귀속된다.",
 "min_order": "제16조 (최소 주문) 연간 최소 주문 수량은 10,000개로 한다.",
 # 해지·관할·반품을 **정상적으로** 적은 문구도 걸리면 안 됩니다
 "정상 해지": "제17조 (해지) 당사자는 상대방이 계약을 중대하게 위반하고 30일 내 시정하지 아니한 경우 해지할 수 있다.",
 "정상 관할": "제18조 (관할) 소송이 필요한 경우 서울중앙지방법원을 관할법원으로 한다.",
 "정상 반품": "제19조 (반품) 하자가 확인된 수량에 한하여 반품할 수 있으며, 비용은 귀책 당사자가 부담한다.",
 "정상 배상": "제20조 (배상) 당사자는 자신의 귀책사유로 발생한 손해를 배상한다.",
 "정상 가격": "제21조 (가격) 단가는 별지 2의 가격표에 따르며, 연 1회 협의하여 조정할 수 있다.",
}
for label, text in KO_GOOD.items():
    hit = C.find_in(text) & TOXIC
    if hit:
        bad.append(f"한국어 정상 문구 [{label}] → 독소 {sorted(hit)}  · 글: {text[:50]}")

print(f"■ 오인 검사 · 모범 조항 {len([r for r in C.CLAUSES if r['category'] != 'toxic'])}개"
      f" + 한국어 정상 문구 {len(KO_GOOD)}개 · 오인 {len(bad)}건")
for b in bad: print("   ★", b)
