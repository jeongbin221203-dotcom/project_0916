"""바깥 세상이 망가졌을 때를 가정한 스윕.

지금까지는 "사람이 이상한 값을 넣으면"이었습니다. 이쪽은 "관세청이 안 되면",
"응답이 깨져서 오면", "품목이 100개면" 같은 것을 봅니다.

    python tests/_fuzz_chaos.py
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from app import create_app
from app.extensions import db
from app.services import ServiceError
from app.validators import ValidationError

# 바깥 API가 낼 수 있는 모든 꼴.
BROKEN_RESPONSES = [
    ("빈 응답", lambda: _response(200, "")),
    ("깨진 XML", lambda: _response(200, "<a><b></a>")),
    ("깨진 JSON", lambda: _response(200, "{oops")),
    ("HTML 오류 페이지", lambda: _response(200, "<html><body>점검 중</body></html>")),
    ("엉뚱한 XML", lambda: _response(200, "<other><x>1</x></other>")),
    ("아주 큰 응답", lambda: _response(200, "<a>" + "x" * 2_000_000 + "</a>")),
    ("401 권한 없음", lambda: _response(401, "no")),
    ("403 거절", lambda: _response(403, "no")),
    ("429 과다 호출", lambda: _response(429, "slow down")),
    ("500 서버 오류", lambda: _response(500, "boom")),
    ("503 점검 중", lambda: _response(503, "maintenance")),
    ("타임아웃", lambda: (_ for _ in ()).throw(httpx.ReadTimeout("느림"))),
    ("연결 끊김", lambda: (_ for _ in ()).throw(httpx.ConnectError("끊김"))),
    ("SSL 오류", lambda: (_ for _ in ()).throw(httpx.ConnectError("SSL"))),
]


def _response(status: int, text: str):
    return httpx.Response(status, text=text, request=httpx.Request("GET", "https://x"))


class Sweep:
    def __init__(self):
        self.crashes: dict[tuple, list] = {}
        self.checked = 0

    def run(self, label, fn, *args, **kwargs):
        self.checked += 1
        try:
            return fn(*args, **kwargs)
        except (ValidationError, ServiceError):
            return None
        except Exception as error:          # noqa: BLE001 - 조사 도구
            where = traceback.extract_tb(error.__traceback__)[-1]
            key = (type(error).__name__, f"{Path(where.filename).name}:{where.lineno}")
            self.crashes.setdefault(key, []).append((label, str(error)[:150]))
            return None

    def report(self) -> int:
        total = sum(len(v) for v in self.crashes.values())
        print(f"\n{'=' * 70}\n검사 {self.checked:,}건 · 예상 못 한 예외 {total}건 "
              f"({len(self.crashes)}곳)\n{'=' * 70}")
        for (kind, where), rows in sorted(self.crashes.items(), key=lambda x: -len(x[1])):
            print(f"\n[{len(rows):>5}건] {kind} @ {where}")
            for label, message in rows[:3]:
                print(f"        {label} -> {message}")
        return len(self.crashes)


def sweep_broken_apis(app, s: Sweep) -> None:
    """바깥 API가 망가져도 화면이 죽지 않아야 합니다."""

    from app.collectors import (carrier_client, container_client, customs_client,
                                exchange_client, tariff_client)
    from app.services import planning_service as ps

    calls = [
        ("HS 검색", lambda: customs_client.search_hs_codes("샴푸")),
        ("관세율", lambda: customs_client.fetch_tariff_rates("3305100000")),
        ("국가코드", lambda: customs_client.fetch_country_codes()),
        ("환율", lambda: exchange_client.fetch_krw_rates()),
        ("선사 목록", lambda: carrier_client.search_shipping_companies("에이치엠엠")),
        ("선사 내역", lambda: carrier_client.shipping_company("HDMU")),
        ("도착국 관세", lambda: tariff_client.fetch_wits("410", "484", "330510")),
        ("미국 관세율표", lambda: tariff_client.fetch_us_hts("3305.10")),
        ("통관 진행", lambda: container_client.cargo_progress(cargo_no="00ANLU083N59007001")),
        ("컨테이너", lambda: container_client.container_detail("00ANLU083N59007001")),
        ("수출이행", lambda: container_client.export_performance(declaration_no="1" * 15)),
    ]

    with app.app_context():
        for name, make in BROKEN_RESPONSES:
            with patch("httpx.request", side_effect=lambda *a, **k: make()):
                for label, call in calls:
                    result = s.run(f"{label} · {name}", call)
                    # 결과 모양이 무너지면 화면이 다음 줄에서 죽습니다.
                    if result is not None and not isinstance(result, dict):
                        s.crashes.setdefault(("BAD_SHAPE", label), []).append(
                            (f"{label} · {name}", f"dict가 아님: {type(result).__name__}"))
                    elif isinstance(result, dict) and "success" not in result:
                        s.crashes.setdefault(("BAD_SHAPE", label), []).append(
                            (f"{label} · {name}", f"success 없음: {list(result)[:5]}"))

                # 서비스 계층도 같은 상황에서 버텨야 합니다.
                s.run(f"HS 서비스 · {name}", ps.search_hs_codes, "샴푸")
                s.run(f"환율 서비스 · {name}", ps.exchange_rates)
                s.run(f"스케줄 · {name}", ps.search_schedules, {
                    "project_name": "t", "transport_mode": "SEA", "sea_mode": "FCL",
                    "origin_code": "KRPUS", "destination_code": "USLAX",
                    "requested_departure_date": "2026-11-02",
                    "cargo": {"items": [{"product_description": "샴푸", "package_type": "carton",
                                         "quantity": 10, "length_cm": 40, "width_cm": 30,
                                         "height_cm": 25, "weight_per_package_kg": 12}]}})


def sweep_scale(app, s: Sweep) -> None:
    """품목이 아주 많거나 값이 아주 클 때."""

    from app.services import document_service as ds, planning_service as ps

    def item(index: int) -> dict:
        return {"product_description": f"품목 {index}", "hs_code": "3305100000",
                "package_type": "carton", "quantity": 1, "length_cm": 10,
                "width_cm": 10, "height_cm": 10, "weight_per_package_kg": 1,
                "amount": "10"}

    with app.app_context():
        for count in (1, 2, 20, 100, 300):
            payload = {"cargo": {"items": [item(i) for i in range(count)]}}
            metrics = s.run(f"품목 {count}개 계산", ps.cargo_metrics, payload)
            if metrics:
                assert len(metrics["lines"]) == count

        # 아주 큰 화물 (컨테이너가 수백 대)
        huge = {"product_description": "벌크", "package_type": "carton",
                "quantity": 90_000, "length_cm": 200, "width_cm": 200,
                "height_cm": 200, "weight_per_package_kg": 30_000}
        s.run("아주 큰 화물", ps.cargo_metrics, {"cargo": {"items": [huge]}})

        # 아주 작은 화물 (반올림에서 0이 되는지)
        tiny = {"product_description": "샘플", "package_type": "carton",
                "quantity": 1, "length_cm": 0.1, "width_cm": 0.1,
                "height_cm": 0.1, "weight_per_package_kg": 0.001}
        result = s.run("아주 작은 화물", ps.cargo_metrics, {"cargo": {"items": [tiny]}})
        if result and result["total_cbm"] == 0:
            s.crashes.setdefault(("ZERO_CBM", "cargo_calculator"), []).append(
                ("아주 작은 화물", "CBM이 0으로 떨어져 운임을 못 냅니다"))

        # 아주 긴 글이 DB 칸을 넘는지
        long_payload = {
            "project_name": "가" * 500, "transport_mode": "SEA", "sea_mode": "LCL",
            "origin_code": "KRPUS", "destination_code": "USLAX",
            "requested_departure_date": "2026-11-02", "incoterms": "FOB",
            "currency": "USD", "invoice_value": "5000",
            "cargo": {"items": [{**item(0), "product_description": "나" * 1000,
                                 "hs_code": "3" * 50}]},
            "exporter_name": "다" * 500, "exporter_address": "라" * 2000,
            "notify_party": "마" * 1000,
            "buyer": {"name": "바" * 500, "country": "사" * 200,
                      "address": "아" * 2000, "contact_email": "x" * 500 + "@b.c"},
        }
        found = s.run("아주 긴 글 스케줄", ps.search_schedules, long_payload)
        if found and found["items"]:
            long_payload["schedule_id"] = found["items"][0]["schedule_id"]
            shipment = s.run("아주 긴 글 저장", ps.create_shipment, long_payload)
            if shipment:
                s.run("아주 긴 글 서류", ds.generate_documents, shipment)
                s.run("아주 긴 글 검증", ds.check_documents, shipment)


def sweep_repeat(app, s: Sweep) -> None:
    """같은 일을 여러 번 해도 같아야 합니다. (두 번 누르기)"""

    from app.services import document_service as ds, planning_service as ps

    with app.app_context():
        payload = {
            "project_name": "두 번 누르기", "transport_mode": "SEA", "sea_mode": "LCL",
            "origin_code": "KRPUS", "destination_code": "USLAX",
            "requested_departure_date": "2026-11-02", "incoterms": "FOB",
            "currency": "USD", "invoice_value": "5000",
            "cargo": {"items": [{"product_description": "샴푸", "hs_code": "3305100000",
                                 "package_type": "carton", "quantity": 10, "length_cm": 40,
                                 "width_cm": 30, "height_cm": 25, "weight_per_package_kg": 12}]},
            "exporter_name": "포워더스", "buyer": {"name": "ACME", "country": "US"},
        }
        payload["schedule_id"] = ps.search_schedules(payload)["items"][0]["schedule_id"]

        ids = []
        for _ in range(5):                      # 같은 요청을 다섯 번 (더블클릭)
            shipment = s.run("같은 요청 반복", ps.create_shipment, payload)
            if shipment:
                ids.append(shipment.shipment_id)
        if len(set(ids)) != len(ids):
            s.crashes.setdefault(("DUPLICATE_ID", "shipment_repository"), []).append(
                ("같은 요청 반복", f"번호가 겹칩니다: {ids}"))

        if ids:
            from app.repositories import shipment_repository
            shipment = shipment_repository.get_by_shipment_id(ids[0])
            for _ in range(5):
                s.run("서류 반복 생성", ds.generate_documents, shipment)
                s.run("서류 반복 검증", ds.validate_shipment_documents, shipment)


def main() -> int:
    app = create_app()
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    s = Sweep()
    with app.app_context():
        db.create_all()
    sweep_broken_apis(app, s)
    sweep_scale(app, s)
    sweep_repeat(app, s)
    return s.report()


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
