"""무작위 조합으로 크게 돌리는 스윕. 실제 화면 흐름을 통째로 흉내 냅니다.

_fuzz_sweep.py가 함수 하나하나를 찌른다면, 이쪽은 "사람이 이렇게 입력할 수도
있다"를 수만 가지로 만들어 운송 계획 전체를 돌려 봅니다.

    python tests/_fuzz_deep.py [반복횟수]
"""

from __future__ import annotations

import random
import string
import sys
import traceback
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app
from app.services import ServiceError
from app.validators import ValidationError

PORTS = ["KRPUS", "KRKAN", "KRINC", "KRKUV", "", "ZZZZZ", None, "krpus", "  KRPUS  "]
DEST_PORTS = ["USLAX", "MXZLO", "DEBRV", "CNSHA", "JPTYO", "", "ZZZZZ", None, "USLAX "]
AIRPORTS = ["ICN", "PUS", "MWX", "CJU", "", "ZZZ", None]
DEST_AIRPORTS = ["MEX", "LAX", "FRA", "NRT", "", "ZZZ", None]
MODES = ["SEA", "AIR", "", None, "sea", "TRUCK", 1]
SEA_MODES = ["FCL", "LCL", "", None, "fcl", "BULK"]
INCOTERMS = ["EXW", "FCA", "FAS", "FOB", "CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP",
             "", None, "xxx", "fob"]
CURRENCIES = ["USD", "KRW", "EUR", "JPY", "CNY", "", None, "ZZZ", "usd"]
PACKAGES = ["carton", "pallet", "wooden_crate", "drum", "flexible_bag", "uld", "bulk",
            "", None, "box", 1]
HS = ["3305100000", "3306.10-0000", "8471300000", "", None, "12345", "9" * 20,
      "abcd", "0000000000", "샴푸", "toothpaste"]
DG_CLASSES = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "", None, "10", "3.1"]
UN = ["UN1263", "1263", "UN0001", "", None, "UN12345", "ABCD", "UN 1263"]
PG = ["I", "II", "III", "", None, "IV", "1"]

NUMBERS = [0, 1, -1, 0.5, 40, 1000, 99999, 10 ** 9, "", None, "abc", "1,000",
           "  20  ", "1e5", float("nan"), float("inf"), True, -0.0001, "0"]

TEXT = ["샴푸", "Shampoo 500ml", "", None, " ", "가" * 500, "x" * 2000,
        "<b>x</b>", "'; DROP TABLE--", "\x00", "😀 제품", 123]


def a_date(rng: random.Random):
    choices = [
        (date.today() + timedelta(days=rng.randint(-400, 800))).isoformat(),
        "", None, "2026-13-45", "not-a-date", "2026/10/01", "20261001",
        date.today().isoformat(), "0000-01-01", "9999-12-31",
    ]
    return rng.choice(choices)


def a_cargo(rng: random.Random) -> dict:
    item = {
        "product_description": rng.choice(TEXT),
        "hs_code": rng.choice(HS),
        "package_type": rng.choice(PACKAGES),
        "length_cm": rng.choice(NUMBERS),
        "width_cm": rng.choice(NUMBERS),
        "height_cm": rng.choice(NUMBERS),
        "quantity": rng.choice(NUMBERS),
        "weight_per_package_kg": rng.choice(NUMBERS),
    }
    if rng.random() < 0.5:
        item["net_weight_kg"] = rng.choice(NUMBERS)
    if rng.random() < 0.4:
        item["amount"] = rng.choice(NUMBERS)
    if rng.random() < 0.3:
        item["unit_price"] = rng.choice(NUMBERS)
    if rng.random() < 0.35:
        item.update({
            "is_dangerous": rng.choice([True, False, "on", "", None, 1, "yes"]),
            "un_number": rng.choice(UN),
            "dg_class": rng.choice(DG_CLASSES),
            "packing_group": rng.choice(PG),
            "proper_shipping_name": rng.choice(TEXT),
        })
    return item


