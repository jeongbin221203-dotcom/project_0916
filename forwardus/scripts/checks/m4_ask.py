"""④ 문서마다 적어 둔 예시 질문(ask)으로 그 문서가 나오는가 — 전수.

예시 질문으로도 자기 문서가 안 나오면, 그 문서는 사실상 꺼져 있는 것이고
이용자는 엉뚱한 답을 받습니다.
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")
from tests._fuzz_app import build_app
from app.services import knowledge_service as K

app = build_app()
miss, wrong, total = [], [], 0
with app.app_context():
    entries = K._entries() if hasattr(K, "_entries") else None
    if entries is None:
        for name in ("load", "_load", "entries", "_all"):
            if hasattr(K, name):
                entries = getattr(K, name)()
                break
    rows = entries.values() if isinstance(entries, dict) else list(entries)
    for entry in rows:
        # ask 는 한 줄 글자열입니다. ;; 로 여러 개를 적은 문서도 있습니다.
        asks = [q.strip() for q in str(entry.get("ask") or "").split(";;") if q.strip()]
        for question in asks:
            total += 1
            got = K.lookup(question)
            if not got:
                miss.append(f"[{entry['key']}] '{question}' → 아무 답도 안 나옴")
            elif got.get("key") != entry["key"]:
                wrong.append(f"[{entry['key']}] '{question}' → 다른 문서({got['key']})가 나옴")

print(f"■ ④ 지식 문서 {len(rows)}개 · 예시 질문 {total}개")
print(f"   답이 안 나오는 질문 {len(miss)}개 · 엉뚱한 문서가 나오는 질문 {len(wrong)}개")
for m in miss[:10]: print("   ★", m)
for w in wrong[:10]: print("   ◇", w)
