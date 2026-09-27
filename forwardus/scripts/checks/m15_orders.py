"""⑮ 3만 가지 — 적는 순서(⑫) × 인코텀즈(⑬) × 금액(⑭)을 엮습니다.

무엇을 지키나 (경우마다 다시 셉니다)
  1. 어느 순서로 적어도 네 갈래 값이 다 남는다
  2. 고른 인코텀즈가 그대로 저장되고, 해상전용 조건은 항공에서 확인을 받는다
  3. 송장 금액 == 품목 금액의 합 (표기를 흔들어도)
  4. CBM·총중량이 손으로 다시 곱한 값과 같다
"""
import sys, io, random, itertools
from decimal import ROUND_HALF_UP, Decimal

# **제품과 같은 반올림을 씁니다.**
#
# 파이썬 Decimal 의 기본은 은행가 반올림(ROUND_HALF_EVEN)이라 562.005 를
# 562.00 으로 내립니다. 그런데 제품은 상업 송장 관행인 사사오입
# (ROUND_HALF_UP)을 써서 562.01 로 올립니다 — 은행·세관이 그렇게 되셈합니다.
#
# 검사가 기본 반올림으로 금액을 만들어 보내면, 서버가 "단가 × 수량이 금액과
# 맞지 않습니다"라고 막습니다. **서버가 맞습니다.** 검사 쪽 반올림이 틀렸던
# 것이고, 2026-09-26 이후 이 검사가 계속 실패하던 원인이었습니다.
# (2026-09-27 교차 무인 검증이 찾았습니다)
CENT = Decimal("0.01")


def money(value: Decimal) -> Decimal:
    """제품과 같은 방식으로 센트 자리를 맞춥니다."""

    return value.quantize(CENT, rounding=ROUND_HALF_UP)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")
from tests._fuzz_app import build_app
from app.models import User, Shipment
from app.services import planning_service, work_draft_service as W
from app.processors.cost_calculator import INCOTERMS_INFO

ROUNDS = int(sys.argv[1]) if len(sys.argv) > 1 else 30000
app = build_app()
with app.app_context():
    uid = User.query.filter_by(email=app.config["MASTER_EMAIL"]).one().id

CODES = [row["code"] for row in INCOTERMS_INFO]
SEA_ONLY = {row["code"] for row in INCOTERMS_INFO if row.get("sea_only")}
ORDERS = list(itertools.permutations(("일정", "운송", "서류", "품목")))
MONEY = ["{:.2f}", "{:,.2f}", "{:.0f}", " {:.2f} ", "{:.3f}"]
SEA = [("KRPUS","USLAX"),("KRPUS","DEHAM"),("KRINC","CNSGH"),("KRPUS","JPYOK"),
       ("KRPUS","MXVER"),("KRPUS","VNSGN"),("KRPUS","BEANR"),("KRPUS","TRIST")]
AIR = [("ICN","LAX"),("ICN","FRA"),("PUS","NRT"),("ICN","SIN")]

random.seed(int(sys.argv[2]) if len(sys.argv) > 2 else 315)
client = app.test_client()
with client.session_transaction() as s:
    s["user_id"] = uid

bad, made, checked = [], 0, 0
with app.app_context():
    viewer = User.query.get(uid)
