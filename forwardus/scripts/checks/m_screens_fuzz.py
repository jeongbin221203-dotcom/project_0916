"""⑰~㉕ 화면 · 붙는 값(query)을 크게 흔듭니다. 500 이 나면 이용자는 화면을 못 씁니다."""
import sys, io, random, urllib.parse
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")
from tests._fuzz_app import build_app

ROUNDS = int(sys.argv[1]) if len(sys.argv) > 1 else 10000
random.seed(int(sys.argv[2]) if len(sys.argv) > 2 else 1725)

app = build_app()
with app.app_context():
    from app.models import User
    from app.services import planning_service
    uid = User.query.filter_by(email=app.config["MASTER_EMAIL"]).one().id
    payload = {"project_name": "흔들기", "transport_mode": "SEA", "sea_mode": "LCL",
               "origin_code": "KRPUS", "destination_code": "USLAX",
               "requested_departure_date": "2026-11-02", "incoterms": "FOB",
               "currency": "USD", "invoice_value": 1250,
               "exporter_name": "주식회사 한빛무역", "exporter_address": "부산",
               "buyer": {"name": "SAMPLE CO., LTD.", "country": "US"},
               "cargo": {"product_description": "치약", "hs_code": "3306100000",
                         "package_type": "carton", "quantity": 100, "length_cm": 40,
                         "width_cm": 30, "height_cm": 25, "weight_per_package_kg": 8}}
    s = planning_service.search_schedules(payload)
    payload["schedule_id"] = s["items"][0]["schedule_id"]
    made = planning_service.create_shipment(payload, user_id=uid)
    sid = made["shipment_id"] if isinstance(made, dict) else made.shipment_id

client = app.test_client()
with client.session_transaction() as s:
    s["user_id"] = uid

JUNK = ["", " ", "0", "-1", "999999999999999", "3306100000", "33061", "330610000000",
        "치약", "toothpaste", "ABCDEFGHIJ", "US", "USA", "us", "ZZ", "대한민국",
        "<script>alert(1)</script>", "'; DROP TABLE x; --", "../../etc/passwd",
        "%00", "​", "🚢", "가" * 500, "a" * 2000, "1,2,3", "3306100000,3304990000",
        "null", "None", "true", "[]", "{}", "NaN", "Infinity", "1e999", "-0.0"]

GET_PATHS = [
    ("⑰ 요건 목록",   "/documents/api/required-docs", ["hs", "product", "country", "country_name", "dangerous", "ai"]),
    ("㉑ 환율",        "/planning/api/exchange-rate", ["from", "to", "amount"]),
    ("㉑ 관세율 요약",  "/planning/api/tariff-summary", ["hs", "country"]),
    ("㉕ 관세율",      "/planning/api/tariff", ["hs", "country"]),
    ("㉕ 도착국 관세율", "/planning/api/destination-tariff", ["hs", "country"]),
    ("㉕ HS 조회",     "/planning/api/hs-codes", ["q", "country", "order"]),
    ("㉕ 지역 조회",    "/planning/api/locations", ["q", "mode", "country"]),
    ("㉕ UN번호",      "/planning/api/un-numbers", ["q"]),
    ("㉕ UN/LOCODE",  "/planning/api/unlocode", ["q", "country"]),
    ("㉒ 컨테이너 조회", "/tracking/container", ["number", "carrier"]),
    ("㉑ 소요일",      "/planning/api/transit-estimate", ["origin", "destination", "mode"]),
    ("⑲ 통관고유부호",  f"/documents/{sid}/customs-filing/clearance-code", ["business_no"]),
    ("㉕ 조회처 점검",  "/lookup/sources/check", ["only"]),
    ("㉑ 나라 목록",    "/planning/api/countries", ["q"]),
    ("㉑ 위험물",      "/planning/api/dangerous-goods", ["dg_class", "un_number"]),
]

POST_PATHS = [
    ("㉑ 물류비 견적",  "/planning/api/cargo"),
    ("⑳ 서류 간 검증",  f"/documents/{sid}/validate"),
    ("㉓ AI 묻기",     f"/assistant/{sid}/api/ask"),
    ("㉑ 스케줄",      "/planning/api/schedules"),
    ("㉑ 출항 확인",    "/planning/api/departure-check"),
]

bad, checked = [], 0
for turn in range(ROUNDS):
    label, path, keys = random.choice(GET_PATHS)
    query = urllib.parse.urlencode(
        {key: random.choice(JUNK) for key in random.sample(keys, random.randint(0, len(keys)))})
    url = f"{path}?{query}" if query else path
    checked += 1
    try:
        response = client.get(url)
    except Exception as error:
        bad.append(f"{label}: 죽음 {type(error).__name__} {error} ← {url[:120]}")
        continue
    if response.status_code >= 500 and response.status_code != 502:
        bad.append(f"{label}: {response.status_code} ← {url[:140]}")

    if turn % 3 == 0:
        label, path = random.choice(POST_PATHS)
        body = {key: random.choice(JUNK) for key in
                random.sample(["items", "cargo", "question", "hs_code", "origin_code",
                               "destination_code", "transport_mode", "incoterms",
                               "quantity", "amount", "currency", "date"],
                              random.randint(0, 6))}
        if random.random() < 0.3:
            body = random.choice([[], "", None, {"items": []}, {"items": [{}]}, 12345])
        checked += 1
        try:
            response = client.post(path, json=body)
        except Exception as error:
            bad.append(f"{label}: 죽음 {type(error).__name__} {error}")
            continue
        if response.status_code >= 500 and response.status_code != 502:
            bad.append(f"{label}: {response.status_code} ← {str(body)[:120]}")

print(f"■ ⑰~㉕ 화면 흔들기 {ROUNDS:,}회 · 확인 {checked:,}가지 · 500 {len(bad)}건")
seen = {}
for b in bad:
    seen[b.split(" ← ")[0]] = seen.get(b.split(" ← ")[0], 0) + 1
for key, count in sorted(seen.items(), key=lambda kv: -kv[1])[:12]:
    print(f"   ★ {count:>5}회  {key}")
if bad:
    print("\n   보기:", bad[0][:300])
