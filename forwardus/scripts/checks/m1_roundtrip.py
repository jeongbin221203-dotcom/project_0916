"""① 나갔다 들어왔을 때 — 적은 값이 그대로인가. 1만 회, 값 종류를 크게 늘렸습니다.

무엇을 잡으려는가
  화면을 떠났다 돌아오면 값이 조용히 달라지는 일. 서류에 실리는 값이라
  한 글자만 달라도 수하인·금액·세번이 틀립니다.
  ㄱ) 저장했다 불러오면 다른 값
  ㄴ) 두 번 왕복하면 또 달라지는 값 (매번 조금씩 깎이는 것)
  ㄷ) 칸이 통째로 사라지는 것
  ㄹ) 품목 줄이 사라지거나 순서가 바뀌는 것
"""
import sys, io, random, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")
from tests._fuzz_app import build_app
from app.services import work_draft_service as W
from app.models import User
from app.extensions import db

ROUNDS = int(sys.argv[1]) if len(sys.argv) > 1 else 10000
random.seed(int(sys.argv[2]) if len(sys.argv) > 2 else 2026)

# 실제로 사람이 적는 것 + 적지 않았으면 좋겠는 것을 섞습니다
HANGUL = ["(주)한빛무역", "김수현", "제주 감귤 10kg 상자", "부산광역시 중구 중앙대로 1",
          "㈜대한물산 서울지점", "포장: 나무 팔레트 4개", "훈증 처리 완료(ISPM 15)"]
LATIN = ["SAMPLE CO., LTD.", "ACME Trading GmbH", "O'Brien & Sons", 'He said "ok"',
         "Ho Chi Minh City, Viet Nam", "C/O DHL — Bldg 3", "ABC\tDEF", "a" * 420]
NUMBERS = ["0", "00123", "1,234.56", "  88.8  ", "1e3", "-5", "12.000",
           "999999999999", "0.001", "3/4", "2.5%"]
RISKY = ["SWIFT: DEUTDEFF500", "A/C 1234-5678-9012", "IBAN DE89 3704 0044 0532 0130 00",
         "은행 계좌 110-234-567890", "TEL 02-1234-5678", "HS 8471.30-0000"]
ODD = ["", "   ", None, "​", "🚢 해상", "türkçe ışık", "ЖЖ", "日本語", "\n줄바꿈\n",
       "<script>x</script>", "'; DROP TABLE users; --", "＝１２３"]
POOL = HANGUL + LATIN + NUMBERS + RISKY + ODD

app = build_app()
bad, checked = [], 0
with app.app_context():
    viewer = User.query.first()
    for turn in range(ROUNDS):
        # 이번 회차에 적을 칸을 무작위로 고릅니다 (아예 안 적는 회차도 있습니다)
        keys = random.sample(W.SHARED_FIELDS, random.randint(0, len(W.SHARED_FIELDS)))
        fields = {key: random.choice(POOL) for key in keys}
        rows = []
        for _ in range(random.randint(0, 4)):
            item_keys = random.sample(W.ITEM_FIELDS, random.randint(1, len(W.ITEM_FIELDS)))
            rows.append({key: random.choice(POOL) for key in item_keys})

        W.clear(viewer)
        first = W.save(viewer, {"fields": fields, "items": rows})
        # ── 떠났다 돌아옵니다 ──
        back = W.load(viewer)
        checked += 1
        if back.get("fields") != first.get("fields") or back.get("items") != first.get("items"):
            bad.append(f"{turn}: 저장한 것과 불러온 것이 다름"); continue

        # ㄱ) 서버가 정한 다듬기(_text)와 결과가 같아야 합니다
        for key, raw in fields.items():
            want = W._text(raw)
            got = back["fields"].get(key, "")
            checked += 1
            if want and got != want:
                bad.append(f"{turn}: {key} — 적은 것 {raw!r} → 돌아온 것 {got!r} (기대 {want!r})")
            if not want and key in back["fields"]:
                bad.append(f"{turn}: {key} — 빈 값인데 칸이 생김 {got!r}")

        # ㄴ) 돌아온 값을 그대로 다시 저장하면 또 달라지면 안 됩니다
        again = W.save(viewer, {"fields": back.get("fields") or {},
                                "items": back.get("items") or []})
        checked += 1
        if again.get("fields") != back.get("fields"):
            diff = {k: (back["fields"].get(k), again["fields"].get(k))
                    for k in set(back["fields"]) | set(again["fields"])
                    if back["fields"].get(k) != again["fields"].get(k)}
            bad.append(f"{turn}: 두 번 왕복하니 또 달라짐 {json.dumps(diff, ensure_ascii=False)[:160]}")
        if again.get("items") != back.get("items"):
            bad.append(f"{turn}: 두 번 왕복하니 품목이 달라짐")

        # ㄹ) 품목 줄 수와 순서
        kept = [row for row in ({k: W._text(v) for k, v in item.items() if W._text(v)}
                                for item in rows) if row]
        checked += 1
        if back.get("items") != kept:
            bad.append(f"{turn}: 품목 {len(kept)}줄을 적었는데 {len(back.get('items') or [])}줄로 돌아옴")

        # ㅁ) 계좌·SWIFT는 어떤 경우에도 남아 있으면 안 됩니다
        blob = json.dumps(back, ensure_ascii=False)
        for leak in ("DEUTDEFF500", "1234-5678-9012", "0532 0130 00", "110-234-567890"):
            checked += 1
            if leak in blob:
                bad.append(f"{turn}: 계좌/스위프트가 저장됨 — {leak}")

        # ㅂ) 운송 계획 화면으로 넘겨도 죽지 않아야 합니다
        checked += 1
        try:
            W.planning_prefill(viewer)
        except Exception as error:
            bad.append(f"{turn}: 운송 계획 미리채움 죽음 {type(error).__name__} {error}")

        if turn % 2000 == 0 and turn:
            db.session.expire_all()

print(f"■ ① 나갔다 들어오기 {ROUNDS:,}회 · 확인 {checked:,}가지 · 문제 {len(bad)}건")
for b in bad[:14]: print("   ★", b)
