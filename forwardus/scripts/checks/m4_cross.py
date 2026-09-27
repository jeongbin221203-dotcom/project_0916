"""나라 인증 문서가 나라와 무관한 질문을 가로채지 않는가 (오탐)."""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")
from tests._fuzz_app import build_app
from app.services import knowledge_service as K

GENERAL = [
    "CBM이 뭐예요?", "B/L과 AWB 차이가 뭔가요?", "인코텀즈 FOB랑 CIF 차이",
    "신용장 네고가 뭐예요?", "수출신고필증은 어디서 받나요?", "원산지증명서 발급 절차",
    "LCL과 FCL 중 어느 쪽이 싼가요?", "데머리지가 뭔가요?", "계약서 독소조항 알려줘",
    "포워더 부킹은 어떻게 하나요?", "수출 절차 알려줘", "처음 수출하는데 뭐부터 하나요",
    "적하보험 들어야 하나요?", "HS코드는 어떻게 찾아요?", "CE 마킹이 뭔가요?",
    "관세 환급 받을 수 있나요?", "컨테이너 규격 알려주세요", "용적중량 계산법",
    "수출 인증이 뭔가요?", "인증 받아야 하나요?", "무슨 인증이 필요한가요?",
]
app = build_app()
bad = []
with app.app_context():
    for question in GENERAL:
        got = K.lookup(question)
        key = (got or {}).get("key", "—")
        # 나라를 대지 않았는데 특정 나라 인증 글이 나오면 동문서답입니다.
        # (CE 마킹은 유럽 전용 말이므로 cert-eu-ce 가 맞습니다)
        if key.startswith("cert-") and "CE" not in question:
            bad.append(f"'{question}' → {key}")
        print(f"   {key:<22} ← {question}")
print(f"\n■ ④ 나라와 무관한 질문 {len(GENERAL)}개 · 나라 인증 글로 새는 것 {len(bad)}건")
for b in bad: print("   ★", b)
