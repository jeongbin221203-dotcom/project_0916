"""나라 인증 문서가 사람 말투로 나오는가 — 나라 × 말투."""
import sys, io, re
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")
from tests._fuzz_app import build_app
from app.services import knowledge_service as K

# 문서마다 사람이 부르는 나라 이름
NAMES = {
    "cert-australia": "호주", "cert-canada": "캐나다", "cert-eu-ce": "유럽",
    "cert-hongkong": "홍콩", "cert-india": "인도", "cert-indonesia": "인도네시아",
    "cert-japan-pse": "일본", "cert-malaysia": "말레이시아",
    "cert-philippines": "필리핀", "cert-saudi": "사우디", "cert-singapore": "싱가포르",
    "cert-taiwan": "대만", "cert-thailand": "태국", "cert-turkiye": "튀르키예",
    "cert-uae": "UAE", "cert-uk": "영국",
}
SHAPES = [
    "{0} 수출할 때 인증이 필요한가요?",
    "{0}에 보낼 때 인증 받아야 하나요?",
    "{0} 인증 뭐가 필요해?",
    "{0}은 인증이 필요 없나요?",
    "{0} 수출 인증 알려주세요",
    "{0}으로 수출하려면 무슨 인증이 있어야 하나요",
]
app = build_app()
bad, total = [], 0
with app.app_context():
    for key, name in NAMES.items():
        for shape in SHAPES:
            total += 1
            question = shape.format(name)
            got = K.lookup(question)
            if not got:
                bad.append(f"'{question}' → 아무 답도 안 나옴")
            elif got["key"] != key:
                bad.append(f"'{question}' → {got['key']} (기대 {key})")
print(f"■ ④ 나라 인증 {len(NAMES)}곳 × 말투 {len(SHAPES)}가지 = {total}가지 · 문제 {len(bad)}건")
for b in bad[:20]: print("   ★", b)
