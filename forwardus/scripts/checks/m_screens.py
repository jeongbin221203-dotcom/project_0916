"""⑰~㉕ 화면 전수 — 기관을 하나도 부르지 않는 상태(api 사용 x)로 모두 열어 봅니다.

보는 것
  ㄱ) 500 이 나는 화면이 있는가 (기관이 없다고 터지면 안 됩니다)
  ㄴ) 기관이 없을 때 **빈 화면**이 아니라 이유를 말해 주는가
  ㄴ) 로그인하지 않으면 남의 건이 보이는가
  ㄹ) 이상한 값(없는 건 번호·글자 번호)을 넣어도 500 이 아닌가
"""
import sys, io, json, random
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")
from tests._fuzz_app import build_app
from app.extensions import db

app = build_app()
with app.app_context():
    from app.models import User, Shipment
    master = User.query.filter_by(email=app.config["MASTER_EMAIL"]).one()
    uid = master.id

    # 볼 수 있는 건 하나를 만듭니다 (스케줄을 골라야 만들어집니다)
    from app.services import planning_service
    payload = {
        "project_name": "화면 점검", "transport_mode": "SEA", "sea_mode": "LCL",
        "origin_code": "KRPUS", "destination_code": "USLAX",
        "requested_departure_date": "2026-11-02",
        "incoterms": "FOB", "currency": "USD", "invoice_value": 1250,
        "exporter_name": "주식회사 한빛무역", "exporter_address": "부산",
        "buyer": {"name": "SAMPLE CO., LTD.", "country": "US", "address": "Los Angeles"},
        "cargo": {"product_description": "치약", "hs_code": "3306100000",
                  "package_type": "carton", "quantity": 100,
                  "length_cm": 40, "width_cm": 30, "height_cm": 25,
                  "weight_per_package_kg": 8},
    }
    schedules = planning_service.search_schedules(payload)
    payload["schedule_id"] = schedules["items"][0]["schedule_id"]
    made = planning_service.create_shipment(payload, user_id=uid)
    sid = made["shipment_id"] if isinstance(made, dict) else made.shipment_id

client = app.test_client()
with client.session_transaction() as s:
    s["user_id"] = uid

# ⑰~㉕ 로 물어보신 화면들
SCREENS = [
 ("⑰ 수출요건 확인",        "GET",  f"/documents/{sid}/requirements", None),
 ("⑰ 요건 목록(api)",       "GET",  f"/documents/api/required-docs?hs=3306100000&country=US", None),
 ("⑱ 문서 자동작성",         "POST", f"/documents/{sid}/generate", {}),
 ("⑲ 관세사 전달용 자료",     "GET",  f"/documents/{sid}/customs-filing", None),
 ("⑲ 통관고유부호 조회",      "GET",  f"/documents/{sid}/customs-filing/clearance-code?business_no=124-81-00998", None),
 ("⑳ Document Center",     "GET",  f"/documents/{sid}", None),
 ("⑳ 서류 간 검증",          "POST", f"/documents/{sid}/validate", {}),
 ("㉑ 물류비 견적(화물)",      "POST", "/planning/api/cargo",
     {"items": [{"product_description": "치약", "package_type": "carton", "quantity": "100",
                 "length_cm": "40", "width_cm": "30", "height_cm": "25",
                 "weight_per_package_kg": "8"}], "container_type": "40GP"}),
 ("㉑ 환율",                "GET",  "/planning/api/exchange-rate?from=USD&to=KRW&amount=1000", None),
 ("㉑ 환율판",              "GET",  "/planning/api/fx-board", None),
 ("㉑ 관세율 요약",          "GET",  "/planning/api/tariff-summary?hs=3306100000&country=US", None),
 ("㉒ 컨테이너·통관 조회",     "GET",  "/tracking/container?number=MSKU1234567", None),
 ("㉒ 통관 진행 조회",        "GET",  f"/tracking/{sid}", None),
 ("㉓ AI Assistant",       "GET",  f"/assistant/{sid}", None),
 ("㉓ AI 묻기",             "POST", f"/assistant/{sid}/api/ask", {"question": "이 건 수출 가능성 어때요?"}),
 ("㉔ B/L 조회",            "GET",  "/tracking/container?number=HLCUBO12345678", None),
 ("㉕ 관세청 조회 · 세율",     "GET",  "/planning/api/tariff?hs=3306100000&country=US", None),
 ("㉕ 관세청 조회 · 도착국",   "GET",  "/planning/api/destination-tariff?hs=3306100000&country=US", None),
 ("㉕ 조회처 목록",          "GET",  "/lookup/sources", None),
 ("㉕ HS 조회",             "GET",  "/planning/api/hs-codes?q=치약", None),
 ("· 제출 전 점검(신고자료)",  "POST", f"/documents/{sid}/customs-filing",
     {"exporter_business_no": "124-81-00998", "customs_trade_kind": "11",
      "customs_payment_method": "LS", "country_of_origin": "KR · 대한민국"}),
]

bad, blank = [], []
print("── 기관 없이(api 사용 x) 모두 열어 봅니다 ──")
for label, method, path, body in SCREENS:
    try:
        if method == "GET":
            response = client.get(path)
        else:
            response = client.post(path, json=body) if body is not None else client.post(path)
    except Exception as error:
        bad.append(f"{label}: 죽음 {type(error).__name__} {error}")
        print(f"   ✗ {label:<26} 죽음 {type(error).__name__}")
        continue
    code = response.status_code
    text = response.get_data(as_text=True)
    mark = "✓" if code < 400 else ("△" if code < 500 else "✗")
    if code >= 500:
        bad.append(f"{label}: {code}\n{text[:400]}")
    # 기관이 없으면 **이유를 말해야** 합니다. 빈 화면은 안 됩니다.
    said = any(word in text for word in
               ("기관", "조회", "키", "받지 못", "없습니다", "확인", "준비", "설정", "error"))
    if code < 400 and len(text.strip()) < 40:
        blank.append(f"{label}: 내용이 {len(text.strip())}자뿐")
    print(f"   {mark} {label:<26} {code}  {len(text):>7,}자"
          + ("" if said or code >= 400 else "   ← 이유를 말하지 않음"))

print()
# 로그인하지 않으면 남의 건이 보이는가
anon = app.test_client()
leaks = []
for label, method, path, body in SCREENS:
    if sid not in path:
        continue
    response = anon.get(path) if method == "GET" else anon.post(path, json=body or {})
    if response.status_code < 400 and sid in response.get_data(as_text=True):
        leaks.append(f"{label} ({path})")
print(f"■ 로그인 없이 남의 건이 보이는 화면 {len(leaks)}개")
for l in leaks: print("   ★", l)

# 이상한 건 번호
odd = []
for value in ["EXP-0000-00000", "../../etc/passwd", "'; DROP TABLE x; --", "0", "x"*200, "한글"]:
    for path in ("/documents/{}", "/documents/{}/customs-filing", "/tracking/{}",
                 "/assistant/{}", "/documents/{}/requirements"):
        response = client.get(path.format(value))
        if response.status_code >= 500:
            odd.append(f"{path.format(value[:30])} → {response.status_code}")
print(f"\n■ 이상한 건 번호로 열었을 때 500 이 나는 곳 {len(odd)}개")
for o in odd[:10]: print("   ★", o)

print(f"\n■ ⑰~㉕ 화면 {len(SCREENS)}개 · 500 {len(bad)}건 · 빈 화면 {len(blank)}건")
for b in bad[:6]: print("   ★", b[:500])
for b in blank: print("   ☆", b)
