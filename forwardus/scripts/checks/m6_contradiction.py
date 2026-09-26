"""⑥ 칸마다는 맞는데 **서로 모순되는** 입력이 그대로 통과하는가.

가장 무서운 종류입니다. 값 하나하나는 규칙을 지키고 있어 아무도 못 막는데,
모아 놓고 보면 말이 안 됩니다. 그대로 서류가 되고 세관에 갑니다.

보는 조합
  · 순중량 > 총중량                    (물건보다 포장이 가벼울 수는 없습니다)
  · ETA < ETD                          (도착이 출발보다 빠름)
  · 유효기일 < 최종선적일               (실으라는 날보다 서류 마감이 빠름)
  · 바이어 나라 ≠ 도착항 나라           (미국 바이어인데 로테르담행)
  · 해상 전용 조건 + 항공               (FOB/AIR)
  · 출발지 = 도착지
  · LCL 인데 200 CBM                   (컨테이너로 가야 합니다)
  · 항공인데 30톤                      (한 대에 안 실립니다)
  · 금액 ≠ 단가 × 수량
  · 송장 금액 ≠ 품목 금액의 합
  · 밀도가 물의 20배                   (금보다 무거운 화물)
  · 위험물인데 등급 없음
  · 출발 희망일이 과거
"""
import sys, io, random
from datetime import date, timedelta
from decimal import Decimal
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")
from tests._fuzz_app import build_app
from app.services import planning_service, ServiceError
from app.validators import ValidationError

ROUNDS = int(sys.argv[1]) if len(sys.argv) > 1 else 10000
random.seed(int(sys.argv[2]) if len(sys.argv) > 2 else 606)
TODAY = date(2026, 9, 26)


def base():
    return {"project_name": "모순 점검", "transport_mode": "SEA", "sea_mode": "LCL",
            "origin_code": "KRPUS", "destination_code": "USLAX",
            "requested_departure_date": (TODAY + timedelta(days=20)).isoformat(),
            "incoterms": "FOB", "currency": "USD", "invoice_value": 1250,
            "exporter_name": "주식회사 한빛무역", "exporter_address": "부산",
            "buyer": {"name": "SAMPLE CO., LTD.", "country": "US", "address": "LA"},
            "cargo": {"product_description": "치약", "hs_code": "3306100000",
                      "package_type": "carton", "quantity": 100, "length_cm": 40,
                      "width_cm": 30, "height_cm": 25, "weight_per_package_kg": 8,
                      "unit_price": "12.50", "amount": "1250.00"}}


# (이름, 어떻게 망가뜨리나, 반드시 막아야 하는가)
CASES = [
 ("순중량 > 총중량", lambda p: p["cargo"].update(net_weight_kg=999999), True),
 ("도착이 출발보다 빠름", lambda p: p.update(buyer_required_date=(TODAY - timedelta(days=5)).isoformat()), False),
 ("바이어 나라 ≠ 도착항 나라", lambda p: p["buyer"].update(country="DE"), False),
 ("해상 전용 조건 + 항공", lambda p: p.update(transport_mode="AIR", sea_mode=None,
                                          origin_code="ICN", destination_code="LAX",
                                          incoterms="FOB"), True),
 ("출발지 = 도착지", lambda p: p.update(destination_code="KRPUS"), True),
 ("LCL 인데 200 CBM", lambda p: p["cargo"].update(quantity=9999, length_cm=200,
                                                  width_cm=200, height_cm=200), False),
 ("항공인데 아주 무거움", lambda p: (p.update(transport_mode="AIR", sea_mode=None,
                                         origin_code="ICN", destination_code="LAX",
                                         incoterms="FCA"),
                                 p["cargo"].update(quantity=3000, weight_per_package_kg=999)), False),
 ("금액 ≠ 단가 × 수량", lambda p: p["cargo"].update(unit_price="12.50", amount="99999.00"), True),
 ("밀도가 물의 20배", lambda p: p["cargo"].update(length_cm=10, width_cm=10, height_cm=10,
                                               weight_per_package_kg=20), False),
 ("위험물인데 등급 없음", lambda p: p["cargo"].update(is_dangerous=True, dg_class=""), False),
 ("출발 희망일이 과거", lambda p: p.update(requested_departure_date=(TODAY - timedelta(days=30)).isoformat()), False),
 ("수량 0", lambda p: p["cargo"].update(quantity=0), True),
 ("치수 0", lambda p: p["cargo"].update(height_cm=0), True),
 ("통화가 목록 밖", lambda p: p.update(currency="ZZZ"), True),
 ("인코텀즈가 목록 밖", lambda p: p.update(incoterms="ZZZ"), True),
 ("바이어 이름 없음", lambda p: p["buyer"].update(name=""), True),
 ("항공인데 sea_mode 가 붙음", lambda p: p.update(transport_mode="AIR", sea_mode="FCL",
                                              origin_code="ICN", destination_code="LAX",
                                              incoterms="FCA"), False),
 ("해상인데 공항 코드", lambda p: p.update(origin_code="ICN", destination_code="LAX"), False),
 ("항공인데 항구 코드", lambda p: p.update(transport_mode="AIR", sea_mode=None,
                                       incoterms="FCA"), False),
]

app = build_app()
blocked = {name: 0 for name, _, _ in CASES}
passed = {name: 0 for name, _, _ in CASES}
warned = {name: 0 for name, _, _ in CASES}
bad, checked = [], 0
with app.app_context():
    from app.models import User
    uid = User.query.filter_by(email=app.config["MASTER_EMAIL"]).one().id
    for turn in range(ROUNDS):
        name, spoil, must_block = random.choice(CASES)
        payload = base()
        spoil(payload)
        checked += 1
        try:
            found = planning_service.search_schedules(payload)
            if not found.get("items"):
                blocked[name] += 1
                continue
            payload["schedule_id"] = found["items"][0]["schedule_id"]
            made = planning_service.create_shipment(payload, user_id=uid)
        except (ValidationError, ServiceError):
            blocked[name] += 1
            continue
        except Exception as error:
            bad.append(f"{name}: 죽음 {type(error).__name__} {error}")
            continue
        passed[name] += 1
        # 통과했다면 **경고라도** 있어야 합니다
        sid = made["shipment_id"] if isinstance(made, dict) else made.shipment_id
        from app.models import Shipment
        sh = Shipment.query.filter_by(shipment_id=sid).one()
        notes = " ".join(filter(None, [
            getattr(sh.cargo, "density_warning", "") if sh.cargo else "",
            getattr(sh.cargo, "units_warning", "") if sh.cargo else "",
            getattr(sh.cargo, "dg_warning", "") if sh.cargo else "",
            getattr(sh, "incoterms_warning", "") or "",
        ]))
        if notes.strip():
            warned[name] += 1

print(f"■ ⑥ 서로 모순되는 입력 {ROUNDS:,}회 · {len(CASES)}가지 · 죽음 {len(bad)}건")
print()
print(f"   {'무엇이 모순인가':<26}{'막음':>7}{'통과':>7}{'통과 중 경고':>12}   판정")
for name, _, must_block in CASES:
    b, p, w = blocked[name], passed[name], warned[name]
    if must_block:
        verdict = "OK" if p == 0 else "★ 막아야 하는데 통과"
    else:
        verdict = "OK(경고)" if p == 0 or w == p else ("OK" if p == 0 else "☆ 말없이 통과")
    print(f"   {name:<26}{b:>7}{p:>7}{w:>12}   {verdict}")
for b in bad[:6]: print("   ★", b)
