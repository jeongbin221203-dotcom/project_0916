"""같은 일을 두 번 하거나 두 창에서 동시에 할 때.

여태 한 번도 안 본 자리입니다.
  · [만들기]를 두 번 누르면 건이 둘 생기는가 (둘 다 세관에 갈 수 있습니다)
  · 두 창에서 임시저장하면 나중 것이 앞 것을 통째로 덮는가
  · 같은 서류를 두 번 만들면 두 장이 되는가
  · 확정(final)한 서류를 다시 고칠 수 있는가
  · 같은 파일을 두 번 올리면 두 줄이 되는가
"""
import sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")
from tests._fuzz_app import build_app
from app.extensions import db

app = build_app()
bad, checked = [], 0
with app.app_context():
    from app.models import User, Shipment
    uid = User.query.filter_by(email=app.config["MASTER_EMAIL"]).one().id

client = app.test_client()
with client.session_transaction() as s:
    s["user_id"] = uid

PAYLOAD = {
    "project_name": "동시 점검", "transport_mode": "SEA", "sea_mode": "LCL",
    "origin_code": "KRPUS", "destination_code": "USLAX",
    "requested_departure_date": "2026-11-02", "incoterms": "FOB", "currency": "USD",
    "invoice_value": 1250, "exporter_name": "주식회사 한빛무역", "exporter_address": "부산",
    "buyer_name": "SAMPLE CO., LTD.", "buyer_country": "US",
    "items": [{"product_description": "치약", "hs_code": "3306100000",
               "package_type": "carton", "quantity": "100", "length_cm": "40",
               "width_cm": "30", "height_cm": "25", "weight_per_package_kg": "8",
               "unit_price": "12.50", "amount": "1250.00"}],
}

# 스케줄을 먼저 고릅니다 (화면도 그렇게 합니다)
found = client.post("/planning/api/schedules", json={
    **PAYLOAD, "cargo": {"items": PAYLOAD["items"]}}).get_json()
PAYLOAD["schedule_id"] = (found.get("data") or {})["items"][0]["schedule_id"]

# ① [만들기]를 두 번 — 건이 둘 생기는가
with app.app_context():
    from app.models import Shipment
    before = Shipment.query.count()
first = client.post("/documents/start", json=PAYLOAD)
second = client.post("/documents/start", json=PAYLOAD)
with app.app_context():
    after = Shipment.query.count()
checked += 1
made = after - before
print(f"① [만들기] 두 번 → 건이 {made}개 생김 "
      f"(첫 번째 {first.status_code} · 두 번째 {second.status_code})")
if made > 1:
    bad.append(f"[만들기]를 두 번 누르면 건이 {made}개 생깁니다")

sid = (first.get_json() or {}).get("data", {}).get("shipment_id") \
      or (first.get_json() or {}).get("shipment_id", "")
if not sid:
    with app.app_context():
        sid = Shipment.query.order_by(Shipment.id.desc()).first().shipment_id
print(f"   만든 건: {sid}")

# ② 두 창에서 임시저장 — 나중 것이 앞 것을 통째로 덮는가
client.put("/api/work-draft", json={"fields": {"exporter_name": "가나무역",
                                               "origin_code": "KRPUS"}, "items": []})
client.put("/api/work-draft", json={"fields": {"buyer_name": "BUYER B"}, "items": []})
draft = client.get("/api/work-draft").get_json()["data"]
checked += 2
kept = draft.get("fields", {})
print(f"\n② 두 창에서 임시저장 → 남은 칸 {sorted(kept)}")
if "exporter_name" not in kept:
    bad.append("두 번째 저장이 첫 번째가 적은 칸을 지웠습니다")
if kept.get("buyer_name") != "BUYER B":
    bad.append("두 번째 저장이 안 들어갔습니다")

# ③ 같은 서류를 두 번 만들면
r1 = client.post(f"/documents/{sid}/generate", json={})
r2 = client.post(f"/documents/{sid}/generate", json={})
with app.app_context():
    sh = Shipment.query.filter_by(shipment_id=sid).one()
    kinds = [d.doc_type for d in sh.documents]
checked += 1
dupes = [k for k in set(kinds) if kinds.count(k) > 1]
print(f"\n③ 자동작성 두 번 → 서류 {len(kinds)}장 · 종류 {len(set(kinds))}가지")
if dupes:
    bad.append(f"같은 서류가 두 장 생깁니다: {dupes}")

# ④ 확정한 서류를 다시 고칠 수 있는가
with app.app_context():
    sh = Shipment.query.filter_by(shipment_id=sid).one()
    kind = sh.documents[0].doc_type if sh.documents else "commercial_invoice"
fin = client.post(f"/documents/{sid}/{kind}/finalize", json={})
with app.app_context():
    sh = Shipment.query.filter_by(shipment_id=sid).one()
    doc = next((d for d in sh.documents if d.doc_type == kind), None)
    status_after_final = getattr(doc, "status", "?")
edit = client.post(f"/documents/{sid}/{kind}",
                   data={"exporter": "바꿔치기 주식회사"})
with app.app_context():
    sh = Shipment.query.filter_by(shipment_id=sid).one()
    doc = next((d for d in sh.documents if d.doc_type == kind), None)
    status_after_edit = getattr(doc, "status", "?")
checked += 2
print(f"\n④ 확정 {fin.status_code} → 상태 '{status_after_final}' · "
      f"확정 뒤 수정 {edit.status_code} → 상태 '{status_after_edit}'")
if status_after_final == status_after_edit and status_after_final in ("final", "finalized"):
    bad.append("확정한 서류를 고쳤는데 여전히 '확정'으로 남습니다 "
               "(고친 내용이 검증을 안 거칩니다)")

# ⑤ 같은 값을 두 번 저장 — 신고자료
for _ in range(2):
    client.post(f"/documents/{sid}/customs-filing",
                data={"exporter_business_no": "124-81-00998", "customs_trade_kind": "11",
                      "customs_payment_method": "LS", "country_of_origin": "KR · 대한민국"})
with app.app_context():
    sh = Shipment.query.filter_by(shipment_id=sid).one()
    checked += 1
    if sh.exporter_business_no != "124-81-00998":
        bad.append(f"두 번 저장하니 사업자등록번호가 '{sh.exporter_business_no}' 로 바뀜")
print(f"\n⑤ 신고자료 두 번 저장 → 사업자등록번호 '{sh.exporter_business_no}'")

print(f"\n■ 동시·중복 점검 · 확인 {checked}가지 · 문제 {len(bad)}건")
for b in bad: print("   ★", b)