for round_no in range(ROUNDS):
    air = random.random() < 0.3
    code = random.choice(CODES)
    origin, dest = random.choice(AIR if air else SEA)
    order = random.choice(ORDERS)
    fmt = random.choice(MONEY)

    lines, total, cbm, weight = [], Decimal(0), Decimal(0), Decimal(0)
    for _ in range(random.randint(1, 4)):
        count = random.randint(1, 3000)
        l, w, h = (random.choice([5, 12.5, 30, 40, 76.2, 100, 118]) for _ in range(3))
        kg = random.choice([0.25, 1, 12, 33.3, 250])
        price = Decimal(str(random.choice([0.01, 3.75, 12.5, 88.88, 4999.99])))
        amount = money(price * count)
        # **적는 모양에 맞춰 단가를 도로 맞춥니다.**
        #
        # 서버는 2026-09-26 부터 단가 × 수량 = 금액 을 맞대어 봅니다(은행이
        # 그렇게 되셈하기 때문입니다). 그런데 여기서 "{:.0f}" 로 적으면 금액이
        # 8,868.75 → 8,869 가 되어 단가와 안 맞습니다. **서버가 막는 것이
        # 맞습니다.** 여기서 보려는 것은 적는 순서·인코텀즈·금액 칸이지
        # 그 규칙이 아니므로, 적을 모양대로 금액을 먼저 정하고 단가를 거기에
        # 맞춥니다. (2026-09-27)
        shown = Decimal(fmt.format(amount).replace(",", "").strip())
        if shown <= 0:
            shown = Decimal("1.00")
        amount = shown
        price = (amount / count).quantize(Decimal("0.0001"))
        amount = money(price * count)
        if Decimal(fmt.format(amount).replace(",", "").strip()) != amount:
            # 그 모양으로는 되곱해지지 않는 값입니다. 쉼표 두 자리로 적습니다.
            fmt = "{:,.2f}"
        # 서버는 **보낸 합계를 믿지 않고 품목 금액을 다시 더합니다.** 그러니
        # 검산도 화면이 적어 보낸 글자 그대로를 다시 읽어 더해야 맞습니다.
        total += Decimal(fmt.format(amount).replace(",", "").strip())
        cbm += (Decimal(str(l))/100)*(Decimal(str(w))/100)*(Decimal(str(h))/100)*count
        weight += Decimal(str(kg)) * count
        lines.append({"product_description": "치약", "hs_code": "3306100000",
                      "quantity": str(count), "package_count": str(count),
                      "package_type": "carton",
                      "length_cm": str(l), "width_cm": str(w), "height_cm": str(h),
                      "weight_per_package_kg": str(kg),
                      "gross_weight_kg": str(money(Decimal(str(kg)) * count)),
                      "net_weight_kg": str(money(Decimal(str(kg)) * count * Decimal("0.9"))),
                      "unit_price": str(price), "amount": fmt.format(amount)})

    # ── ⑫ 적는 순서를 섞어 초안에 넣습니다 ──────────────────────
    PARTS = {
        "일정": {"requested_departure_date": "2026-11-10"},
        "운송": {"transport_mode": "AIR" if air else "SEA", "sea_mode": "LCL",
               "origin_code": origin, "destination_code": dest},
        "서류": {"exporter_name": "우리회사", "buyer_name": f"B{round_no}",
               "incoterms": code, "currency": "USD"},
        "품목": {"__items__": lines},
    }
    with app.app_context():
        W.clear(viewer)
        for part in order:
            values = PARTS[part]
            W.save(viewer, {"fields": {k: v for k, v in values.items() if k != "__items__"},
                            "items": values.get("__items__") or []})
        kept = W.load(viewer) or {}
    got = kept.get("fields") or {}
    checked += 1
    for part in ("일정", "운송", "서류"):
        for key, want in PARTS[part].items():
            if got.get(key) != want:
                bad.append(f"{round_no} 순서 {'→'.join(order)}: {key}={got.get(key)!r} (기대 {want})")
    if len((kept.get("items") or [])) != len(lines):
        bad.append(f"{round_no} 순서 {'→'.join(order)}: 품목 {len(kept.get('items') or [])}줄 (기대 {len(lines)})")

    # ── 실제로 만들어 봅니다 (⑬⑭) ─────────────────────────────
    body = {"project_name": f"3만-{round_no}", "transport_mode": "AIR" if air else "SEA",
            "sea_mode": "LCL", "origin_code": origin, "destination_code": dest,
            "incoterms": code, "currency": "USD", "exporter_name": "우리회사",
            "buyer_name": f"B{round_no}", "buyer": f"B{round_no}",
            "requested_departure_date": "2026-11-10",
            "invoice_value": fmt.format(total), "items": lines}
    needs_confirm = air and code in SEA_ONLY
    if needs_confirm:
        # 확인 없이 보내면 **막혀야** 합니다.
        first = client.post("/documents/start", json=body).get_json() or {}
        checked += 1
        if first.get("success"):
            bad.append(f"{round_no}: 항공에 {code}인데 확인 없이 통과됨")
        body["incoterms_confirmed"] = "1"
    with app.app_context():
        found = planning_service.search_schedules(body)
    if found.get("items"):
        body["schedule_id"] = found["items"][0]["schedule_id"]
    answer = client.post("/documents/start", json=body).get_json() or {}
    if not answer.get("success"):
        bad.append(f"{round_no}: {code}/{'AIR' if air else 'SEA'} 못 만듦 — "
                   f"{(answer.get('message') or '')[:50]}")
        continue
    made += 1
    with app.app_context():
        ship = Shipment.query.filter_by(shipment_id=answer["data"]["shipment_id"]).one()
        checked += 4
        if ship.incoterms != code:
            bad.append(f"{round_no}: 고른 {code} 인데 저장은 {ship.incoterms}")
        if abs(Decimal(str(ship.invoice_value)) - total) > Decimal("0.01"):
            bad.append(f"{round_no}: 송장금액 {ship.invoice_value} vs 합 {total} (표기 {fmt})")
        got_cbm = Decimal(str(sum(c.total_cbm for c in ship.cargos)))
        if abs(got_cbm - cbm) > Decimal("0.02"):
            bad.append(f"{round_no}: CBM {got_cbm} vs 검산 {cbm}")
        got_kg = Decimal(str(sum(c.total_weight_kg for c in ship.cargos)))
        if abs(got_kg - weight) > Decimal("0.02"):
            bad.append(f"{round_no}: 총중량 {got_kg} vs 검산 {weight}")
    if len(bad) > 40:
        break
print(f"■ ⑮ {round_no + 1}가지 · 만든 건 {made} · 확인 {checked}가지 · 문제 {len(bad)}건")
for b in bad[:20]: print("   ★", b)
