"""⑱ 문서 자동작성 · ⑲ 관세사 자료 · ⑳ Document Center — 값이 **맞게 실리는가**.

화면이 열리는 것과 맞는 값이 적히는 것은 다릅니다. 관세사에게 넘기는 자료가
건의 실제 값과 어긋나면, 그대로 신고되고 사후에 정정해야 합니다.
"""
import sys, io, random
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")
from decimal import Decimal
from tests._fuzz_app import build_app
from app.services import planning_service, customs_filing_service, document_service

ROUNDS = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
random.seed(int(sys.argv[2]) if len(sys.argv) > 2 else 1819)

PORTS = [("KRPUS", "USLAX"), ("KRINC", "NLRTM"), ("KRPUS", "SGSIN"), ("KRPUS", "DEHAM")]
TERMS = ["EXW", "FCA", "FOB", "CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP"]
app = build_app()
bad, checked = [], 0
with app.app_context():
    from app.models import User
    uid = User.query.filter_by(email=app.config["MASTER_EMAIL"]).one().id
    for turn in range(ROUNDS):
        origin, dest = random.choice(PORTS)
        term = random.choice(TERMS)
        count = random.choice([1, 7, 48, 365, 1200])
        price = Decimal(random.choice(["0.55", "12.50", "199.99", "4820.00"]))
        rows = []
        for _ in range(random.randint(1, 4)):
            rows.append({"product_description": random.choice(["치약", "샴푸", "감귤", "LED 램프"]),
                         "hs_code": random.choice(["3306100000", "3305100000", "0805100000"]),
                         "package_type": "carton", "quantity": count,
                         "length_cm": 40, "width_cm": 30, "height_cm": 25,
                         "weight_per_package_kg": 8,
                         "unit_price": str(price),
                         "amount": str((price * count).quantize(Decimal("0.01")))})
        payload = {"project_name": f"검사 {turn}", "transport_mode": "SEA", "sea_mode": "LCL",
                   "origin_code": origin, "destination_code": dest,
                   "requested_departure_date": "2026-11-02",
                   "incoterms": term, "currency": "USD",
                   "invoice_value": float(sum(Decimal(r["amount"]) for r in rows)),
                   "exporter_name": "주식회사 한빛무역", "exporter_address": "부산광역시",
                   "buyer": {"name": "SAMPLE CO., LTD.", "country": dest[:2],
                             "address": "Los Angeles"},
                   "items": rows, "cargo": rows[0]}
        try:
            found = planning_service.search_schedules(payload)
            payload["schedule_id"] = found["items"][0]["schedule_id"]
            made = planning_service.create_shipment(payload, user_id=uid)
        except Exception as error:
            bad.append(f"{turn}: 건을 못 만듦 {type(error).__name__} {error}")
            continue
        from app.models import Shipment
        shipment = Shipment.query.filter_by(
            shipment_id=made["shipment_id"] if isinstance(made, dict) else made.shipment_id).one()

        # ⑲ 관세사 전달용 자료
        checked += 4
        try:
            sheet = customs_filing_service.filing_sheet(shipment)
            text = customs_filing_service.as_text(sheet)
            missing = customs_filing_service.describe_missing(sheet)
        except Exception as error:
            bad.append(f"{turn}: 신고자료 죽음 {type(error).__name__} {error}")
            continue
        # 건의 값이 자료에 그대로 실려야 합니다
        flat = " ".join(str(row.get("value", "")) for block in
                        (sheet.get("rows") or sheet.get("blocks") or []) for row in
                        (block.get("rows", [block]) if isinstance(block, dict) else [block]))
        blob = f"{flat} {text}"
        for label, value in (("인코텀즈", term), ("적재항", origin), ("도착항", dest)):
            if value not in blob:
                bad.append(f"{turn}: 신고자료에 {label} '{value}' 가 없음")
        # 사업자등록번호를 안 적었으면 '비어 있다'고 말해야 합니다
        if "사업자" not in (missing or "") and not shipment.exporter_business_no:
            bad.append(f"{turn}: 사업자등록번호가 비었는데 알려 주지 않음")

        # ⑱ 문서 자동작성 → ⑳ 서류 간 검증
        checked += 2
        try:
            document_service.generate_documents(shipment)
        except Exception as error:
            bad.append(f"{turn}: 자동작성 죽음 {type(error).__name__} {error}")
            continue
        try:
            findings = document_service.validate_shipment_documents(shipment)
        except Exception as error:
            bad.append(f"{turn}: 서류 간 검증 죽음 {type(error).__name__} {error}")
            continue
        # 막 만든 서류끼리는 어긋난 곳이 없어야 합니다
        cross = [f for f in (findings.get("findings") or findings if isinstance(findings, dict)
                             else findings)
                 if isinstance(f, dict) and f.get("kind") in ("cross", "reference")]
        if cross:
            bad.append(f"{turn}: 막 만든 서류인데 값이 어긋난다고 함 — "
                       f"{[c.get('message', '')[:60] for c in cross[:2]]}")

print(f"■ ⑱⑲⑳ {ROUNDS:,}건 · 확인 {checked:,}가지 · 문제 {len(bad)}건")
seen = {}
for b in bad:
    seen[b.split(": ", 1)[-1][:70]] = seen.get(b.split(": ", 1)[-1][:70], 0) + 1
for key, count in sorted(seen.items(), key=lambda kv: -kv[1])[:10]:
    print(f"   ★ {count:>5}회  {key}")
