"""② 환율 4단계 폴백 — 단계마다 일부러 고장을 내고 무엇이 나오는지 봅니다.

환율은 견적 금액에 그대로 곱해집니다. 값이 1000배 틀리면 견적도 1000배 틀립니다.
"""
import sys, io, json, random
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")
from datetime import date, timedelta
from tests._fuzz_app import build_app
from app.collectors import exchange_client as X
from app.collectors import file_cache

app = build_app()
bad, checked = [], 0


def run(label, *, unipass=None, oxr=None, stored=None, expect_source=None):
    """단계를 갈아 끼우고 결과를 봅니다."""
    global checked
    X.clear_cache()
    X.fetch_unipass_rates.__wrapped__ if hasattr(X.fetch_unipass_rates, "__wrapped__") else None
    real = {"unipass": X.fetch_unipass_rates, "oxr": X._from_open_exchange_rates,
            "last": X._last_good}
    X.fetch_unipass_rates = lambda *a, **k: (unipass if unipass is not None
                                             else {"success": False, "data": {}})
    X._from_open_exchange_rates = lambda: oxr
    X._last_good = lambda: stored
    X._save_last_good = lambda *a, **k: None
    try:
        got = X.fetch_krw_rates()
    finally:
        X.fetch_unipass_rates = real["unipass"]
        X._from_open_exchange_rates = real["oxr"]
        X._last_good = real["last"]
        X.clear_cache()

    rates = got.get("data") or {}
    source = got.get("source")
    checked += 6
    if expect_source and source != expect_source:
        bad.append(f"{label}: 출처가 '{source}' (기대 '{expect_source}')")
    if rates.get("KRW") != 1.0:
        bad.append(f"{label}: KRW 가 1.0 이 아님 ({rates.get('KRW')!r})")
    for code, value in rates.items():
        if value is None or not isinstance(value, (int, float)) or value <= 0:
            bad.append(f"{label}: {code} 환율이 쓸 수 없는 값 {value!r}")
            break
    # 화면에 내보내는 설명이 사실과 맞는가
    basis = X.rate_basis(got)
    if source == "mock" and not any(w in basis for w in ("예시", "고정", "참고")):
        bad.append(f"{label}: 예시 환율인데 설명에 그 말이 없음 — '{basis}'")
    if X.rate_is_real(got) != (source in ("api", "market", "stored")):
        bad.append(f"{label}: rate_is_real 이 출처와 안 맞음 ({source})")
    # 달러가 터무니없는 값이면 견적이 통째로 틀립니다
    usd = rates.get("USD")
    if isinstance(usd, (int, float)) and usd and not (500 <= usd <= 3000):
        bad.append(f"{label}: USD 가 {usd:,} 원으로 나감 — 있을 수 없는 값")
    if usd is not None and not isinstance(usd, (int, float)):
        bad.append(f"{label}: USD 가 숫자가 아닌 채로 나감 ({usd!r})")
    return got, rates


with app.app_context():
    good = {code: value for code, value in
            {"USD": 1380.5, "EUR": 1495.2, "JPY": 9.12, "CNY": 190.3, "KRW": 1.0}.items()}

    # ── 1단계 살아 있음 ──
    run("① 관세청", unipass={"success": True, "data": dict(good),
                             "applied_date": "2026-09-26", "source": "api"},
        expect_source="api")
    # ── 1 죽음 → 2 시장환율 ──
    run("② 시장환율", oxr={**X.ok(dict(good), "market"), "applied_date": "2026-09-25"},
        expect_source="market")
    # ── 1·2 죽음 → 3 저장해 둔 값 ──
    run("③ 저장값", stored={**X.ok(dict(good), "stored"), "applied_date": "2026-09-01",
                            "stored_days": 25, "saved_date": "2026-09-01", "origin": "customs"},
        expect_source="stored")
    # ── 모두 죽음 → 4 예시 ──
    run("④ 예시", expect_source="mock")

    # ── 기관이 이상한 값을 보낼 때 ──
    WEIRD = [
        ("달러가 1.38 (자릿수 실수)", {"USD": 1.3805, "KRW": 1.0}),
        ("달러가 0",               {"USD": 0, "KRW": 1.0}),
        ("달러가 음수",             {"USD": -1380.5, "KRW": 1.0}),
        ("달러가 글자",             {"USD": "1380.5", "KRW": 1.0}),
        ("달러가 None",            {"USD": None, "KRW": 1.0}),
        ("KRW 가 1000",           {"USD": 1380.5, "KRW": 1000.0}),
        ("엔이 1달러 기준(0.0072)",  {"USD": 1380.5, "JPY": 0.0072, "KRW": 1.0}),
        ("빈 표",                  {}),
    ]
    for label, rates in WEIRD:
        run(f"기관 이상값 · {label}",
            unipass={"success": True, "data": dict(rates), "applied_date": "2026-09-26",
                     "source": "api"})

    # ── 저장값이 너무 오래됐을 때 (30일 넘음) ──
    X.clear_cache()
    file_cache.write(X.LAST_GOOD_FILE, {"krw_per_unit": dict(good),
                                        "applied_date": "2025-01-01",
                                        "origin": "customs", "saved_date": "2025-01-01"})
    checked += 1
    if X.STORED_MAX_DAYS != 30:
        bad.append(f"저장값 유효기간이 {X.STORED_MAX_DAYS}일로 바뀜")

    # ── convert() 왕복 · 없는 통화 ──
    for one, other in [("USD", "KRW"), ("KRW", "USD"), ("EUR", "JPY"), ("JPY", "CNY")]:
        checked += 2
        there = X.convert(100.0, one, other, good)
        if there is None:
            bad.append(f"convert {one}→{other} 가 None")
            continue
        back = X.convert(there, other, one, good)
        if back is None or abs(back - 100.0) > 0.01:
            bad.append(f"convert {one}→{other}→{one} 가 {back} (100 이어야 함)")
    for one, other in [("USD", "ZZZ"), ("ZZZ", "USD"), ("", "USD"), ("USD", "")]:
        checked += 1
        if X.convert(100.0, one, other, good) is not None:
            bad.append(f"convert {one!r}→{other!r} 가 값을 만들어 냄")

print(f"■ ② 환율 폴백 · 확인 {checked}가지 · 문제 {len(bad)}건")
for b in bad: print("   ★", b)
