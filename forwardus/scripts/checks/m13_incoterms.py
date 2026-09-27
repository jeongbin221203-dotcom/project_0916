"""⑬ 인코텀즈를 **바꿨을 때** 따라와야 할 것이 모두 따라오는가.

조건 하나를 바꾸면 위험이 넘어가는 시점·보험 의무·누가 무엇을 내는지가
한꺼번에 달라집니다. 하나라도 옛 조건으로 남으면 견적과 서류가 어긋납니다.
"""
import sys, io, random
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")
from tests._fuzz_app import build_app
from app.processors.cost_calculator import (INCOTERMS_INFO, EXPORTER_PAYS,
                                            INSURANCE_PAID_BY_EXPORTER)

ROUNDS = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
random.seed(int(sys.argv[2]) if len(sys.argv) > 2 else 1313)

# ICC Incoterms 2020. 제품 표를 보지 않고 규칙에서 따로 적었습니다.
SEA_ONLY = {"FAS", "FOB", "CFR", "CIF"}
INSURANCE_DUTY = {"CIF": "ICC(C)", "CIP": "ICC(A)"}
GROUPS = {"EXW": "E", "FCA": "F", "FAS": "F", "FOB": "F",
          "CFR": "C", "CIF": "C", "CPT": "C", "CIP": "C",
          "DAP": "D", "DPU": "D", "DDP": "D"}

app = build_app()
info = {row["code"]: row for row in INCOTERMS_INFO}
bad, checked = [], 0

# ① 표가 11개 그대로인가
checked += 1
if set(info) != set(GROUPS):
    bad.append(f"조건 목록이 다름: {sorted(set(info) ^ set(GROUPS))}")

for code, row in info.items():
    checked += 5
    # ② 해상 전용 표시
    if bool(row.get("sea_only")) != (code in SEA_ONLY):
        bad.append(f"{code}: 해상 전용 표시가 {row.get('sea_only')} (기대 {code in SEA_ONLY})")
    # ③ 보험 의무는 CIF·CIP 뿐
    # 보험 이야기는 caution·duties 에 적혀 있습니다. 화면도 그 칸을 보여 줍니다.
    text = " ".join(str(row.get(key) or "")
                    for key in ("short", "summary", "risk", "detail", "caution",
                                "seller_cost", "buyer_cost", "duties"))
    if code in INSURANCE_DUTY:
        if INSURANCE_DUTY[code] not in text:
            bad.append(f"{code}: 보험 의무({INSURANCE_DUTY[code]})를 안 적음")
        if "110" not in text:
            bad.append(f"{code}: 보험금액(매매대금의 110% 이상)을 안 적음")
    elif "ICC(" in text and "의무" in text:
        bad.append(f"{code}: 보험 의무가 없는데 ICC 를 의무처럼 적음")
    # ④ 비용 부담 — E 는 아무것도, D 는 도착지까지
    pays = EXPORTER_PAYS.get(code, set())
    if GROUPS[code] == "E" and pays:
        bad.append(f"{code}: E조건인데 수출자 부담이 있음 {sorted(pays)}")
    if GROUPS[code] == "D" and "destination" not in pays:
        bad.append(f"{code}: D조건인데 도착지 비용이 빠짐 {sorted(pays)}")
    if GROUPS[code] in ("C", "D") and "freight" not in pays:
        bad.append(f"{code}: {GROUPS[code]}조건인데 운임이 빠짐 {sorted(pays)}")
    if GROUPS[code] == "F" and "freight" in pays:
        bad.append(f"{code}: F조건인데 운임을 수출자가 냄")
    # ⑤ 보험료를 누가 내는가 — D조건은 수출자(도착지까지 위험을 짐)
    want = code in INSURANCE_DUTY or GROUPS[code] == "D"
    if (code in INSURANCE_PAID_BY_EXPORTER) != want:
        bad.append(f"{code}: 보험료 부담이 {code in INSURANCE_PAID_BY_EXPORTER} (기대 {want})")

# ⑥ 조건을 **바꿔 가며** 견적이 따라 바뀌는가
with app.app_context():
    from app.processors.cargo_calculator import calculate_cargo_lines
    from app.processors.cost_calculator import calculate_logistics_cost
    metrics = calculate_cargo_lines([{
        "product_description": "치약", "package_type": "carton", "quantity": 100,
        "length_cm": 40, "width_cm": 30, "height_cm": 25, "weight_per_package_kg": 8}])
    seen = {}
    for code in info:
        got = calculate_logistics_cost(
            transport_mode="SEA", sea_mode="LCL", incoterms=code,
            freight_usd=1200, freight_source="tariff", invoice_value_usd=25000,
            metrics=metrics, exchange_rate=1380.5)
        seen[code] = (got["exporter_total_krw"], got["buyer_total_krw"])
        checked += 2
        if got["exporter_total_krw"] + got["buyer_total_krw"] != got["total_krw"]:
            bad.append(f"{code}: 수출자 + 바이어 ≠ 총액")
    # E 가 가장 적고 DDP 가 가장 많아야 합니다
    checked += 3
    if seen["EXW"][0] != 0:
        bad.append(f"EXW 수출자 부담이 {seen['EXW'][0]:,} (0 이어야 함)")
    if seen["DDP"][1] != 0:
        bad.append(f"DDP 바이어 부담이 {seen['DDP'][1]:,} (0 이어야 함)")
    order = ["EXW", "FOB", "CFR", "CIF", "DAP", "DDP"]
    amounts = [seen[c][0] for c in order]
    if amounts != sorted(amounts):
        bad.append("조건이 뒤로 갈수록 수출자 부담이 늘어나지 않음: "
                   + " < ".join(f"{c} {seen[c][0]:,}" for c in order))
    # 같은 조건 두 번 부르면 같은 값
    for _ in range(min(ROUNDS, 500)):
        code = random.choice(list(info))
        again = calculate_logistics_cost(
            transport_mode="SEA", sea_mode="LCL", incoterms=code,
            freight_usd=1200, freight_source="tariff", invoice_value_usd=25000,
            metrics=metrics, exchange_rate=1380.5)
        checked += 1
        if (again["exporter_total_krw"], again["buyer_total_krw"]) != seen[code]:
            bad.append(f"{code}: 다시 부르니 값이 달라짐")
            break

print(f"■ ⑬ 인코텀즈 11개 · 확인 {checked:,}가지 · 문제 {len(bad)}건")
for b in bad[:12]:
    print("   ★", b)
