"""② 환율 — 기관이 무엇을 보내든 견적에 쓸 수 없는 값이 새지 않는가. 1만 회."""
import sys, io, random
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")
from tests._fuzz_app import build_app
from app.collectors import exchange_client as X

ROUNDS = int(sys.argv[1]) if len(sys.argv) > 1 else 10000
random.seed(int(sys.argv[2]) if len(sys.argv) > 2 else 606)

CODES = ["USD", "EUR", "JPY", "CNY", "GBP", "AUD", "VND", "IDR", "KWD", "KRW",
         "ZZZ", "", "usd", "US", "USDD", None, 123]
JUNK = [0, -1, -1380.5, "1380.5", None, True, False, float("inf"), float("nan"),
        1e-9, 1e12, 1.3805, 13.805, 138.05, 0.0072, [], {}, "abc"]
GOOD = {"USD": 1380.5, "EUR": 1495.2, "JPY": 9.12, "CNY": 190.3, "GBP": 1760.0,
        "AUD": 910.0, "VND": 0.055, "IDR": 0.085, "KWD": 4500.0}

app = build_app()
bad, checked, passed, blocked = [], 0, 0, 0
with app.app_context():
    real = X.fetch_unipass_rates
    X._save_last_good = lambda *a, **k: None
    X._from_open_exchange_rates = lambda: None
    X._last_good = lambda: None
    try:
        for turn in range(ROUNDS):
            table = {}
            for code in random.sample(CODES, random.randint(0, len(CODES))):
                table[code] = (random.choice(list(GOOD.values())) if random.random() < 0.6
                               else random.choice(JUNK))
            if random.random() < 0.4:                      # 달러를 제대로 넣는 회차
                table["USD"] = random.uniform(900, 1600)
            X.clear_cache()
            X.fetch_unipass_rates = lambda *a, **k: {"success": True, "data": dict(table),
                                                     "applied_date": "2026-09-26", "source": "api"}
            got = X.fetch_krw_rates()
            X.clear_cache()
            rates = got.get("data") or {}
            checked += 3
            if got.get("source") == "api":
                passed += 1
            else:
                blocked += 1
            # 무엇이 나오든 견적에 쓸 수 있는 값이어야 합니다
            if rates.get("KRW") != 1.0:
                bad.append(f"{turn}: KRW 가 {rates.get('KRW')!r}")
            for code, value in rates.items():
                if not isinstance(value, float) or value != value or value <= 0 \
                        or value in (float("inf"),):
                    bad.append(f"{turn}: {code} = {value!r} 가 새어 나감"); break
                if not X.is_currency_code(code):
                    bad.append(f"{turn}: 통화가 아닌 '{code}' 가 표에 남음"); break
            usd = rates.get("USD")
            if usd is None or not (300 <= usd <= 5000):
                bad.append(f"{turn}: USD 가 {usd!r} 로 나감")
            # 환산이 되어야 합니다
            checked += 1
            if X.convert(100.0, "USD", "KRW", rates) is None:
                bad.append(f"{turn}: USD→KRW 환산이 안 됨")
    finally:
        X.fetch_unipass_rates = real

print(f"■ ② 환율 표 {ROUNDS:,}가지 · 확인 {checked:,}가지 · 문제 {len(bad)}건")
print(f"   그대로 쓴 표 {passed:,} · 못 믿어 다음 단계로 내린 표 {blocked:,}")
for b in bad[:12]: print("   ★", b)