def a_payload(rng: random.Random) -> dict:
    air = rng.random() < 0.35
    items = [a_cargo(rng) for _ in range(rng.choice([0, 1, 1, 1, 2, 3, 5]))]
    payload = {
        "project_name": rng.choice(TEXT),
        "transport_mode": rng.choice(MODES) if rng.random() < 0.3 else ("AIR" if air else "SEA"),
        "sea_mode": rng.choice(SEA_MODES),
        "origin_code": rng.choice(AIRPORTS if air else PORTS),
        "destination_code": rng.choice(DEST_AIRPORTS if air else DEST_PORTS),
        "requested_departure_date": a_date(rng),
        "buyer_required_date": a_date(rng),
        "incoterms": rng.choice(INCOTERMS),
        "currency": rng.choice(CURRENCIES),
        "invoice_value": rng.choice(NUMBERS),
        "cargo": {"items": items} if rng.random() < 0.7 else (items or {}),
        "exporter_name": rng.choice(TEXT),
        "exporter_address": rng.choice(TEXT),
        "notify_party": rng.choice(TEXT),
        "buyer": {
            "name": rng.choice(TEXT), "country": rng.choice(["KR", "US", "", None, "ZZ"]),
            "address": rng.choice(TEXT),
            "contact_email": rng.choice(["a@b.c", "", None, "not-an-email", "a" * 300]),
        },
        "schedule_id": rng.choice(["", None, "bogus", 1]),
    }
    if rng.random() < 0.15:                       # 통째로 이상한 모양
        payload["cargo"] = rng.choice(["x", 1, None, [], [1], {"items": "x"}])
    if rng.random() < 0.1:
        payload["buyer"] = rng.choice(["x", 1, None, []])
    return payload


def main(rounds: int) -> int:
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    rng = random.Random(20260920)

    crashes: dict[tuple, list] = {}
    checked = 0

    endpoints = ["/planning/api/cargo", "/planning/api/schedule-outlook",
                 "/planning/api/schedules", "/planning/api/shipments"]

    with app.app_context():
        from app.services import planning_service as ps

        for round_no in range(rounds):
            payload = a_payload(rng)
            calls = [
                ("cargo_items", lambda: ps.cargo_items(payload)),
                ("cargo_metrics", lambda: ps.cargo_metrics(payload)),
                ("calculate_cargo", lambda: ps.calculate_cargo(payload)),
                ("transit_summary", lambda: ps.transit_summary(
                    payload["origin_code"], payload["destination_code"])),
                ("schedule_outlook", lambda: ps.schedule_outlook(payload)),
                ("create_shipment", lambda: ps.create_shipment(payload)),
            ]
            for label, fn in calls:
                checked += 1
                try:
                    fn()
                except (ValidationError, ServiceError):
                    pass
                except Exception as error:      # noqa: BLE001 - 조사 도구
                    where = traceback.extract_tb(error.__traceback__)[-1]
                    key = (type(error).__name__, f"{Path(where.filename).name}:{where.lineno}")
                    crashes.setdefault(key, []).append((label, str(error)[:150], payload))

            if round_no % 4 == 0:                 # HTTP도 같은 몸통으로 찔러 봅니다.
                for path in endpoints:
                    checked += 1
                    response = client.post(path, json=payload)
                    if response.status_code >= 500:
                        key = ("HTTP500", path)
                        crashes.setdefault(key, []).append(
                            (path, response.get_data(as_text=True)[:150], payload))

    print(f"\n{'=' * 70}\n무작위 {rounds:,}회 · 호출 {checked:,}건 · "
          f"예상 못 한 예외 {sum(len(v) for v in crashes.values())}건 "
          f"({len(crashes)}곳)\n{'=' * 70}")
    for (kind, where), rows in sorted(crashes.items(), key=lambda x: -len(x[1])):
        print(f"\n[{len(rows):>5}건] {kind} @ {where}")
        label, message, payload = rows[0]
        print(f"        {label} -> {message}")
        print(f"        입력: {_brief(payload)}")
    return len(crashes)


def _brief(payload: dict) -> str:
    keep = {k: payload.get(k) for k in
            ("transport_mode", "sea_mode", "origin_code", "destination_code",
             "requested_departure_date", "incoterms", "currency", "invoice_value")}
    cargo = payload.get("cargo")
    keep["cargo"] = (f"{len(cargo['items'])}품목" if isinstance(cargo, dict)
                     and isinstance(cargo.get("items"), list) else repr(cargo)[:40])
    return repr(keep)[:400]


if __name__ == "__main__":
    sys.exit(1 if main(int(sys.argv[1]) if len(sys.argv) > 1 else 2000) else 0)
