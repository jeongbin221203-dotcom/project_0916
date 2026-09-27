"""모든 화면을 실제로 그려 봅니다. 문법이 맞아도 그릴 때 터집니다."""
import sys, io, random
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")
from tests._fuzz_app import build_app

app = build_app()
with app.app_context():
    from app.models import User
    from app.services import planning_service, document_service
    uid = User.query.filter_by(email=app.config["MASTER_EMAIL"]).one().id
    # 서류까지 만들어 둔 건 하나
    payload = {"project_name": "전체 점검", "transport_mode": "SEA", "sea_mode": "LCL",
               "origin_code": "KRPUS", "destination_code": "USLAX",
               "requested_departure_date": "2026-11-02", "incoterms": "FOB",
               "currency": "USD", "invoice_value": 1250,
               "exporter_name": "주식회사 한빛무역", "exporter_address": "부산광역시",
               "buyer": {"name": "SAMPLE CO., LTD.", "country": "US", "address": "Los Angeles"},
               "cargo": {"product_description": "치약", "hs_code": "3306100000",
                         "package_type": "carton", "quantity": 100, "length_cm": 40,
                         "width_cm": 30, "height_cm": 25, "weight_per_package_kg": 8}}
    found = planning_service.search_schedules(payload)
    payload["schedule_id"] = found["items"][0]["schedule_id"]
    made = planning_service.create_shipment(payload, user_id=uid)
    sid = made["shipment_id"] if isinstance(made, dict) else made.shipment_id
    from app.models import Shipment
    shipment = Shipment.query.filter_by(shipment_id=sid).one()
    document_service.generate_documents(shipment)
    doc_types = [d.doc_type for d in shipment.documents]

client = app.test_client()
with client.session_transaction() as s:
    s["user_id"] = uid
anon = app.test_client()

FILL = {"shipment_id": sid, "doc_type": doc_types[0] if doc_types else "commercial_invoice",
        "kind": "commercial_invoice", "source_id": "1", "draft_id": "1",
        "document_id": "1", "step": "read"}

gets, bad, empty, checked = [], [], [], 0
for rule in app.url_map.iter_rules():
    if rule.endpoint.startswith("static") or "GET" not in rule.methods:
        continue
    path = str(rule)
    ok = True
    for arg in rule.arguments:
        if arg not in FILL:
            ok = False
            break
        path = path.replace(f"<{arg}>", str(FILL[arg])).replace(f"<int:{arg}>", str(FILL[arg]))
    if not ok or "<" in path:
        bad.append(f"[못 채움] {rule} (인자 {sorted(rule.arguments)})")
        continue
    gets.append((rule.endpoint, path))

print("── 로그인한 채로 모든 GET 화면을 그립니다")
for endpoint, path in sorted(gets):
    checked += 1
    try:
        response = client.get(path)
    except Exception as error:
        bad.append(f"[죽음] {path}  {type(error).__name__} {error}")
        print(f"   ✗ {endpoint:<34} 죽음 {type(error).__name__}")
        continue
    code = response.status_code
    size = len(response.get_data())
    mark = "✓" if code < 400 else ("△" if code < 500 else "✗")
    if code >= 500:
        bad.append(f"[{code}] {path}\n{response.get_data(as_text=True)[:300]}")
    # HTML 화면인데 내용이 거의 없으면 빈 화면입니다
    if code == 200 and response.mimetype == "text/html" and size < 2000:
        empty.append(f"{path} ({size:,}바이트)")
    print(f"   {mark} {endpoint:<34} {code}  {size:>8,}바이트")

# 로그인 없이 열었을 때 내용이 새는가
leaks = []
for endpoint, path in gets:
    if sid not in path:
        continue
    checked += 1
    response = anon.get(path)
    body = response.get_data(as_text=True)
    if response.status_code == 200 and ("주식회사 한빛무역" in body or "SAMPLE CO." in body):
        leaks.append(f"{path}")

print(f"\n■ 화면 그리기 {len(gets)}개 · 확인 {checked}가지")
print(f"   500·죽음 {len([b for b in bad if not b.startswith('[못 채움]')])}건"
      f" · 인자를 못 채운 주소 {len([b for b in bad if b.startswith('[못 채움]')])}개"
      f" · 빈 화면 {len(empty)}건 · 로그인 없이 새는 화면 {len(leaks)}건")
for b in bad[:12]: print("   ★", b[:400])
for e in empty[:10]: print("   ☆ 빈 화면:", e)
for l in leaks: print("   ★ 유출:", l)
