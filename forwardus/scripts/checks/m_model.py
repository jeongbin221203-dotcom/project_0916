"""저장한 뒤 다시 읽었을 때 값이 앞뒤가 맞는가 — 모델·관계 점검.

화면·계산이 맞아도 DB 에 들어갔다 나오면서 어긋나면 서류가 틀립니다.
"""
import sys, io, random
from decimal import Decimal
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")
from tests._fuzz_app import build_app
from app.extensions import db

ROUNDS = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
random.seed(int(sys.argv[2]) if len(sys.argv) > 2 else 4040)

app = build_app()
bad, checked = [], 0
with app.app_context():
    from app.models import User, Shipment
    from app.services import planning_service, document_service
    uid = User.query.filter_by(email=app.config["MASTER_EMAIL"]).one().id
    TERMS = ["EXW", "FCA", "FAS", "FOB", "CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP"]
    for turn in range(ROUNDS):
        mode = random.choice(["SEA", "AIR"])
        term = random.choice(TERMS)
        count = random.choice([1, 12, 480, 9999])
        price = Decimal(random.choice(["0.55", "12.50", "4820.00"]))
        p = {"project_name": f"모델 {turn}", "transport_mode": mode,
             "sea_mode": random.choice(["FCL", "LCL"]) if mode == "SEA" else None,
             "origin_code": "KRPUS" if mode == "SEA" else "ICN",
             "destination_code": "USLAX" if mode == "SEA" else "LAX",
             "requested_departure_date": "2026-11-02",
             "incoterms": term, "incoterms_confirmed": "1", "currency": "USD",
             "invoice_value": float(price * count),
             "exporter_name": "주식회사 한빛무역", "exporter_address": "부산",
             "buyer": {"name": "SAMPLE CO., LTD.", "country": "US"},
             "cargo": {"product_description": "치약", "hs_code": "3306100000",
                       "package_type": "carton", "quantity": count,
                       "length_cm": 40, "width_cm": 30, "height_cm": 25,
                       "weight_per_package_kg": 8, "unit_price": str(price),
                       "amount": str((price * count).quantize(Decimal("0.01")))}}
        try:
            found = planning_service.search_schedules(p)
            p["schedule_id"] = found["items"][0]["schedule_id"]
            made = planning_service.create_shipment(p, user_id=uid)
        except Exception as error:
            bad.append(f"{turn}: 못 만듦 {type(error).__name__} {error}")
            continue
        sid = made["shipment_id"] if isinstance(made, dict) else made.shipment_id

        # 세션을 비우고 **DB 에서 다시 읽습니다**
        db.session.expire_all()
        sh = Shipment.query.filter_by(shipment_id=sid).one()
        checked += 7
        if sh.incoterms != term:
            bad.append(f"{turn}: 인코텀즈 {sh.incoterms} ≠ {term}")
        if sh.transport_mode != mode:
            bad.append(f"{turn}: 운송수단 {sh.transport_mode} ≠ {mode}")
        if sh.user_id != uid:
            bad.append(f"{turn}: 작성자가 바뀜")
        if not sh.cargo:
            bad.append(f"{turn}: 화물이 안 붙음"); continue
        if sh.cargo.quantity != count:
            bad.append(f"{turn}: 수량 {sh.cargo.quantity} ≠ {count}")
        # 비용 합계가 항목의 합과 맞는가
        if sh.costs:
            total = sum(c.krw_amount for c in sh.costs)
            if sh.total_cost_krw != total:
                bad.append(f"{turn}: 총비용 {sh.total_cost_krw:,} ≠ 항목 합 {total:,}")
        # 날짜 앞뒤
        if sh.etd and sh.eta and sh.eta < sh.etd:
            bad.append(f"{turn}: ETA({sh.eta}) 가 ETD({sh.etd}) 보다 이름")
        if sh.planned_eta and sh.eta and sh.delay_days != (sh.eta - sh.planned_eta).days:
            bad.append(f"{turn}: 지연일수가 안 맞음")

        # 서류를 만들고 다시 읽어도 같은가
        if turn % 50 == 0:
            checked += 2
            document_service.generate_documents(sh)
            db.session.expire_all()
            sh = Shipment.query.filter_by(shipment_id=sid).one()
            if not sh.documents:
                bad.append(f"{turn}: 서류가 안 붙음")
            for doc in sh.documents:
                if doc.shipment_pk != sh.id:
                    bad.append(f"{turn}: 서류가 다른 건에 붙음")
                    break

        # 남의 건은 못 보는가
        if turn % 100 == 0:
            checked += 1
            from app.services import shipment_service, ServiceError
            other = User.query.filter(User.id != uid).first()
            if other is not None:
                try:
                    shipment_service.get_or_404(sid, viewer=other)
                    bad.append(f"{turn}: 남의 건이 보임")
                except ServiceError:
                    pass
        if turn % 200 == 0:
            db.session.expire_all()

print(f"■ 모델·저장 {ROUNDS:,}건 · 확인 {checked:,}가지 · 문제 {len(bad)}건")
seen = {}
for b in bad:
    seen[b.split(": ", 1)[-1][:70]] = seen.get(b.split(": ", 1)[-1][:70], 0) + 1
for key, count in sorted(seen.items(), key=lambda kv: -kv[1])[:12]:
    print(f"   ★ {count:>5}회  {key}")
