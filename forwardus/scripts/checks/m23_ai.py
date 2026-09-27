"""㉓ AI Assistant — 수출 가능성 판단 · 비용·수익성 해석.

AI 키가 없는 상태(api 사용 x)에서도 답이 나와야 하고, 무엇보다 **인코텀즈별
수출자 부담**이 ICC 2020 표와 맞아야 합니다. 여기가 틀리면 견적이 틀립니다.
"""
import sys, io, random
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")
from tests._fuzz_app import build_app
from app.services import planning_service, assistant_service as A
from app.processors.cost_calculator import EXPORTER_PAYS

# ICC Incoterms 2020 A9/B9 비용 배분. 손으로 옮겨 적은 기준표입니다.
#   origin      수출지 비용 (수출통관 · 터미널 · 반입)
#   freight     국제운임
#   insurance   적하보험 (CIF·CIP 만 매도인 의무)
#   destination 도착지 비용 (양하 · 터미널)
#   import      수입통관 · 관세 (DDP 만)
ICC = {
    "EXW": set(),
    "FCA": {"origin"},
    "FAS": {"origin"},
    "FOB": {"origin"},
    "CFR": {"origin", "freight"},
    "CIF": {"origin", "freight", "insurance"},
    "CPT": {"origin", "freight"},
    "CIP": {"origin", "freight", "insurance"},
    "DAP": {"origin", "freight", "destination"},
    "DPU": {"origin", "freight", "destination"},
    "DDP": {"origin", "freight", "destination", "import"},
}
CATEGORIES = {"Origin Charge": "origin", "Customs": "origin", "Freight": "freight",
              "Insurance": "insurance", "Destination Charge": "destination"}

bad, checked = [], 0

# ① 표가 ICC 와 같은가
for term, want in ICC.items():
    checked += 1
    got = EXPORTER_PAYS.get(term)
    if got != want:
        bad.append(f"{term}: 우리 표 {sorted(got or [])} ≠ ICC {sorted(want)}")
for term in EXPORTER_PAYS:
    checked += 1
    if term not in ICC:
        bad.append(f"{term}: ICC 2020 에 없는 조건")

# ② 조건 × 비용 항목을 모두 맞대어 봅니다
INSURANCE_EXPORTER = {"CIF", "CIP", "DAP", "DPU", "DDP"}
for term in ICC:
    for category, group in CATEGORIES.items():
        checked += 1
        # 적하보험료는 ICC 의무 표가 아니라 "누가 내는가"로 봅니다.
        want = (term in INSURANCE_EXPORTER if group == "insurance"
                else group in ICC[term])
        got = A._exporter_pays(term, category)
        if got != want:
            bad.append(f"{term} × {category}: 우리 {got} ≠ ICC {want}")
    # 모르는 항목은 수출자 부담이 아니어야 합니다 (지어내면 안 됩니다)
    checked += 1
    if A._exporter_pays(term, "Unknown Charge"):
        bad.append(f"{term}: 모르는 비용 항목을 수출자 부담으로 셈함")

# ③ 실제 건으로 돌려 봅니다 — AI 키 없이
app = build_app()
ROUNDS = int(sys.argv[1]) if len(sys.argv) > 1 else 300
random.seed(int(sys.argv[2]) if len(sys.argv) > 2 else 2323)
QUESTIONS = ["이 건 수출 가능성 어때요?", "비용이 왜 이렇게 나왔나요?", "수익성 좀 봐줘",
             "납기 맞출 수 있나요?", "현금흐름 알려줘", "", "   ", "ㅁㄴㅇㄹ",
             "a" * 900, "<script>x</script>", "🚢", "관세 얼마예요?"]
