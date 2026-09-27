"""⑫ 뒤에서 앞으로 — 서류부터 쓰고 견적으로 갈 때 값이 그대로 옮겨지는가.

앞에서부터 쓰는 사람만 있는 게 아닙니다. 서류를 먼저 쓰고 나중에 운임을 보거나,
견적을 내다 말고 서류로 갔다 다시 오기도 합니다. 그때 적어 둔 값이 사라지거나
엉뚱하게 바뀌면, 사람은 다시 적으면서 이번엔 틀리게 적습니다.
"""
import sys, io, random, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")
from tests._fuzz_app import build_app
from app.services import work_draft_service as W

ROUNDS = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
random.seed(int(sys.argv[2]) if len(sys.argv) > 2 else 1212)

app = build_app()
bad, checked = [], 0

# 적는 차례를 흔듭니다. 어느 순서로 적어도 끝에 남는 값은 같아야 합니다.
STEPS = {
    "일정":   {"requested_departure_date": "2026-11-02"},
    "운송":   {"transport_mode": "SEA", "sea_mode": "LCL",
              "origin_code": "KRPUS", "origin_name": "Busan",
              "destination_code": "USLAX", "destination_name": "Los Angeles"},
    "조건":   {"incoterms": "FOB", "currency": "USD"},
    "수출자": {"exporter_name": "주식회사 한빛무역", "exporter_address": "부산광역시 중구"},
    "바이어": {"buyer_name": "SAMPLE CO., LTD.", "buyer_country": "US",
              "buyer_address": "Los Angeles, CA"},
    "신용장": {"lc_no": "LC-2026-0001", "lc_latest_shipment_date": "2026-11-20",
              "lc_expiry_date": "2026-12-10", "lc_presentation_days": "21"},
    "이름":   {"project_name": "미국_치약_20261102"},
}
def make_items(count):
    names = ["치약", "샴푸", "비누", "칫솔", "수건"]
    return [{"product_description": names[i % len(names)], "hs_code": "3306100000",
             "package_type": "carton", "quantity": str(10 * (i + 1)),
             "length_cm": "40", "width_cm": "30", "height_cm": "25",
             "weight_per_package_kg": "8", "unit_price": "12.50",
             "amount": f"{12.5 * 10 * (i + 1):.2f}"} for i in range(count)]
WANT = {k: v for step in STEPS.values() for k, v in step.items()}

with app.app_context():
    from app.models import User
    viewer = User.query.first()
    for turn in range(ROUNDS):
        order = list(STEPS)
        random.shuffle(order)                      # 어느 칸부터 적을지 매번 다르게
        W.clear(viewer)
        # 품목을 언제 적는지도 흔듭니다 (맨 앞·중간·맨 뒤)
        item_at = random.randint(0, len(order))
        items = make_items(random.randint(1, 5))
        for index, name in enumerate(order):
            if index == item_at:
                W.save(viewer, {"fields": {}, "items": items})
            W.save(viewer, {"fields": STEPS[name], "items": []})
        if item_at >= len(order):
            W.save(viewer, {"fields": {}, "items": items})

        back = W.load(viewer)
        fields = back.get("fields") or {}
        checked += len(WANT) + 2
        for key, value in WANT.items():
            if fields.get(key) != value:
                bad.append(f"{turn} [{'→'.join(order)}]: {key} = {fields.get(key)!r} "
                           f"(기대 {value!r})")
                break
        if len(back.get("items") or []) != len(items):
            bad.append(f"{turn}: 품목이 {len(back.get('items') or [])}줄 "
                       f"({len(items)}줄이어야 함)")

        # 운송 계획 화면 모양으로 넘겼을 때
        checked += 4
        try:
            plan = W.planning_prefill(viewer)
        except Exception as error:
            bad.append(f"{turn}: 견적 화면으로 못 넘김 {type(error).__name__} {error}")
            continue
        if (plan.get("origin") or {}).get("code") != "KRPUS":
            bad.append(f"{turn}: 출발지가 안 넘어감 {plan.get('origin')}")
        if (plan.get("destination") or {}).get("code") != "USLAX":
            bad.append(f"{turn}: 도착지가 안 넘어감 {plan.get('destination')}")
        if plan.get("incoterms") != "FOB":
            bad.append(f"{turn}: 인코텀즈가 안 넘어감 {plan.get('incoterms')!r}")
        lc = plan.get("lc") or {}
        if lc and lc.get("expiry") not in ("2026-12-10", None):
            bad.append(f"{turn}: 신용장 유효기일이 어긋남 {lc.get('expiry')!r}")
        # 품목이 견적 화면으로 넘어가는가.
        # 첫 줄은 fields 에 평평하게, 나머지는 cargo_lines 에 담깁니다.
        checked += 3
        first = plan.get("fields") or {}
        rest = plan.get("cargo_lines") or []
        if first.get("product_description") != items[0]["product_description"]:
            bad.append(f"{turn}: 첫 품목이 안 넘어감 "
                       f"{first.get('product_description')!r}")
        if len(rest) != len(items) - 1:
            bad.append(f"{turn}: 나머지 품목이 {len(rest)}줄 "
                       f"({len(items) - 1}줄이어야 함)")
        for index, row in enumerate(rest):
            if row.get("product_description") != items[index + 1]["product_description"]:
                bad.append(f"{turn}: 품목 순서가 바뀜")
                break
        # 송장 금액은 품목 금액의 합이어야 합니다
        checked += 1
        want_total = sum(float(row["amount"]) for row in items)
        got_total = float(str(first.get("invoice_value") or 0).replace(",", ""))
        if abs(got_total - want_total) > 0.01:
            bad.append(f"{turn}: 송장 금액 {got_total} ≠ 품목 합 {want_total}")

print(f"■ ⑫ 역순·섞어 적기 {ROUNDS:,}회 · 확인 {checked:,}가지 · 문제 {len(bad)}건")
seen = {}
for b in bad:
    seen[b.split(": ", 1)[-1][:70]] = seen.get(b.split(": ", 1)[-1][:70], 0) + 1
for key, count in sorted(seen.items(), key=lambda kv: -kv[1])[:10]:
    print(f"   ★ {count:>6}회  {key}")
