"""㉑ 물류비 견적 — 항목의 합이 총액인가, 조건별 부담이 맞는가, 환산이 맞는가.

견적서 숫자는 그대로 바이어에게 나갑니다. 합이 안 맞으면 그 자리에서 신뢰를 잃고,
부담 주체가 틀리면 나중에 누가 낼지로 다툽니다.
"""
import sys, io, random
from decimal import Decimal, ROUND_HALF_EVEN
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")
from app.processors import cost_calculator as C
from app.processors.cargo_calculator import calculate_cargo_lines

ROUNDS = int(sys.argv[1]) if len(sys.argv) > 1 else 20000
random.seed(int(sys.argv[2]) if len(sys.argv) > 2 else 2121)
D = Decimal

ICC = {"EXW": set(), "FCA": {"origin"}, "FAS": {"origin"}, "FOB": {"origin"},
       "CFR": {"origin", "freight"}, "CIF": {"origin", "freight", "insurance"},
       "CPT": {"origin", "freight"}, "CIP": {"origin", "freight", "insurance"},
       "DAP": {"origin", "freight", "destination"},
       "DPU": {"origin", "freight", "destination"},
       "DDP": {"origin", "freight", "destination", "import"}}

bad, checked = [], 0
for turn in range(ROUNDS):
    mode = random.choice(["SEA", "AIR"])
    sea = random.choice(["FCL", "LCL"]) if mode == "SEA" else None
    term = random.choice(list(ICC))
    rate = random.choice([1380.5, 1295.0, 1500.25, 900.0, 2000.0])
    freight = round(random.uniform(1, 90000), 2)
    invoice = round(random.uniform(1, 5_000_000), 2)
    rows = [{"product_description": "화물", "package_type": "carton",
             "quantity": random.choice([1, 40, 900, 9999]),
             "length_cm": random.choice([10, 60, 120]),
             "width_cm": random.choice([10, 60, 100]),
             "height_cm": random.choice([10, 50, 220]),
             "weight_per_package_kg": random.choice([0.1, 8, 400])}]
    metrics = calculate_cargo_lines(rows, "40GP" if sea != "FCL" else
                                    random.choice(["20GP", "40GP", "40HC"]))
    try:
        got = C.calculate_logistics_cost(
            transport_mode=mode, sea_mode=sea, incoterms=term,
            freight_usd=freight, freight_source="tariff",
            invoice_value_usd=invoice, metrics=metrics,
            exchange_rate=rate, exchange_source="api")
    except Exception as error:
        bad.append(f"{turn}: 죽음 {type(error).__name__} {error}"); continue

    lines = got["lines"]
    checked += 6
    # ① 항목의 합이 총액
    if sum(l["krw_amount"] for l in lines) != got["total_krw"]:
        bad.append(f"{turn}: 항목 합 ≠ 총액")
    # ② 수출자 + 바이어 = 총액
    if got["exporter_total_krw"] + got["buyer_total_krw"] != got["total_krw"]:
        bad.append(f"{turn}: 수출자 + 바이어 ≠ 총액")
    # ③ 분류별 합의 합이 총액
    if sum(got["category_totals"].values()) != got["total_krw"]:
        bad.append(f"{turn}: 분류별 합 ≠ 총액")
    # ④ 음수·0 항목이 없어야 합니다
    for l in lines:
        if l["krw_amount"] < 0:
            bad.append(f"{turn}: {l['name']} 이 음수 {l['krw_amount']}")
        if l["original_amount"] < 0:
            bad.append(f"{turn}: {l['name']} 원화 전 금액이 음수")
    # ⑤ 환산이 맞는가 (USD 항목)
    for l in lines:
        if l["original_currency"] == "USD":
            want = round(l["original_amount"] * rate)
            if abs(l["krw_amount"] - want) > 1:
                bad.append(f"{turn}: {l['name']} 환산 {l['krw_amount']} ≠ {want}")
    # ⑥ 조건별 부담. 적하보험료만 규칙이 다릅니다 — 의무가 아니라 **누가 내는가**.
    #    D조건은 수출자가 도착지까지 위험을 지므로 보험도 수출자가 듭니다.
    INSURANCE_EXPORTER = {"CIF", "CIP", "DAP", "DPU", "DDP"}
    for l in lines:
        if l["group"] == "insurance":
            want = "exporter" if term in INSURANCE_EXPORTER else "buyer"
        else:
            want = "exporter" if l["group"] in ICC[term] else "buyer"
        if l["payer"] != want:
            bad.append(f"{turn} {term}: {l['name']}({l['group']}) 부담이 {l['payer']} (기대 {want})")
    checked += 1
    if term == "EXW" and got["exporter_total_krw"] != 0:
        bad.append(f"{turn} EXW: 수출자 부담이 0 이 아님")
    checked += 1
    if term == "DDP" and got["buyer_total_krw"] != 0:
        bad.append(f"{turn} DDP: 바이어 부담이 0 이 아님 ({got['buyer_total_krw']:,})")
    # ⑦ 보험료는 최소금액 아래로 내려가지 않습니다
    checked += 1
    ins = next((l for l in lines if l["code"] == "insurance"), None)
    if ins and ins["krw_amount"] < C.INSURANCE_MIN_KRW - 1:
        bad.append(f"{turn}: 보험료가 최소금액보다 작음 {ins['krw_amount']}")
    # ⑧ FCL 이면 컨테이너 수만큼 곱해져야 합니다
    if sea == "FCL":
        checked += 1
        boxes = metrics.get("container_quantity") or 1
        thc = next((l for l in lines if l["code"] == "terminal_handling"), None)
        want = C.LOCAL_CHARGES_KRW["terminal_handling"]["FCL"] * boxes
        if thc and thc["original_amount"] != want:
            bad.append(f"{turn}: THC {thc['original_amount']} ≠ {want} ({boxes}대)")

print(f"■ ㉑ 물류비 견적 {ROUNDS:,}가지 · 확인 {checked:,}가지 · 문제 {len(bad)}건")
seen = {}
for b in bad:
    seen[b.split(": ", 1)[-1][:70]] = seen.get(b.split(": ", 1)[-1][:70], 0) + 1
for key, count in sorted(seen.items(), key=lambda kv: -kv[1])[:12]:
    print(f"   ★ {count:>5}회  {key}")