with app.app_context():
    from app.models import User, Shipment
    uid = User.query.filter_by(email=app.config["MASTER_EMAIL"]).one().id
    for turn in range(ROUNDS):
        term = random.choice(list(ICC))
        mode = random.choice(["SEA", "AIR"])
        p = {"project_name": f"조수 {turn}", "transport_mode": mode,
             "sea_mode": "LCL" if mode == "SEA" else None,
             "origin_code": "KRPUS" if mode == "SEA" else "ICN",
             "destination_code": "USLAX" if mode == "SEA" else "LAX",
             "requested_departure_date": "2026-11-02",
             "incoterms": term, "incoterms_confirmed": "1", "currency": "USD",
             "invoice_value": 25000, "exporter_name": "한빛무역", "exporter_address": "부산",
             "buyer": {"name": "SAMPLE CO.", "country": "US"},
             "cargo": {"product_description": "치약", "hs_code": "3306100000",
                       "package_type": "carton", "quantity": random.choice([10, 500, 3000]),
                       "length_cm": 40, "width_cm": 30, "height_cm": 25,
                       "weight_per_package_kg": random.choice([0.5, 8, 60])}}
        try:
            found = planning_service.search_schedules(p)
            p["schedule_id"] = found["items"][0]["schedule_id"]
            made = planning_service.create_shipment(p, user_id=uid)
        except Exception as error:
            bad.append(f"{turn} {term}/{mode}: 건을 못 만듦 {type(error).__name__} {error}")
            continue
        sh = Shipment.query.filter_by(
            shipment_id=made["shipment_id"] if isinstance(made, dict) else made.shipment_id).one()

        for name, call in (("수출 가능성", A.export_readiness), ("비용 해석", A.cost_explanation),
                           ("예외 안내", A.exception_guide), ("현금흐름", A.cash_flow)):
            checked += 1
            try:
                out = call(sh)
            except Exception as error:
                bad.append(f"{turn} {term}: {name} 죽음 {type(error).__name__} {error}")
                continue
            # 예외 안내는 available 대신 has_exception 을 씁니다 (설계가 다릅니다)
            key = "has_exception" if name == "예외 안내" else "available"
            if not isinstance(out, dict) or key not in out:
                bad.append(f"{turn} {term}: {name} 에 '{key}' 가 없음")

        # 비용 해석이 낸 수출자 부담이 표와 맞는가
        checked += 1
        out = A.cost_explanation(sh)
        if out.get("available"):
            # 적하보험료만 규칙이 다릅니다 — 의무가 아니라 **누가 내는가**.
            # D조건은 수출자가 도착지까지 위험을 지므로 보험도 수출자가 듭니다.
            INSURANCE_EXPORTER = {"CIF", "CIP", "DAP", "DPU", "DDP"}
            want = sum(c.krw_amount for c in sh.costs
                       if (term in INSURANCE_EXPORTER
                           if CATEGORIES.get(c.category) == "insurance"
                           else CATEGORIES.get(c.category) in ICC[term]))
            if out["exporter_cost_krw"] != want:
                bad.append(f"{turn} {term}: 수출자 부담 {out['exporter_cost_krw']:,} ≠ {want:,}")
            # 수출자 부담이 총액을 넘으면 안 됩니다
            if out["exporter_cost_krw"] > out["total_krw"]:
                bad.append(f"{turn} {term}: 수출자 부담이 총액보다 큼")
            if term == "EXW" and out["exporter_cost_krw"] != 0:
                bad.append(f"{turn} EXW: 수출자 부담이 0 이 아님 ({out['exporter_cost_krw']:,})")

        # 질문에 답하다 죽지 않는가 (AI 키 없이)
        for question in random.sample(QUESTIONS, 4):
            checked += 1
            try:
                A.answer_question(sh, question)
            except Exception as error:
                from app.services import ServiceError
                from app.validators import ValidationError
                if not isinstance(error, (ServiceError, ValidationError)):
                    bad.append(f"{turn} {term}: '{question[:20]}' 에서 죽음 "
                               f"{type(error).__name__} {error}")

print(f"■ ㉓ AI Assistant · 건 {ROUNDS:,} · 확인 {checked:,}가지 · 문제 {len(bad)}건")
seen = {}
for b in bad:
    seen[b.split(": ", 1)[-1][:70]] = seen.get(b.split(": ", 1)[-1][:70], 0) + 1
for key, count in sorted(seen.items(), key=lambda kv: -kv[1])[:12]:
    print(f"   ★ {count:>5}회  {key}")
